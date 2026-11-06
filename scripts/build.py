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
import zipfile
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
AQUARIUS = 'https://secure.sjrwmd.com/aqportal'
WATER_QUALITY = {
    'salinity': ('Salinity.YSI_Calc@37375724', 'ppt'),
    'temperature': ('Water Temp.YSI@37375724', '°C'),
    'turbidity': ('Turbidity Form Neph.YSI@37375724', 'FNU'),
}
HEADERS = {'User-Agent': 'IRL-dashboard/0.2 (https://github.com/Crombie-Lab/IRL-dashboard)'}
MAX_DOWNLOAD_BYTES = 16 * 1024 * 1024


def get_bytes(base, params, max_attempts=4, *, data=None):
    url = base + ('?' + urlencode(params) if params else '')
    for attempt in range(max_attempts):
        try:
            with urlopen(Request(url, headers=HEADERS, data=data), timeout=45) as response:
                payload = response.read(MAX_DOWNLOAD_BYTES + 1)
            if len(payload) > MAX_DOWNLOAD_BYTES:
                raise ValueError('HTTP response exceeds the 16 MiB download limit')
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


def parse_aquarius_csv(payload, *, dataset, unit):
    """Read native instantaneous values; the validated CSV header establishes UTC.

    Grade 0 / approval 800 are explicitly provisional. Keep unusable or invalid
    values as null rows so charts cannot connect across their timestamps.
    AQUARIUS grade codes are not QARTOD flags.
    """
    lines = payload.decode('utf-8-sig').splitlines()
    reader = csv.reader(lines)
    identity = next(reader, [])
    if not identity or identity[0] != '#Data Set Export - ' + dataset:
        raise ValueError('Unexpected SJRWMD dataset identity')
    fields = next(reader, [])
    expected = ['Timestamp (UTC)', f'Value ({unit})', 'Grade Code',
                'Approval Level', 'Interpolation Type']
    if fields != expected:
        raise ValueError('Unverified SJRWMD units/timezone/schema: ' + ', '.join(fields))
    rows = {}
    invalid_dates = 0
    for values in reader:
        if not values or not any(values):
            continue
        if len(values) != len(expected):
            raise ValueError('Malformed SJRWMD observation row')
        stamp, raw, grade, approval, interpolation = values
        try:
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)?', stamp):
                raise ValueError('Invalid UTC timestamp')
            stamp = datetime.fromisoformat(stamp)
            if stamp.tzinfo is not None and stamp.utcoffset() != timedelta(0):
                raise ValueError('Non-UTC value in UTC column')
            stamp = stamp.replace(tzinfo=UTC).isoformat(timespec='seconds')
        except ValueError:
            invalid_dates += 1
            continue
        value = safe_float(raw)
        # Native sentinel and missing values must not become measurements.
        if value == -9999 or (value is not None and unit in ('ppt', 'FNU') and value < 0):
            value = None
        accepted = grade in ('0', '1', '2', '3', '11', '12', '13') and approval in ('800', '1200') and interpolation == '1'
        row = {'t': stamp, 'v': value if accepted else None,
               'reported_value': value, 'grade': grade, 'approval': approval,
               'interpolation': interpolation,
               'quality': 'provisional' if grade == '0' or approval == '800' else 'approved' if accepted else 'excluded'}
        if not accepted:
            row['quality'] = 'excluded'
        if stamp in rows and rows[stamp] != row:
            raise ValueError('Conflicting SJRWMD observations at the same time')
        rows[stamp] = row
    warnings = []
    if invalid_dates:
        warnings.append(f'{invalid_dates} invalid observation timestamps omitted')
    excluded = sum(r['v'] is None for r in rows.values())
    if excluded:
        warnings.append(f'{excluded} missing or quality-excluded readings')
    return [rows[t] for t in sorted(rows)], warnings


def aquarius_recent(key, start, now):
    dataset, unit = WATER_QUALITY[key]
    params = {
        'DataSet': dataset, 'Calendar': 'CALENDARYEAR', 'DateRange': 'Custom',
        'StartTime': start.strftime('%Y-%m-%d %H:%M:%S'),
        'EndTime': now.strftime('%Y-%m-%d %H:%M:%S'),
        'Conversion': 'Instantaneous', 'IntervalPoints': 'PointsAsRecorded',
        'ApprovalLevels': 'True', 'Step': 1, 'ExportFormat': 'csv',
        'Compressed': 'true', 'RoundData': 'False', 'GradeCodes': 'True',
        'InterpolationTypes': 'True', 'Timezone': 0,
    }
    # Public export token, not an account credential. Never retain it in output.
    receipt = json.loads(get_bytes(AQUARIUS + '/Export/DataSetToken', params, data=b''))
    token = receipt.get('Token') if isinstance(receipt, dict) else None
    if not isinstance(token, str) or not token or len(token) > 8192:
        raise ValueError('SJRWMD export did not provide a download token')
    archive = get_bytes(AQUARIUS + '/Export/DataSet', dict(params, Token=token))
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        files = zipped.infolist()
        if len(files) != 1 or not files[0].filename.endswith('.csv') or files[0].file_size > 2 * 1024 * 1024:
            raise ValueError('Unexpected SJRWMD export archive')
        rows, warnings = parse_aquarius_csv(zipped.read(files[0]), dataset=dataset, unit=unit)
    future_rows = sum(datetime.fromisoformat(r['t']) > now for r in rows)
    if future_rows:
        warnings.append(f'{future_rows} future-dated observations omitted')
    rows = [r for r in rows if start <= datetime.fromisoformat(r['t']) <= now]
    if not any(r['v'] is not None for r in rows):
        warnings.append('No valid observations in the last 14 days')
    return {'unit': unit, 'dataset': dataset, 'data': rows, 'warnings': warnings,
            'retrieved_utc': now.isoformat(timespec='seconds'), 'request': params,
            'source_url': AQUARIUS + '/Data/DataSet/Chart/Location/37375724/DataSet/' +
                          {'salinity': 'Salinity/YSI_Calc', 'temperature': 'Water%20Temp/YSI',
                           'turbidity': 'Turbidity%20Form%20Neph/YSI'}[key] + '/Interval/Latest'}


