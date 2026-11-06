import csv
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('water_quality_build', ROOT / 'scripts/build.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
UTC = timezone.utc


class TestWaterQuality(unittest.TestCase):
    def fixture(self, key='salinity'):
        return (ROOT / f'tests/fixtures/aquarius_irli13_{key}.csv').read_bytes()

    def parse(self, payload=None, key='salinity'):
        dataset, unit = mod.WATER_QUALITY[key]
        return mod.parse_aquarius_csv(payload if payload is not None else self.fixture(key), dataset=dataset, unit=unit)

    def alter(self, **changes):
        lines = self.fixture().decode().splitlines()
        rows = list(csv.DictReader(lines[1:]))
        out = io.StringIO()
        out.write(lines[0] + '\n')
        writer = csv.DictWriter(out, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerow({**rows[-1], **changes})
        return out.getvalue().encode()

    def test_native_units_utc_and_provisional_values(self):
        for key, unit, value in [('salinity', 'ppt', 18.265299042390062),
                                 ('temperature', '°C', 25.790000915527344),
                                 ('turbidity', 'FNU', 1.440000057220459)]:
            with self.subTest(key=key):
                rows, _ = self.parse(key=key)
                self.assertEqual(rows[-1]['t'], '2026-11-06T15:00:00+00:00')
                self.assertEqual(rows[-1]['v'], value)
                self.assertEqual(rows[-1]['quality'], 'provisional')
                self.assertEqual(rows[-1]['grade'], '0')
                self.assertEqual(rows[-1]['approval'], '800')
        rows, warnings = self.parse()
        unusable = [r for r in rows if r['grade'] == '-2']
        self.assertEqual(len(unusable), 2)
        self.assertTrue(all(r['v'] is None and r['quality'] == 'excluded' for r in unusable))
        self.assertTrue(warnings)

    def test_bad_schema_identity_units_and_timezone_rejected(self):
        source = self.fixture()
        for bad in [b'', source.replace(b'Value (ppt)', b'Value (mg/L)'),
                    source.replace(b'Timestamp (UTC)', b'Timestamp (EST)'),
                    source.replace(b'37375724', b'33844736')]:
            with self.subTest(bad=bad[:70]), self.assertRaises(ValueError):
                self.parse(bad)
        rows, warnings = self.parse(self.alter(**{'Timestamp (UTC)': '2026-11-06T10:00:00-05:00'}))
        self.assertEqual(rows, [])
        self.assertTrue(warnings)

    def test_missing_censored_quality_working_and_duplicates(self):
        for changes in [{'Value (ppt)': 'NaN'}, {'Value (ppt)': ''},
                        {'Value (ppt)': '-9999'}, {'Value (ppt)': '-1'},
                        {'Grade Code': '-2'}, {'Grade Code': '999'},
                        {'Approval Level': '900'}, {'Interpolation Type': '2'}]:
            with self.subTest(changes=changes):
                rows, warnings = self.parse(self.alter(**changes))
                self.assertIsNone(rows[0]['v'])
                self.assertTrue(warnings)
        rows, _ = self.parse(self.alter(**{'Value (ppt)': '0', 'Grade Code': '3', 'Approval Level': '1200'}))
        self.assertEqual(rows[0]['v'], 0)
        self.assertEqual(rows[0]['quality'], 'approved')  # Grade 3 is not QARTOD suspect.
        one = self.alter()
        rows, _ = self.parse(one + one.splitlines()[-1] + b'\n')
        self.assertEqual(len(rows), 1)
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            self.parse(one + self.alter(**{'Value (ppt)': '20'}).splitlines()[-1] + b'\n')

    def test_public_export_utc_window_and_token_not_retained(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as zipped:
            zipped.writestr('observations.csv', self.fixture())
        now = datetime(2026, 11, 6, 16, tzinfo=UTC)
        start = now - timedelta(days=14)
        with patch.object(mod, 'get_bytes', side_effect=[b'{"Token":"ephemeral-test-download"}', archive.getvalue()]) as fetch:
            result = mod.aquarius_recent('salinity', start, now)
        token_request, download = fetch.call_args_list
        self.assertEqual(token_request.kwargs['data'], b'')
        params = token_request.args[1]
        self.assertEqual(params['Timezone'], 0)
        self.assertEqual(params['StartTime'], '2026-10-23 16:00:00')
        self.assertEqual(params['EndTime'], '2026-11-06 16:00:00')
        self.assertNotIn('UnitID', params)  # Native units are verified in the returned CSV.
        self.assertEqual(download.args[1]['Token'], 'ephemeral-test-download')
        self.assertNotIn('ephemeral-test-download', json.dumps(result))
        self.assertEqual(result['unit'], 'ppt')
        self.assertEqual(result['data'][-1]['v'], 18.265299042390062)
        with patch.object(mod, 'get_bytes', side_effect=[b'{}']):
            with self.assertRaisesRegex(ValueError, 'token'):
                mod.aquarius_recent('salinity', start, now)
        with patch.object(mod, 'get_bytes', side_effect=[b'[]']):
            with self.assertRaisesRegex(ValueError, 'token'):
                mod.aquarius_recent('salinity', start, now)
        with patch.object(mod, 'get_bytes', side_effect=[b'{"Token":"test"}', b'not a ZIP']):
            with self.assertRaises(zipfile.BadZipFile):
                mod.aquarius_recent('salinity', start, now)

    def test_partial_outage_and_unavailable_stations_are_explicit(self):
        now = datetime(2026, 11, 6, 16, tzinfo=UTC)
        good = {'unit': 'ppt', 'data': [{'t': now.isoformat(), 'v': 18}], 'warnings': []}
        with patch.object(mod, 'aquarius_recent', side_effect=[good, ValueError('bad schema'), TimeoutError('upstream')]):
            result = mod.water_quality_recent(now - timedelta(days=14), now)
        series = result['stations'][0]['series']
        self.assertTrue(series['salinity']['data'])
        self.assertFalse(series['temperature']['data'])
        self.assertTrue(series['temperature']['warnings'])
        self.assertEqual([s['name'] for s in result['unavailable_stations']], ['IRLI14', 'IRLI15'])

    def test_invalid_dates_and_future_observations_not_published(self):
        for stamp in ['invalid', '2026-11-06', '2026-11-06 25:00:00']:
            rows, warnings = self.parse(self.alter(**{'Timestamp (UTC)': stamp}))
            self.assertEqual(rows, [])
            self.assertTrue(warnings)
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as zipped:
            zipped.writestr('observations.csv', self.fixture())
        now = datetime(2026, 11, 6, 14, tzinfo=UTC)
        with patch.object(mod, 'get_bytes', side_effect=[b'{"Token":"test"}', archive.getvalue()]):
            result = mod.aquarius_recent('salinity', now - timedelta(days=14), now)
        self.assertTrue(all(datetime.fromisoformat(r['t']) <= now for r in result['data']))
        self.assertTrue(any('future-dated' in warning for warning in result['warnings']))

    def test_quality_outage_does_not_block_primary_observations(self):
        stage = [{'t': '2026-11-06T15:54:00+00:00', 'v': 2.12}]
        with patch.object(mod, 'get_bytes', return_value=b''), patch.object(mod, 'parse_iem', return_value=stage), \
                patch.object(mod, 'coops_recent', return_value=[]), \
                patch.object(mod, 'nws_forecast', return_value={'warnings': []}), \
                patch.object(mod, 'aquarius_recent', side_effect=TimeoutError('private-request-token')), \
                patch.object(mod, 'render') as render:
            mod.run()
        document = render.call_args.args[0]
        self.assertEqual(document['williams_point'], stage)
        series = document['water_quality']['stations'][0]['series']
        self.assertTrue(all(s['warnings'] and not s['data'] for s in series.values()))
        self.assertNotIn('private-request-token', json.dumps(document))


if __name__ == '__main__':
    unittest.main()
