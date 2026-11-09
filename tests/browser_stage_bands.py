"""Optional Playwright check for exploratory level colors and gauge-only shading.

Run against a built local preview using --url. Boundary examples replace the
latest gauge value only in browser memory; they are never saved as observations.
"""
import argparse
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright


parser = argparse.ArgumentParser()
parser.add_argument('--url', default='http://127.0.0.1:8765/')
args = parser.parse_args()
cases = [(1.651999, 'green'), (1.652, 'yellow'), (1.7, 'yellow'),
         (1.744, 'yellow'), (1.744001, 'orange'), (1.9, 'orange'),
         (1.994, 'orange'), (1.994001, 'red'), (2.2, 'red'),
         ('missing', None)]

with sync_playwright() as p:
    browser = p.chromium.launch(args=['--no-sandbox', '--disable-dev-shm-usage'])
    for width in (1280, 390):
        page = browser.new_page(viewport={'width': width, 'height': 900})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.add_init_script('''
            document.addEventListener('DOMContentLoaded', () => {
                const value=new URLSearchParams(location.search).get('test_stage');
                if(value===null) return;
                const model=document.getElementById('model');
                const payload=JSON.parse(model.textContent);
                if(value==='missing') payload.williams_point=[];
                else payload.williams_point[payload.williams_point.length-1].v=Number(value);
                model.textContent=JSON.stringify(payload);
            });
        ''')
        for value, expected in cases:
            page.goto(args.url + ('&' if '?' in args.url else '?') +
                      urlencode({'test_stage': value}), wait_until='load')
            page.wait_for_function("document.getElementById('stageplot')._fullLayout !== undefined")
            result = page.evaluate('''async () => {
                const value=document.getElementById('stage-now');
                const g=document.getElementById('stageplot');
                const shapes=g.layout.shapes||[];
                const range=g.layout.yaxis.range;
                for(const s of shapes){
                    if(s.xref!=='x domain'||s.yref!=='y'||s.x0!==0||s.x1!==1||s.layer!=='below')
                        throw Error('Band escapes the gauge panel');
                    if(s.y0<range[0]||s.y1>range[1]||s.y1<=s.y0)
                        throw Error('Band changes/escapes the full-trace gauge scale');
                }
                const original=JSON.stringify(shapes);
                const initial=g.layout.xaxis.range.slice();
                const shifted=initial.map(t=>new Date(Date.parse(t)-86400000).toISOString());
                await Plotly.relayout(g,{'xaxis.range':shifted});
                document.getElementById('reset-views').click();
                if(JSON.stringify(g.layout.shapes||[])!==original) throw Error('Pan/reset changed bands');
                if(!g.layout.yaxis.fixedrange||g.layout.dragmode!=='pan') throw Error('Navigation changed');
                for(const id of ['forecastplot','qualityplot','tideplot','pressureplot'])
                    if(document.getElementById(id).layout?.shapes?.length) throw Error('Unrelated chart shaded');
                if(document.documentElement.scrollWidth>innerWidth) throw Error('Horizontal page overflow');
                return {band:value.dataset.levelBand||null,text:value.textContent,
                    color:getComputedStyle(value).color,shapes:shapes.length,
                    manualBand:document.getElementById('manual-now').className};
            }''')
            assert result['band'] == expected, (width, value, result)
            if expected is None:
                assert result['text'] == 'Unavailable' and result['shapes'] == 0, result
            else:
                assert result['shapes'] > 0, result
            assert not errors, errors
            print(width, value, 'PASS', result, flush=True)
        # Inspect an unchanged real snapshot after the browser-only examples.
        page.goto(args.url, wait_until='load')
        page.wait_for_function("document.getElementById('stageplot')._fullLayout !== undefined")
        page.screenshot(path=f'/tmp/irl-level-bands-{width}.png', full_page=True)
        page.close()
    browser.close()
