import importlib.util
import tempfile
import json
import csv
import io
from datetime import timedelta
import unittest
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError, URLError
from datetime import datetime, timezone
from pathlib import Path

MOD_PATH = Path(__file__).resolve().parents[1] / 'scripts' / 'build.py'
spec = importlib.util.spec_from_file_location('monitor_build', MOD_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class TestParsing(unittest.TestCase):
    def manual_fixture(self):
        return (MOD_PATH.parents[1] / 'tests/fixtures/manual_depths.csv').read_bytes()

    def test_manual_depths_screenshot_values_and_est_to_utc(self):
        readings = mod.parse_manual_depths((MOD_PATH.parents[1] / 'data/manual_depths.csv').read_bytes())
        expected = {
            ('2026-11-04T21:00+00:00', 'indian_river_north'): 10,
            ('2026-11-04T21:00+00:00', 'briarwood_entrance'): 5,
            ('2026-11-05T14:30+00:00', 'indian_river_north'): 8,
            ('2026-11-05T14:30+00:00', 'briarwood_entrance'): 2.75,
            ('2026-11-05T22:30+00:00', 'indian_river_north'): 6.25,
            ('2026-11-05T22:30+00:00', 'briarwood_entrance'): 1.125,
            ('2026-11-06T13:15+00:00', 'indian_river_north'): 4.25,
            ('2026-11-06T13:15+00:00', 'briarwood_entrance'): 0,
        }
        self.assertEqual({(r['t'],r['location_id']):r['depth_inches'] for r in readings}, expected)
        nonstandard = [r for r in readings if not r['standard_position']]
        self.assertEqual(len(nonstandard), 1)
        self.assertEqual(nonstandard[0]['location_id'], 'indian_river_north')
        self.assertIn('Not a standard location', nonstandard[0]['original_notes'])
        self.assertTrue(all(r['notes']=='depth at road center' for r in readings))
        self.assertTrue(all(r['original_time'].endswith('-05:00') for r in readings))

    def test_manual_measured_edge_and_unmeasured_notes(self):
        payload = (MOD_PATH.parents[1] / 'tests/fixtures/manual_depths_with_edge.csv').read_bytes()
        readings = mod.parse_manual_depths(payload)
        north = next(r for r in readings if r['location_id'] == 'indian_river_north')
        briarwood = next(r for r in readings if r['location_id'] == 'briarwood_entrance')
        self.assertEqual(north['t'], '2026-11-06T13:15+00:00')
        self.assertEqual(north['original_time'], '2026-11-06T08:15:00-05:00')
        self.assertEqual(north['depth_inches'], 4.25)
        self.assertEqual(north['deep_edge_depth_inches'], 9.5)
        self.assertEqual(briarwood['depth_inches'], 0)
        self.assertIsNone(briarwood['deep_edge_depth_inches'])
        self.assertIn('not measured', briarwood['original_notes'])
        old = mod.parse_manual_depths(self.manual_fixture())
        self.assertTrue(all(r['deep_edge_depth_inches'] is None for r in old))
        reader = csv.DictReader(io.StringIO(payload.decode()))
        row = next(reader)
        for edge in ['NaN', 'inf', '-1', '4', 'unknown']:
            out = io.StringIO()
            writer = csv.DictWriter(out, fieldnames=reader.fieldnames)
            writer.writeheader(); writer.writerow({**row, 'deep_edge_depth_inches': edge})
            with self.subTest(edge=edge), self.assertRaisesRegex(ValueError, 'deep-edge'):
                mod.parse_manual_depths(out.getvalue().encode())
        # A measured zero at both locations is distinct from an unmeasured edge.
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=reader.fieldnames)
        writer.writeheader(); writer.writerow({**row, 'water_depth_inches':'0', 'deep_edge_depth_inches':'0'})
        self.assertEqual(mod.parse_manual_depths(out.getvalue().encode())[0]['deep_edge_depth_inches'], 0)

    def test_manual_fixture_and_rejected_invalid_rows(self):
        payload = self.manual_fixture()
        readings = mod.parse_manual_depths(payload)
        self.assertEqual(len(readings), 2)
        self.assertEqual(readings[0]['t'], '2026-11-04T21:00+00:00')
        reader = csv.DictReader(io.StringIO(payload.decode()))
        rows = list(reader)
        for field, bad in [('observed_at','2026-11-04T16:00:00'),('observed_at','invalid'),
                           ('water_depth_inches',''),('water_depth_inches','NaN'),('water_depth_inches','-1'),
                           ('location_id','unknown'),('standard_position','maybe'),('notes','')]:
            row = {**rows[0],field:bad}
            out = io.StringIO()
            writer = csv.DictWriter(out, fieldnames=reader.fieldnames)
            writer.writeheader()
            writer.writerow(row)
            with self.subTest(field=field,bad=bad), self.assertRaises(ValueError):
                mod.parse_manual_depths(out.getvalue().encode())
        # A valid zero is a measured dry point, distinct from a missing depth.
        row = {**rows[0], 'water_depth_inches':'0'}
        out = io.StringIO(); writer = csv.DictWriter(out, fieldnames=reader.fieldnames)
        writer.writeheader(); writer.writerow(row)
        self.assertEqual(mod.parse_manual_depths(out.getvalue().encode())[0]['depth_inches'], 0)
        for bad in [b'', payload.splitlines()[0]+b'\n', payload+payload.splitlines()[1]+b'\n']:
            with self.assertRaises(ValueError):
                mod.parse_manual_depths(bad)

    def nws_fixture(self):
        return json.loads((MOD_PATH.parents[1] / 'tests/fixtures/nws_grid.json').read_text())

    def test_nws_real_schema_units_and_intervals(self):
        now = datetime(2026,11,5,18,tzinfo=timezone.utc)
        parsed = mod.parse_nws_grid(json.dumps(self.nws_fixture()), now)
        self.assertAlmostEqual(parsed['wind'][0]['v'], 9.26 / 3.6)
        self.assertEqual(parsed['wind'][0]['t'], '2026-11-05T18:00:00+00:00')
        self.assertEqual(parsed['wind'][0]['end'], '2026-11-05T20:00:00+00:00')
        self.assertEqual(parsed['rain'][0]['v'], 0)
        self.assertEqual(parsed['rain'][0]['end'], '2026-11-06T00:00:00+00:00')
        # A multi-hour total stays one value, even when the period overlaps now.
        body = self.nws_fixture()
        body['properties']['quantitativePrecipitation']['values'][1]['value'] = 12.7
        rain = mod.parse_nws_grid(json.dumps(body), now)['rain']
        self.assertEqual(rain[0]['v'], 12.7)
        self.assertEqual(len(rain), 3)
        self.assertEqual(parsed['direction'][0]['v'], 80)
        self.assertTrue(parsed['updated_utc'].endswith('+00:00'))

    def test_overlapping_rain_disables_only_summary(self):
        body = self.nws_fixture()
        rain = body['properties']['quantitativePrecipitation']['values']
        rain.insert(2, dict(rain[1], value=1.524))
        parsed = mod.parse_nws_grid(json.dumps(body), datetime(2026,11,5,18,tzinfo=timezone.utc))
        self.assertIsNone(parsed['rain_events'])
        self.assertTrue(any('Overlapping rain' in warning for warning in parsed['warnings']))
        self.assertTrue(parsed['wind'])
        self.assertTrue(parsed['rain'])

    def test_nws_small_nonzero_rain_totals_preserved(self):
        body = self.nws_fixture()
        source = json.loads((MOD_PATH.parents[1] / 'tests/fixtures/nws_precipitation.json').read_text())
        body['properties']['quantitativePrecipitation'] = source
        parsed = mod.parse_nws_grid(json.dumps(body), datetime(2026,11,6,1,tzinfo=timezone.utc))
        self.assertEqual([r['v'] for r in parsed['rain']], [0, .254, .508])
        for raw, row in zip(source['values'], parsed['rain']):
            start, end = mod.nws_interval(raw['validTime'])
            self.assertEqual(row['t'], start.isoformat())
            self.assertEqual(row['end'], end.isoformat())

    def test_nws_missing_invalid_and_unknown_units(self):
        now = datetime(2026,11,5,17,tzinfo=timezone.utc)
        for value in [None, 'NaN', -1, 101]:
            body = self.nws_fixture()
            body['properties']['probabilityOfPrecipitation']['values'][0]['value'] = value
            parsed = mod.parse_nws_grid(json.dumps(body), now)
            self.assertIsNone(parsed['probability'][0]['v'])
            self.assertTrue(parsed['warnings'])
        for body in [{}, {'properties': None}, {'properties': {'updateTime': None}}]:
            with self.assertRaises(ValueError):
                mod.parse_nws_grid(json.dumps(body), now)
        body = self.nws_fixture()
        body['properties']['windSpeed']['values'][0]['validTime'] = 'invalid'
        self.assertTrue(mod.parse_nws_grid(json.dumps(body), now)['warnings'])
        body['properties']['windSpeed']['uom'] = 'wmoUnit:kn'
        with self.assertRaisesRegex(ValueError, 'units/schema'):
            mod.parse_nws_grid(json.dumps(body), now)
        with self.assertRaisesRegex(ValueError, 'no future'):
            mod.parse_nws_grid(json.dumps(self.nws_fixture()), now + timedelta(days=10))

    def test_nws_intervals_require_timezone_and_positive_duration(self):
        for interval in ['2026-11-05T17:00:00/PT1H', '2026-11-05T17:00:00Z/PT0H',
                         '2026-11-05T17:00:00Z/P1M', 'bad/PT1H']:
            with self.subTest(interval=interval), self.assertRaises(ValueError):
                mod.nws_interval(interval)
        start, end = mod.nws_interval('2026-11-05T12:00:00-05:00/P1DT30M')
        self.assertEqual(start.hour, 17)
        self.assertEqual(end-start, timedelta(days=1,minutes=30))

    def test_forecast_failure_preserves_observation_build(self):
        fixture = (MOD_PATH.parents[1] / 'tests/fixtures/iem_water_height.csv').read_bytes()
        with patch.object(mod, 'get_bytes', return_value=fixture), patch.object(mod, 'coops_recent', return_value=[]), patch.object(mod, 'nws_forecast', side_effect=ValueError('unavailable')), patch.object(mod, 'water_quality_recent', return_value={}), patch.object(mod, 'render') as render:
            mod.run()
            document = render.call_args.args[0]
            self.assertTrue(document['williams_point'])
            self.assertEqual(document['weather_forecast'], {})
            self.assertTrue(any('forecast unavailable' in w for w in document['warnings']))

    def test_all_observation_requests_include_fourteen_days(self):
        now = datetime(2026, 11, 6, 12, tzinfo=timezone.utc)
        fixture = (MOD_PATH.parents[1] / 'tests/fixtures/iem_water_height.csv').read_bytes()
        with patch.object(mod, 'datetime', wraps=datetime) as clock, patch.object(mod, 'get_bytes', return_value=fixture) as fetch, patch.object(mod, 'coops_recent', return_value=[]) as coops, patch.object(mod, 'nws_forecast', return_value={'warnings': []}), patch.object(mod, 'water_quality_recent', return_value={}), patch.object(mod, 'render'):
            clock.now.return_value = now
            mod.run()
        self.assertEqual(fetch.call_args.args[1]['sts'], '2026-10-23T12:00Z')
        self.assertEqual(len(coops.call_args_list), 4)
        for call in coops.call_args_list:
            self.assertEqual(call.args[1], now - timedelta(days=14))
            self.assertEqual(call.args[2], now + timedelta(days=3) if call.args[0] == 'predictions' else now)

    def test_one_optional_fetch_failure_preserves_other_feeds(self):
        fixture = (MOD_PATH.parents[1] / 'tests/fixtures/iem_water_height.csv').read_bytes()
        good = [{'t': '2026-11-06T12:00+00:00', 'v': 1}]
        for failed in ('wind', 'air_pressure', 'water_level', 'predictions'):
            def fetch(product, *args, **kwargs):
                if product == failed:
                    raise URLError('simulated feed outage')
                return good
            with self.subTest(failed=failed), patch.object(mod, 'get_bytes', return_value=fixture), \
                    patch.object(mod, 'coops_recent', side_effect=fetch), \
                    patch.object(mod, 'nws_forecast', return_value={'warnings': []}), \
                    patch.object(mod, 'water_quality_recent', return_value={}), \
                    patch.object(mod, 'render') as render:
                mod.run()
                document = render.call_args.args[0]
                self.assertTrue(document['williams_point'])
                self.assertEqual(len(document['warnings']), 1)
                failed_key = {'air_pressure': 'pressure', 'water_level': 'ocean', 'predictions': 'tide'}.get(failed, failed)
                self.assertTrue(document['warnings'][0].startswith(failed_key + ':'))
                self.assertEqual(document['trident'][failed_key], [])
                for key, rows in document['trident'].items():
                    if key != failed_key:
                        self.assertEqual(rows, good)

    def test_iem_water_height_mhhw(self):
        fixture = (MOD_PATH.parents[1] / 'tests/fixtures/iem_water_height.csv').read_bytes()
        values = mod.parse_iem(fixture, require_reported_units=True)
        self.assertEqual([r['v'] for r in values], [1.5, 1.52, 1.6])
        self.assertEqual(values[-1]['t'], '2026-11-04T15:30+00:00')

    def test_iem_failure_paths(self):
        for payload in [b'', b'station,valid[UTC],Water Height (MHHW)[ft]\nWIPF1,invalid,1\n',
                        b'station,valid[UTC],Water Height (MHHW)[ft]\nWIPF1,2026-11-04,NaN\n',
                        b'station,valid[UTC],Temperature[C]\nWIPF1,2026-11-04,20\n']:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                mod.parse_iem(payload, require_reported_units=True)
        with self.assertRaisesRegex(ValueError, 'Unverified'):
            mod.parse_iem(b'station,valid,Stage\nWIPF1,2026-11-04,1\n', require_reported_units=True)

    def test_coops_missing_invalid_and_error(self):
        payload = b'{"data":[{"t":"bad","s":"3"},{"t":"2026-11-04 15:00","s":"NaN"},{"t":"2026-11-04 15:06","s":"3","d":"999","g":"-1"}]}'
        self.assertEqual(mod.parse_coops(payload, 'wind'), [
            {'t':'2026-11-04T15:06+00:00','speed':3,'direction':None,'gust':None}])
        for payload in [b'{"error":{"message":"No data"}}', b'{}']:
            with self.assertRaises(ValueError):
                mod.parse_coops(payload, 'water_level')

    def test_retry_after_seconds_and_http_date(self):
        for retry, expected in [('10', 10), ('Wed, 04 Nov 2026 15:00:20 GMT', 20)]:
            error = HTTPError('https://example.invalid', 429, 'rate limit', {'Retry-After':retry}, None)
            with patch.object(mod, 'urlopen', side_effect=error) as fetch, patch.object(mod.time, 'sleep') as sleep, patch.object(mod, 'datetime') as clock:
                clock.now.return_value = datetime(2026,11,4,15,0,tzinfo=timezone.utc)
                with self.assertRaises(HTTPError):
                    mod.get_bytes('https://example.invalid', {}, max_attempts=2)
                sleep.assert_called_once_with(expected)
                self.assertEqual(fetch.call_count, 2)

    def test_long_retry_after_does_not_retry_early(self):
        error = HTTPError('https://example.invalid', 503, 'unavailable', {'Retry-After':'120'}, None)
        with patch.object(mod, 'urlopen', side_effect=error) as fetch, patch.object(mod.time, 'sleep') as sleep:
            with self.assertRaises(HTTPError):
                mod.get_bytes('https://example.invalid', {})
            sleep.assert_not_called()
            self.assertEqual(fetch.call_count, 1)

    def test_http_download_size_limit_and_normal_response(self):
        response = MagicMock()
        response.__enter__.return_value = response
        fixture = (MOD_PATH.parents[1] / 'tests/fixtures/iem_water_height.csv').read_bytes()
        response.read.return_value = fixture
        with patch.object(mod, 'urlopen', return_value=response):
            self.assertEqual(mod.get_bytes('https://example.invalid', {}), fixture)
            response.read.assert_called_with(mod.MAX_DOWNLOAD_BYTES + 1)
            response.read.return_value = b'x' * (mod.MAX_DOWNLOAD_BYTES + 1)
            with self.assertRaisesRegex(ValueError, 'download limit'):
                mod.get_bytes('https://example.invalid', {})

    def test_primary_failure_does_not_render(self):
        with patch.object(mod, 'get_bytes', return_value=b''), patch.object(mod, 'render') as render:
            with self.assertRaises(ValueError):
                mod.run()
            render.assert_not_called()

    def test_iem_stage(self):
        csv = b'station,valid(UTC),Stage,Flow\nWIPF1,2026-11-04 15:00,1.50,0\nWIPF1,2026-11-04 15:06,1.52,0\n'
        values = mod.parse_iem(csv)
        self.assertEqual(len(values), 2)
        self.assertEqual(values[0]['v'], 1.5)
        self.assertTrue(values[0]['t'].endswith('+00:00'))

    def test_iem_primary(self):
        csv = b'station,valid,primary_value,secondary_value\nWIPF1,2026-11-04 15:00,2.2,\n'
        self.assertEqual(mod.parse_iem(csv)[0]['v'], 2.2)

    def test_coops(self):
        payload = b'{"data":[{"t":"2026-11-04 15:00","s":"3.2","d":"90","g":"4.0"}]}'
        parsed = mod.parse_coops(payload, 'wind')
        self.assertEqual(parsed[0]['direction'], 90)
        self.assertEqual(parsed[0]['speed'], 3.2)
        self.assertEqual(mod.parse_coops(b'{"predictions":[{"t":"2026-11-04 15:00","v":"0.45"}]}', 'predictions')[0]['v'], .45)

    def test_render_offline(self):
        with tempfile.TemporaryDirectory() as d:
            original_site = mod.SITE
            try:
                mod.SITE = Path(d)
                mod.render({'built_utc':'2026-11-04T15:00:00+00:00','williams_point':[{'t':'2026-11-04T15:00:00+00:00','v':1.5}], 'trident':{},'warnings':[]})
                html = (Path(d) / 'index.html').read_text()
                self.assertIn('Williams Point water level',html)
                self.assertIn('"v":1.5',html)
                self.assertEqual(json.loads((Path(d) / 'update.json').read_text()), {'built_utc':'2026-11-04T15:00:00+00:00'})
                self.assertTrue((Path(d) / '.nojekyll').exists())
                self.assertTrue((Path(d) / 'assets/vendor/matplotlib-barbs.js').is_file())
                self.assertIn('MATPLOTLIB', (Path(d) / 'assets/vendor/matplotlib.LICENSE').read_text())
                self.assertTrue((Path(d) / 'assets/wind-barb-adapter.js').is_file())
            finally:
                mod.SITE = original_site


if __name__ == '__main__':
    unittest.main()
