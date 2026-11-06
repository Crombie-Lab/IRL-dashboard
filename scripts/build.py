#!/usr/bin/env python3
"""Generate a GitHub Pages lagoon dashboard from recent public observations.

Requires Python 3.11+. Only Python standard library. Includes separate NOAA weather forecasts; no flood modeling or alerts.
"""
import csv
import io
import json
import math
import re
import sys
import shutil
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / 'site'
IEM = 'https://mesonet.agron.iastate.edu/cgi-bin/request/hml.py'
COOPS = 'https://api.tidesandcurrents.noaa.gov/api/prod/datagetter'
NWS_POINT = 'https://api.weather.gov/points/28.3903,-80.8026'
HEADERS = {'User-Agent': 'IRL-dashboard/0.2 (https://github.com/Crombie-Lab/IRL-dashboard)'}


def get_bytes(base, params, max_attempts=4):
    url = base + ('?' + urlencode(params) if params else '')
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
            try:
                retry_seconds = float(retry) if retry.isdigit() else (parsedate_to_datetime(retry) - datetime.now(UTC)).total_seconds()
            except (ValueError, TypeError, OverflowError):
                retry_seconds = 0
            if retry_seconds > 90:
                raise  # Preserve the published site rather than retry before the provider permits.
            delay = min(90, max(3 * 2 ** attempt, retry_seconds))
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
        if compact.startswith(('stage', 'primary', 'gageheight', 'waterheight')):
            return original
    raise ValueError('Cannot identify IEM stage column; CSV columns: ' + ', '.join(columns))


def parse_iem(payload, *, require_reported_units=False):
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
    if require_reported_units and stage_field != 'Water Height (MHHW)[ft]':
        raise ValueError('Unverified Williams Point units/datum: ' + stage_field)
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
            direction = direction if direction is not None and 0 <= direction <= 360 else None
            gust = gust if gust is not None and 0 <= gust <= 100 else None
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


def nws_interval(value):
    """Decode NWS ISO-8601 validTime without changing accumulation periods."""
    start, duration = value.split('/')
    start = datetime.fromisoformat(start.replace('Z', '+00:00'))
    if start.tzinfo is None:
        raise ValueError('NWS validTime lacks a timezone')
    match = re.fullmatch(r'P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?', duration)
    if not match:
        raise ValueError('Unsupported NWS interval: ' + duration)
    days, hours, minutes, seconds = (float(v or 0) for v in match.groups())
    delta = timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
    if not timedelta(0) < delta <= timedelta(days=14):
        raise ValueError('Invalid NWS interval length')
    return start.astimezone(UTC), (start + delta).astimezone(UTC)


def parse_nws_grid(payload, now):
    body = json.loads(payload)
    properties = body.get('properties') if isinstance(body, dict) else None
    if not isinstance(properties, dict) or not isinstance(properties.get('updateTime'), str):
        raise ValueError('NWS grid lacks properties/updateTime')
    updated = datetime.fromisoformat(properties['updateTime'].replace('Z', '+00:00'))
    if updated.tzinfo is None:
        raise ValueError('NWS updateTime lacks a timezone')
    result = {'updated_utc': updated.astimezone(UTC).isoformat(), 'warnings': []}
    fields = {
        'windSpeed': ('wind', 'wmoUnit:km_h-1', 1 / 3.6, 0, 360),
        'windGust': ('gust', 'wmoUnit:km_h-1', 1 / 3.6, 0, 360),
        'windDirection': ('direction', 'wmoUnit:degree_(angle)', 1, 0, 360),
        'quantitativePrecipitation': ('rain', 'wmoUnit:mm', 1, 0, math.inf),
        'probabilityOfPrecipitation': ('probability', 'wmoUnit:percent', 1, 0, 100),
    }
    for field, (name, unit, factor, lower, upper) in fields.items():
        source = properties.get(field, {})
        if not isinstance(source, dict) or source.get('uom') != unit or not isinstance(source.get('values'), list):
            raise ValueError('Missing or unverified NWS units/schema: ' + field)
        rows, invalid = [], 0
        for item in source['values']:
            if not isinstance(item, dict):
                invalid += 1
                continue
            try:
                start, end = nws_interval(item['validTime'])
            except (KeyError, ValueError, TypeError, AttributeError):
                invalid += 1
                continue
            if end <= now:
                continue
            value = safe_float(item.get('value'))
            if value is None or not lower <= value <= upper:
                value = None
                invalid += 1
            rows.append({'t': start.isoformat(), 'end': end.isoformat(),
                         'v': value * factor if value is not None else None})
        result[name] = sorted(rows, key=lambda row: row['t'])
        if invalid:
            result['warnings'].append(f'NWS {name}: {invalid} missing/invalid forecast periods; not filled.')
        if not any(row['v'] is not None for row in rows):
            result['warnings'].append(f'NWS {name}: no future forecast values available.')
    if not any(row['v'] is not None for name, *_ in fields.values() for row in result[name]):
        raise ValueError('NWS grid has no future forecast values')
    return result


def nws_forecast(now):
    point = json.loads(get_bytes(NWS_POINT, {}))['properties']
    grid_url = point['forecastGridData']
    if not re.fullmatch(r'https://api\.weather\.gov/gridpoints/[A-Z]{3}/\d+,\d+', grid_url):
        raise ValueError('Unexpected NWS grid URL')
    forecast = parse_nws_grid(get_bytes(grid_url, {}), now)
    forecast.update({'provider': 'NOAA / National Weather Service',
                     'location': 'Cocoa area (32926); 28.3903, -80.8026',
                     'point_url': NWS_POINT, 'grid_url': grid_url,
                     'units': {'wind': 'm/s', 'gust': 'm/s', 'direction': 'degrees from true north',
                               'rain': 'mm per source interval', 'probability': '%'}})
    return forecast


