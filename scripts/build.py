#!/usr/bin/env python3
"""Generate a GitHub Pages lagoon dashboard from recent public observations.

Requires Python 3.11+. Only Python standard library. No forecasting or alerts.
"""
import csv
import io
import json
import math
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / 'site'
IEM = 'https://mesonet.agron.iastate.edu/cgi-bin/request/hml.py'
COOPS = 'https://api.tidesandcurrents.noaa.gov/api/prod/datagetter'
HEADERS = {'User-Agent': 'IRL-dashboard/0.1 (public environmental data visualization)'}


def get_bytes(base, params, max_attempts=4):
    url = base + '?' + urlencode(params)
    for attempt in range(max_attempts):
        try:
            with urlopen(Request(url, headers=HEADERS), timeout=45) as response:
                payload = response.read()
            if not payload:
                raise ValueError('Empty HTTP response')
            return payload
        except HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == max_attempts - 1:
                raise
            retry = exc.headers.get('Retry-After', '')
            delay = min(90, max(3 * 2 ** attempt, int(retry) if retry.isdigit() else 0))
            time.sleep(delay)
        except (URLError, TimeoutError) as exc:
            if attempt == max_attempts - 1:
                raise
            time.sleep(min(30, 3 * 2 ** attempt))
    raise RuntimeError('Exhausted HTTP retries')


def utc_timestamp(value):
    raw = str(value).strip().replace('Z', '+00:00')
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat(timespec='minutes')


def safe_float(value):
    try:
        f = float(value)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def select_stage_column(columns):
    normalized = {c: re.sub(r'[^a-z0-9]+', '', c.lower()) for c in columns}
    priority = ('primary', 'primaryvalue', 'stage', 'stageft', 'gageheight', 'heightft', 'waterlevel')
    for keyword in priority:
        for original, compact in normalized.items():
            if compact == keyword:
                return original
    for original, compact in normalized.items():
        if compact.startswith(('stage', 'primary', 'gageheight')):
            return original
    raise ValueError('Cannot identify IEM stage column; CSV columns: ' + ', '.join(columns))


def parse_iem(payload):
    source = io.StringIO(payload.decode('utf-8-sig'))
    lines = [line for line in source if line.strip() and not line.lstrip().startswith('#')]
    rows = list(csv.DictReader(lines))
    if not rows:
        raise ValueError('No Williams Point HML observations returned')
    fields = list(rows[0])
    stamp_field = next((name for name in fields if name.lower().startswith('valid')), None)
    if not stamp_field:
        raise ValueError('No valid time in IEM response; columns: ' + ', '.join(fields))
    stage_field = select_stage_column(fields)
    observations = {}
    for row in rows:
        if str(row.get('station', 'WIPF1')).strip().upper() != 'WIPF1':
            continue
        stage = safe_float(row.get(stage_field))
        if stage is None or not -50 < stage < 50:
            continue
        try:
            ts = utc_timestamp(row[stamp_field])
        except (ValueError, TypeError):
            continue
        observations[ts] = {'t': ts, 'v': stage}
    result = [observations[key] for key in sorted(observations)]
    if not result:
        raise ValueError('IEM CSV has no parseable water level values; headers: ' + ', '.join(fields))
    return result


def parse_coops(payload, product):
    body = json.loads(payload)
    if 'error' in body:
        raise ValueError(f'NOAA {product}: {body["error"]}')
    records = body.get('predictions' if product == 'predictions' else 'data')
    if not isinstance(records, list):
        raise ValueError(f'NOAA {product} has no data list')
    results = []
    for row in records:
        try:
            timestamp = utc_timestamp(row['t'])
        except (KeyError, ValueError, TypeError):
            continue
        if product == 'wind':
            speed, direction, gust = (safe_float(row.get(k)) for k in ('s','d','g'))
            if speed is not None and 0 <= speed <= 100:
                results.append({'t': timestamp, 'speed': speed, 'direction': direction, 'gust': gust})
        else:
            val = safe_float(row.get('v'))
            if val is not None:
                results.append({'t': timestamp, 'v': val})
    return sorted(results, key=lambda item: item['t'])


def coops_recent(product, start, end, *, datum=None, interval=None):
    params = {
        'station': '8721604', 'product': product,
        'begin_date': start.strftime('%Y%m%d'),
        'end_date': end.strftime('%Y%m%d'),
        'time_zone': 'gmt', 'units': 'metric', 'format': 'json',
        'application': 'irl_dashboard',
    }
    if datum:
        params['datum'] = datum
    if interval:
        params['interval'] = interval
    return parse_coops(get_bytes(COOPS, params), product)


def metrics(series):
    if not series:
        return {'count': 0, 'last': None, 'latest': None}
    return {'count': len(series), 'last': series[-1]['t'], 'latest': series[-1]}


def render(payload):
    SITE.mkdir(parents=True, exist_ok=True)
    template = (ROOT / 'templates' / 'index.html').read_text(encoding='utf-8')
    content = json.dumps(payload, separators=(',', ':'), ensure_ascii=False).replace('</', '<\\/')
    (SITE / 'index.html').write_text(template.replace('/*__PAYLOAD__*/', content), encoding='utf-8')
    (SITE / '.nojekyll').touch()
    (SITE / 'data.json').write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')


def run():
    now = datetime.now(UTC)
    stage_start = now - timedelta(days=14)
    tide_start = now - timedelta(days=7)
    future = now + timedelta(days=3)
    # Williams Point is mandatory; don't replace the previously published site with an empty chart.
    stage_params = {'station':'WIPF1','sts': stage_start.strftime('%Y-%m-%dT%H:%MZ'),
                    'ets': now.strftime('%Y-%m-%dT%H:%MZ'), 'fmt':'csv','kind':'obs','tz':'UTC'}
    stage = parse_iem(get_bytes(IEM, stage_params))
    warnings = []
    sources = {}
    optional = {
        'wind': lambda: coops_recent('wind', tide_start, now, interval='h'),
        'pressure': lambda: coops_recent('air_pressure', tide_start, now, interval='h'),
        'ocean': lambda: coops_recent('water_level', tide_start, now, datum='MLLW'),
        'tide': lambda: coops_recent('predictions', tide_start, future, datum='MLLW', interval='h'),
    }
    for name, fn in optional.items():
        try:
            sources[name] = fn()
            if not sources[name]:
                warnings.append(f'{name}: the source returned no observations')
        except (HTTPError, URLError, ValueError, TimeoutError, json.JSONDecodeError) as exc:
            sources[name] = []
            warnings.append(f'{name}: {type(exc).__name__}: {exc}')
    document = {
        'built_utc': now.isoformat(timespec='seconds'),
        'williams_point': stage,
        'trident': sources,
        'status': {'williams_point': metrics(stage), **{k: metrics(v) for k,v in sources.items()}},
        'warnings': warnings,
        'source_notes': {'stage': 'Iowa Environmental Mesonet HML observation archive; WIPF1',
                         'trident': 'NOAA CO-OPS station 8721604; metric units; ocean levels in MLLW'},
    }
    render(document)
    print(f'WIPF1 observations: {len(stage)} | latest {stage[-1]["t"]}')
    for label, series in sources.items():
        print(f'{label}: {len(series)} records')
    if warnings:
        print('Source warnings: ' + ' | '.join(warnings), file=sys.stderr)
    print('Built site/index.html')


if __name__ == '__main__':
    run()