def water_quality_recent(start, now):
    station = {'name': 'IRLI13', 'provider': 'SJRWMD', 'location_identifier': '37375724',
               'latitude': 28.393066001, 'longitude': -80.735861, 'coordinate_datum': 'NAD83',
               'series': {}}
    for key, (dataset, unit) in WATER_QUALITY.items():
        try:
            station['series'][key] = aquarius_recent(key, start, now)
        except (HTTPError, URLError, ValueError, TimeoutError, KeyError, TypeError, csv.Error,
                zipfile.BadZipFile, RuntimeError, EOFError) as exc:
            # Do not include request URLs or ephemeral export tokens in errors.
            station['series'][key] = {'unit': unit, 'dataset': dataset, 'data': [],
                                      'warnings': [f'SJRWMD {key} unavailable ({type(exc).__name__})']}
    return {'stations': [station], 'source_url': AQUARIUS,
            'unavailable_stations': [
                {'name': 'IRLI14', 'reason': 'No public continuous feed found'},
                {'name': 'IRLI15', 'reason': 'No public continuous feed found'},
            ]}


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


def group_rain_events(rain, probability):
    """Sum adjoining positive source totals; never bridge dry/missing periods.

    Peak PoP is a maximum of overlapping period probabilities, not a combined
    event probability. Preserve full accumulation windows, including active ones.
    """
    events, active, previous_end = [], None, None
    for row in rain:
        if previous_end is not None and row['t'] < previous_end:
            raise ValueError('Overlapping rain periods cannot be totaled safely')
        previous_end = row['end']
        if row['v'] is None or row['v'] <= 0:
            active = None
            continue
        if active is None or row['t'] != active['end']:
            active = {'t': row['t'], 'end': row['end'], 'amount_mm': 0, 'periods': 0}
            events.append(active)
        active['end'] = row['end']
        active['amount_mm'] += row['v']
        active['periods'] += 1
    for event in events:
        overlapping = [p for p in probability if p['t'] < event['end'] and p['end'] > event['t']]
        values = [p['v'] for p in overlapping if p['v'] is not None]
        event['peak_probability'] = max(values, default=None)
        covered = event['t']
        for row in overlapping:
            if row['v'] is None:
                continue
            if row['t'] > covered:
                break
            covered = max(covered, row['end'])
        event['probability_complete'] = covered >= event['end']
    return events


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
    try:
        result['rain_events'] = group_rain_events(result['rain'], result['probability'])
    except ValueError as exc:
        result['rain_events'] = None
        result['warnings'].append('Rain summary unavailable: ' + str(exc))
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
            edge_raw = row.get('deep_edge_depth_inches', '')
            edge = None
            if edge_raw and edge_raw.strip():
                edge = safe_float(edge_raw)
                if edge is None or edge < depth:
                    raise ValueError('Invalid measured deep-edge depth')
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
                             'deep_edge_depth_inches': edge,
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
    (SITE / 'update.json').write_text(json.dumps({'built_utc': payload['built_utc']}), encoding='utf-8')


def run():
    now = datetime.now(UTC)
    manual_depths = parse_manual_depths((ROOT / 'data' / 'manual_depths.csv').read_bytes())
    stage_start = now - timedelta(days=14)
    tide_start = stage_start
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
    water_quality = water_quality_recent(stage_start, now)
    document = {
        'built_utc': now.isoformat(timespec='seconds'),
        'williams_point': stage,
        'manual_depths': manual_depths,
        'trident': sources,
        'weather_forecast': forecast,
        'water_quality': water_quality,
        'status': {'williams_point': metrics(stage), **{k: metrics(v) for k,v in sources.items()}},
        'warnings': warnings,
        'source_notes': {'manual_depths': 'User-reported road-center spot depths with separately recorded measured deep-edge depths when supplied, inches over local road surface; transcribed from supplied screenshot; original times explicitly EST (UTC-05:00). Positions and method notes retained; not datum-referenced gauge heights.',
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
