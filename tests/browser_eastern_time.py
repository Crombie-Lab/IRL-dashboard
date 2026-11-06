"""Optional browser regression check; requires development-only Playwright/Chromium.

Run against a built local preview or the public site using --url. The timestamp
examples exercise timezone rules; they are not synthetic monitoring observations.
"""
import argparse
from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser()
parser.add_argument('--url', default='http://127.0.0.1:8765/')
args = parser.parse_args()
with sync_playwright() as p:
    browser = p.chromium.launch(args=['--no-sandbox', '--disable-dev-shm-usage'])
    for width, zone in ((1280, 'UTC'), (390, 'America/Los_Angeles')):
        page = browser.new_page(viewport={'width': width, 'height': 900}, timezone_id=zone)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(args.url, wait_until='networkidle')
        page.wait_for_function("document.querySelectorAll('.js-plotly-plot').length === 5")
        result = page.evaluate('''async () => {
            const f=EasternTime.format;
            const examples=[
                ['2026-11-06T13:15:00Z','8:15 AM EST'],
                ['2026-11-06T04:30:00Z','11:30 PM EST'],
                ['2026-07-04T16:00:00Z','12:00 PM EDT'],
                ['2026-11-01T05:00:00Z','1:00 AM EDT'],
                ['2026-11-01T06:00:00Z','1:00 AM EST'],
                ['2026-03-08T06:00:00Z','1:00 AM EST'],
                ['2026-03-08T07:00:00Z','3:00 AM EDT']
            ];
            for(const [instant,expected] of examples)
                if(!f(instant).includes(expected)) throw Error(instant+': '+f(instant));
            const dst=EasternTime.ticks(Date.parse('2026-11-01T04:00:00Z'),Date.parse('2026-11-01T08:00:00Z'),1200);
            if(!dst.ticktext.some(t=>t.includes('1:00 AM EDT'))||!dst.ticktext.some(t=>t.includes('1:00 AM EST')))
                throw Error('Repeated fall-back hour lost');
            const ids=['stageplot','forecastplot','qualityplot','tideplot','pressureplot'];
            for(const id of ids){
                const g=document.getElementById(id);
                if(g.layout.xaxis.title.text!=='Eastern time') throw Error(id+' axis title');
                if(g.layout.xaxis.ticktext.some(t=>!/E[SD]T/.test(t))) throw Error(id+' axis timezone');
                if(g.data.some(t=>!t.hovertemplate||t.hovertemplate.includes('%{x'))) throw Error(id+' UTC hover');
            }
            const g=document.getElementById('stageplot'),initial=g.layout.xaxis.range.slice();
            const initialTicks=g.layout.xaxis.tickvals.slice();
            const shifted=initial.map(t=>new Date(Date.parse(t)-86400000).toISOString());
            await Plotly.relayout(g,{'xaxis.range':shifted});
            if(JSON.stringify(initialTicks)===JSON.stringify(g.layout.xaxis.tickvals)) throw Error('Pan did not refresh ticks');
            if(Date.parse(g.layout.xaxis.range[1])-Date.parse(g.layout.xaxis.range[0])!==72*3600000) throw Error('Pan changed elapsed window');
            document.getElementById('forecast-full').click();
            await new Promise(resolve=>setTimeout(resolve,100));
            const forecast=document.getElementById('forecastplot');
            if(forecast.layout.xaxis.ticktext.some(t=>!/E[SD]T/.test(t))) throw Error('Full forecast ticks');
            document.getElementById('reset-views').click();
            await new Promise(resolve=>setTimeout(resolve,100));
            if(JSON.stringify(initial)!==JSON.stringify(g.layout.xaxis.range)) throw Error('Reset changed instants');
            return {examples:examples.length,plots:ids.length,dstTicks:dst.ticktext};
        }''')
        # Exercise actual pointer hovers: WebGL traces do not implement the
        # point-number programmatic-hover shortcut used by SVG traces.
        for plot in ('stageplot', 'forecastplot', 'qualityplot', 'tideplot', 'pressureplot'):
            page.locator('#' + plot).scroll_into_view_if_needed()
            point = page.evaluate('''id => {
                const g=document.getElementById(id),trace=g.data[0],a=g._fullLayout.xaxis,y=g._fullLayout.yaxis;
                const middle=(Date.parse(a.range[0])+Date.parse(a.range[1]))/2;
                const i=trace.y.findIndex((value,i)=>value!=null&&Date.parse(trace.x[i])>=middle);
                const box=g.getBoundingClientRect();
                return {x:box.left+a._offset+a.d2p(trace.x[i]),y:box.top+y._offset+y.d2p(trace.y[i])};
            }''', plot)
            page.mouse.move(point['x'], point['y'])
            page.wait_for_timeout(150)
            hover = page.locator('#' + plot + ' .hoverlayer').text_content()
            assert ('EST' in hover or 'EDT' in hover) and 'UTC' not in hover, (plot, hover)
        assert not errors, errors
        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
        print(width, zone, 'PASS', result, flush=True)
        page.screenshot(path=f'/tmp/irl-eastern-{width}.png', full_page=True)
        page.close()
    browser.close()
