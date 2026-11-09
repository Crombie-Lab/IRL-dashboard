"""Offline checks of matching, exclusions and independently calculated OLS results."""
import importlib.util
from pathlib import Path
import unittest

import numpy as np
from scipy import stats

spec = importlib.util.spec_from_file_location('road_analysis', Path(__file__).with_name('analyze.py'))
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)


class TestRoadAnalysis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gauge = analysis.build.parse_iem((analysis.HERE / 'inputs/wipf1.csv').read_bytes(), require_reported_units=True)
        cls.manual = analysis.build.parse_manual_depths((analysis.HERE / 'inputs/manual_depths.csv').read_bytes())
        cls.paired = analysis.pair_readings(cls.manual, cls.gauge)

    def test_real_schema_units_and_actual_gauge_matches(self):
        self.assertEqual(len(self.gauge), 930)
        north = [r for r in self.paired if r['location_id'] == 'indian_river_north' and r['primary_included']]
        self.assertEqual([r['gauge_ft'] for r in north], [2.39, 2.27, 2.09, 2.04, 1.89])
        self.assertEqual([r['gauge_offset_min'] for r in north], [0, 0, -3, 0, 0])
        row = next(r for r in north if r['t'] == '2026-11-06T13:15+00:00')
        self.assertEqual(row['gauge_time_utc'], '2026-11-06T13:12+00:00')
        self.assertEqual(row['interpolation_span_min'], 6)
        # Both real bracketing observations report 2.09 ft.
        self.assertAlmostEqual(row['interpolated_gauge_ft'], 2.09)

    def test_censored_times_never_paired_and_nonstandard_position_excluded(self):
        censored = [r for r in self.paired if r['time_excluded']]
        self.assertEqual(len(censored), 2)
        self.assertTrue(all(not r['primary_included'] and r['gauge_ft'] is None
                            and r['interpolated_gauge_ft'] is None for r in censored))
        first_north = next(r for r in self.paired if not r['standard_position'])
        self.assertEqual(first_north['gauge_ft'], 2.61)
        self.assertFalse(first_north['primary_included'])
        self.assertEqual(sum(r['primary_included'] for r in self.paired), 11)
        self.assertTrue(all(r['depth_inches'] == 0 for r in censored))

    def test_nearest_tie_prefers_earlier_actual_point_and_rejects_distant_match(self):
        points = [{'t': '2026-11-06T13:12+00:00', 'v': 2.09},
                  {'t': '2026-11-06T13:18+00:00', 'v': 2.08}]
        point, offset = analysis.nearest(points, analysis.stamp('2026-11-06T08:15:00-05:00'))
        self.assertEqual(point, points[0])
        self.assertEqual(offset, -3)
        self.assertEqual(analysis.nearest(points, analysis.stamp('2026-11-06T13:25:00Z')), (None, None))
        self.assertEqual(analysis.nearest(points, analysis.stamp('2026-11-06T13:24:00Z'))[1], -6)

    def test_interpolation_is_bounded_never_extrapolates_or_bridges_long_gaps(self):
        points = [{'t': '2026-11-06T13:12+00:00', 'v': 2.09},
                  {'t': '2026-11-06T13:18+00:00', 'v': 2.08}]
        # Deliberately varied bracket values test fractional interpolation.
        self.assertAlmostEqual(analysis.interpolate(points, analysis.stamp('2026-11-06T13:15:00Z'))[0], 2.085)
        self.assertEqual(analysis.interpolate(points, analysis.stamp(points[0]['t'])), (2.09, 0))
        self.assertEqual(analysis.interpolate(points, analysis.stamp('2026-11-06T13:19:00Z')), (None, None))
        long_gap = [points[0], {'t': '2026-11-06T13:42+00:00', 'v': 2.08}]
        self.assertEqual(analysis.interpolate(long_gap, analysis.stamp('2026-11-06T13:30:00Z')), (None, 30))
        with self.assertRaises(ValueError):
            analysis.stamp('2026-11-06T13:15:00')

    def test_primary_ols_agrees_with_scipy_and_independent_leave_one_out(self):
        for location in analysis.LOCATIONS:
            rows = [r for r in self.paired if r['location_id'] == location and r['primary_included']]
            x = np.array([r['gauge_ft'] for r in rows])
            y = np.array([r['depth_inches'] for r in rows])
            fit, result = analysis.fit_model(rows)
            reference = stats.linregress(x, y)
            self.assertAlmostEqual(result['coefficients'][0]['estimate'], reference.intercept, places=10)
            self.assertAlmostEqual(result['coefficients'][1]['estimate'], reference.slope, places=10)
            self.assertAlmostEqual(result['coefficients'][1]['standard_error'], reference.stderr, places=10)
            self.assertAlmostEqual(result['coefficients'][1]['nominal_p'], reference.pvalue, places=10)
            self.assertAlmostEqual(result['r_squared'], reference.rvalue ** 2, places=12)
            critical = stats.t.ppf(.975, len(rows) - 2)
            np.testing.assert_allclose(result['coefficients'][1]['ci95'],
                                       [reference.slope - critical * reference.stderr,
                                        reference.slope + critical * reference.stderr])
            errors = []
            for i, point in enumerate(result['diagnostics']):
                keep = np.arange(len(rows)) != i
                leave_out = stats.linregress(x[keep], y[keep])
                errors.append(y[i] - (leave_out.intercept + leave_out.slope * x[i]))
                self.assertAlmostEqual(point['loo_error_inches'], errors[-1], places=10)
            self.assertAlmostEqual(result['loo_rmse_inches'], np.sqrt(np.mean(np.square(errors))), places=10)
            self.assertAlmostEqual(result['anova']['regression_ss'] + result['anova']['residual_ss'],
                                   result['anova']['total_ss'], places=10)
            self.assertEqual(result['residual_df'], len(rows) - 2)


if __name__ == '__main__':
    unittest.main()