MANUAL_LOCATIONS = {
    'briarwood_entrance': 'Briarwood Lane entrance / storm drain',
    'indian_river_north': 'Indian River Drive / north culvert',
}


def parse_manual_depths(payload):
    """Validate curated spot depths; reject bad rows instead of dropping measurements."""
    reader = csv.DictReader(io.StringIO(payload.decode('utf-8-sig')))
    required = {'observed_at', 'location_id', 'water_depth_inches', 'standard_position', 'notes'}
    if not required.issubset(reader.fieldnames or []):
        raise ValueError('Manual depth CSV missing required columns')
    readings, seen = [], set()
    for row in reader:
        try:
            original = row['observed_at']
            stamp = datetime.fromisoformat(original.replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                raise ValueError('Manual measurement needs an explicit timezone')
            timestamp = stamp.astimezone(UTC).isoformat(timespec='minutes')
            location = row['location_id']
            if location not in MANUAL_LOCATIONS:
                raise ValueError('Unknown manual measurement location')
            depth = safe_float(row['water_depth_inches'])
            if depth is None or depth < 0:
                raise ValueError('Invalid manual water depth')
            if row['standard_position'] not in ('true', 'false'):
                raise ValueError('Invalid manual position flag')
            if not isinstance(row['notes'], str) or not row['notes'].strip():
                raise ValueError('Manual measurement needs a method note')
            key = timestamp, location
            if key in seen:
                raise ValueError('Duplicate manual measurement time/location')
            seen.add(key)
            readings.append({'t': timestamp, 'original_time': original, 'location_id': location,
                             'location': MANUAL_LOCATIONS[location], 'depth_inches': depth,
                             'standard_position': row['standard_position'] == 'true',
                             'notes': row['notes'].strip(),
                             'original_notes': row.get('original_notes', row['notes']).strip()})
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError(f'Manual depth CSV row {reader.line_num}: {exc}') from exc
    if not readings:
        raise ValueError('Manual depth CSV has no measurements')
    return sorted(readings, key=lambda row: (row['t'], row['location_id']))


def metrics(series):
    if not series:
        return {'count': 0, 'last': None, 'latest': None}
    return {'count': len(series), 'last': series[-1]['t'], 'latest': series[-1]}


def render(payload):
    SITE.mkdir(parents=True, exist_ok=True)
    template = (ROOT / 'templates' / 'index.html').read_text(encoding='utf-8')
    content = json.dumps(payload, separators=(',', ':'), ensure_ascii=False).replace('</', '<\\/')
    (SITE / 'index.html').write_text(template.replace('/*__PAYLOAD__*/', content), encoding='utf-8')
    shutil.copytree(ROOT / 'assets', SITE / 'assets', dirs_exist_ok=True)
    (SITE / '.nojekyll').touch()
    (SITE / 'data.json').write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')


def run():
    now = datetime.now(UTC)
    manual_depths = parse_manual_depths((ROOT / 'data' / 'manual_depths.csv').read_bytes())
    stage_start = now - timedelta(days=14)
    tide_start = now - timedelta(days=7)
    future = now + timedelta(days=3)
    # Williams Point is mandatory; don't replace the previously published site with an empty chart.
    stage_params = {'station':'WIPF1','sts': stage_start.strftime('%Y-%m-%dT%H:%MZ'),
                    'ets': now.strftime('%Y-%m-%dT%H:%MZ'), 'fmt':'csv','kind':'obs','tz':'UTC'}
    stage = parse_iem(get_bytes(IEM, stage_params), require_reported_units=True)
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
    forecast = {}
    try:
        forecast = nws_forecast(now)
        warnings.extend(forecast['warnings'])
    except (HTTPError, URLError, ValueError, TimeoutError, KeyError, TypeError) as exc:
        warnings.append(f'NOAA weather forecast unavailable: {type(exc).__name__}: {exc}')
    document = {
        'built_utc': now.isoformat(timespec='seconds'),
        'williams_point': stage,
        'manual_depths': manual_depths,
        'trident': sources,
        'weather_forecast': forecast,
        'status': {'williams_point': metrics(stage), **{k: metrics(v) for k,v in sources.items()}},
        'warnings': warnings,
        'source_notes': {'manual_depths': 'User-reported road-center spot depths, inches over local road surface; transcribed from supplied screenshot; original times explicitly EST (UTC-05:00). Positions and method notes retained; not datum-referenced gauge heights.',
                         'stage': 'Iowa Environmental Mesonet HML observation archive; WIPF1; Water Height (MHHW)[ft]',
                         'iem_request': stage_params,
                         'noaa_request': {'station': '8721604', 'units': 'metric', 'time_zone': 'gmt', 'datum': 'MLLW (water levels and astronomical tides only)'},
                         'trident': 'NOAA CO-OPS station 8721604; metric units; ocean levels in MLLW'},
    }
    render(document)
    print(f'WIPF1 observations: {len(stage)} | latest {stage[-1]["t"]}')
    for label, series in sources.items():
        print(f'{label}: {len(series)} records')
    print(f'NWS forecast updated: {forecast.get("updated_utc", "unavailable")}')
    if warnings:
        print('Source warnings: ' + ' | '.join(warnings), file=sys.stderr)
    print('Built site/index.html')


if __name__ == '__main__':
    run()
