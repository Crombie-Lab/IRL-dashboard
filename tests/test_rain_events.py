import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('rain_build', ROOT / 'scripts/build.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class TestRainEvents(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads((ROOT / 'tests/fixtures/nws_rain_periods.json').read_text())

    def test_real_period_amount_and_peak_chance(self):
        events = mod.group_rain_events(self.fixture['rain'], self.fixture['probability'])
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event['t'], '2026-11-07T00:00:00+00:00')
        self.assertEqual(event['end'], '2026-11-07T06:00:00+00:00')
        self.assertAlmostEqual(event['amount_mm'] / 25.4, .06)
        self.assertEqual(event['peak_probability'], 19)
        self.assertTrue(event['probability_complete'])

    def test_adjoining_periods_sum_once_without_probability_weighting(self):
        rain = self.fixture['rain']
        rain[3]['v'] = .254
        events = mod.group_rain_events(rain, self.fixture['probability'])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['periods'], 2)
        self.assertEqual(events[0]['end'], rain[3]['end'])
        self.assertAlmostEqual(events[0]['amount_mm'] / 25.4, .07)
        # The known full accumulation total is retained even when its window has begun.
        self.assertEqual(events[0]['t'], rain[2]['t'])

    def test_dry_missing_or_nonadjoining_periods_break_groups(self):
        for middle in [0, None]:
            rain = [dict(row) for row in self.fixture['rain']]
            rain[0]['v'], rain[1]['v'] = .254, middle
            events = mod.group_rain_events(rain, [])
            self.assertEqual(len(events), 2)
            self.assertAlmostEqual(events[0]['amount_mm'], .254)
            self.assertAlmostEqual(events[1]['amount_mm'], 1.524)
        rain = self.fixture['rain']
        rain[0]['v'] = .254
        events = mod.group_rain_events([rain[0], rain[2]], [])
        self.assertEqual(len(events), 2)

    def test_zero_amount_is_distinct_from_missing_and_probability_zero_is_valid(self):
        self.assertEqual(mod.group_rain_events([], []), [])
        rain = [dict(row, v=0) for row in self.fixture['rain']]
        self.assertEqual(mod.group_rain_events(rain, self.fixture['probability']), [])
        event = mod.group_rain_events(self.fixture['rain'], [
            {'t':'2026-11-07T00:00:00+00:00','end':'2026-11-07T06:00:00+00:00','v':0}])[0]
        self.assertEqual(event['peak_probability'], 0)
        self.assertTrue(event['probability_complete'])

    def test_probability_missing_coverage_and_exclusive_end_boundary(self):
        rain = self.fixture['rain']
        for probability in [[], [dict(row, v=None) for row in self.fixture['probability']]]:
            event = mod.group_rain_events(rain, probability)[0]
            self.assertIsNone(event['peak_probability'])
            self.assertFalse(event['probability_complete'])
        probability = [{'t':'2026-11-07T00:00:00+00:00','end':'2026-11-07T01:00:00+00:00','v':20},
                       {'t':'2026-11-07T06:00:00+00:00','end':'2026-11-07T12:00:00+00:00','v':90}]
        event = mod.group_rain_events(rain, probability)[0]
        self.assertEqual(event['peak_probability'], 20)
        self.assertFalse(event['probability_complete'])

    def test_overlapping_amounts_are_rejected_not_double_counted(self):
        rain = self.fixture['rain']
        rain.insert(3, dict(rain[2]))
        with self.assertRaisesRegex(ValueError, 'Overlapping'):
            mod.group_rain_events(rain, self.fixture['probability'])


if __name__ == '__main__':
    unittest.main()
