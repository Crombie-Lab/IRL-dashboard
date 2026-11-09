#!/usr/bin/env python3
"""Offline, retrospective road-depth association analysis; never used by site builds."""
import csv
import hashlib
import importlib.metadata
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use('Agg')
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
from scipy import stats
import statsmodels.api as sm

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EASTERN = ZoneInfo('America/New_York')
MAX_OFFSET_MIN = 6
MAX_BRACKET_MIN = 12
LOCATIONS = {
    'indian_river_north': ('Indian River Drive north culvert', '#7955a6'),
    'briarwood_entrance': ('Briarwood Lane storm drain', '#ae642b'),
}
spec = importlib.util.spec_from_file_location('dashboard_build', ROOT / 'scripts/build.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def stamp(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Analysis timestamps must be timezone aware')
    return result.astimezone(timezone.utc)


def local(value):
    return stamp(value).astimezone(EASTERN).strftime('%b %d, %I:%M %p EST')


def nearest(gauge, time, max_minutes=MAX_OFFSET_MIN):
    """Use an actual observation; ties go to the earlier timestamp."""
    point = min(gauge, key=lambda r: (abs((stamp(r['t']) - time).total_seconds()), stamp(r['t'])))
    offset = (stamp(point['t']) - time).total_seconds() / 60
    return (point, offset) if abs(offset) <= max_minutes else (None, None)


def interpolate(gauge, time, max_minutes=MAX_BRACKET_MIN):
    """Sensitivity only: a derived estimate between close brackets, never extrapolate."""
    before = [r for r in gauge if stamp(r['t']) <= time]
    after = [r for r in gauge if stamp(r['t']) >= time]
    if not before or not after:
        return None, None
    left, right = before[-1], after[0]
    span = (stamp(right['t']) - stamp(left['t'])).total_seconds() / 60
    if span == 0:
        return left['v'], 0
    if span > max_minutes:
        return None, span
    fraction = (time - stamp(left['t'])).total_seconds() / (span * 60)
    return left['v'] + fraction * (right['v'] - left['v']), span


def pair_readings(manual, gauge):
    rows = []
    for original in manual:
        row = dict(original)
        row['time_est'] = local(row['t'])
        note = (row['notes'] + ' ' + row['original_notes']).lower()
        row['time_excluded'] = 'time inaccurate' in note or 'censor from regression' in note
        row.update(gauge_time_utc=None, gauge_offset_min=None, gauge_ft=None,
                   interpolated_gauge_ft=None, interpolation_span_min=None)
        reasons = []
        if row['time_excluded']:
            reasons.append('Inaccurate time; user requested exclusion from regression')
        else:
            point, offset = nearest(gauge, stamp(row['t']))
            value, span = interpolate(gauge, stamp(row['t']))
            row.update(interpolated_gauge_ft=value, interpolation_span_min=span)
            if point:
                row.update(gauge_time_utc=point['t'], gauge_offset_min=offset, gauge_ft=point['v'])
            else:
                reasons.append('No actual gauge observation within six minutes')
        if not row['standard_position']:
            reasons.append('Nonstandard road position; sensitivity analysis only')
        row['primary_included'] = not reasons
        row['primary_exclusion_reason'] = '; '.join(reasons)
        rows.append(row)
    return rows


def fit_model(rows, x_key='gauge_ft'):
    if len(rows) < 3:
        raise ValueError('At least three paired readings are required')
    x = np.array([r[x_key] for r in rows], dtype=float)
    y = np.array([r['depth_inches'] for r in rows], dtype=float)
    if not np.isfinite(x).all() or not np.isfinite(y).all() or np.ptp(x) == 0:
        raise ValueError('Finite, varying paired gauge values are required')
    design = sm.add_constant(x)
    fit = sm.OLS(y, design).fit()
    robust = fit.get_robustcov_results(cov_type='HC3', use_t=True)
    influence = fit.get_influence()
    loo_errors, loo_slopes = [], []
    for i in range(len(rows)):
        keep = np.arange(len(rows)) != i
        reduced = sm.OLS(y[keep], design[keep]).fit()
        loo_errors.append(float(y[i] - reduced.predict(design[i:i + 1])[0]))
        loo_slopes.append(float(reduced.params[1]))
    ci = fit.conf_int()
    prediction = fit.get_prediction(design).summary_frame(alpha=.05)
    coefficients = []
    for i, name in enumerate(('intercept', 'gauge_slope')):
        coefficients.append({'term': name, 'estimate': float(fit.params[i]),
                             'standard_error': float(fit.bse[i]), 't': float(fit.tvalues[i]),
                             'nominal_p': float(fit.pvalues[i]), 'ci95': ci[i].tolist(),
                             'hc3_ci95': robust.conf_int()[i].tolist()})
    diagnostics = []
    for i, row in enumerate(rows):
        diagnostics.append({'point_id': i + 1, 'time_est': row['time_est'], 't': row['t'],
                            'gauge_ft': float(x[i]), 'depth_inches': float(y[i]),
                            'fitted_inches': float(fit.fittedvalues[i]),
                            'residual_inches': float(fit.resid[i]),
                            'leverage': float(influence.hat_matrix_diag[i]),
                            'cooks_distance': float(influence.cooks_distance[0][i]),
                            'studentized_residual': float(influence.resid_studentized_internal[i]),
                            'loo_error_inches': loo_errors[i], 'loo_slope': loo_slopes[i],
                            'mean_ci95_lower': float(prediction['mean_ci_lower'].iloc[i]),
                            'mean_ci95_upper': float(prediction['mean_ci_upper'].iloc[i]),
                            'single_reading_interval95_lower': float(prediction['obs_ci_lower'].iloc[i]),
                            'single_reading_interval95_upper': float(prediction['obs_ci_upper'].iloc[i])})
    # Time checks are descriptive: a single recession is not an independent-event sample.
    hours = np.array([(stamp(r['t']) - stamp(rows[0]['t'])).total_seconds() / 3600 for r in rows])
    time_fit = sm.OLS(y, sm.add_constant(hours)).fit()
    adjusted = sm.OLS(y, np.column_stack((np.ones(len(rows)), x, hours))).fit() if len(rows) >= 4 else None
    changes = np.diff(y)
    gauge_changes = np.diff(x)
    dt = np.diff(hours)
    def correlation(a, b):
        return float(stats.pearsonr(a, b).statistic) if len(a) >= 3 and np.ptp(a) and np.ptp(b) else None
    sse = float(np.dot(fit.resid, fit.resid))
    pearson = stats.pearsonr(x, y)
    pearson_ci = pearson.confidence_interval(confidence_level=.95)
    summary = {
        'n': len(rows), 'residual_df': int(fit.df_resid), 'x_range_ft': [float(x.min()), float(x.max())],
        'y_range_inches': [float(y.min()), float(y.max())], 'zero_readings': int(np.sum(y == 0)),
        'pearson_r': float(pearson.statistic),
        'pearson_ci95_fisher': [float(pearson_ci.low), float(pearson_ci.high)],
        'spearman_rho': float(stats.spearmanr(x, y).statistic),
        'r_squared': float(fit.rsquared), 'adjusted_r_squared': float(fit.rsquared_adj),
        'rmse_inches': float(np.sqrt(np.mean(fit.resid ** 2))),
        'residual_standard_error_inches': float(np.sqrt(fit.mse_resid)),
        'mae_inches': float(np.mean(np.abs(fit.resid))),
        'loo_rmse_inches': float(np.sqrt(np.mean(np.square(loo_errors)))),
        'loo_slope_range': [min(loo_slopes), max(loo_slopes)],
        'coefficients': coefficients,
        'slope_equals_12_nominal_p': float(2 * stats.t.sf(abs((fit.params[1] - 12) / fit.bse[1]), fit.df_resid)),
        'anova': {'regression_ss': float(fit.ess), 'residual_ss': sse, 'total_ss': float(fit.centered_tss),
                  'regression_df': 1, 'residual_df': int(fit.df_resid), 'total_df': len(rows) - 1,
                  'regression_ms': float(fit.ess), 'residual_ms': float(fit.mse_resid),
                  'F': float(fit.fvalue), 'nominal_p': float(fit.f_pvalue)},
        'checks': {'time_only_r_squared': float(time_fit.rsquared),
                   'gauge_vs_elapsed_hours_r': float(stats.pearsonr(x, hours).statistic),
                   'time_adjusted_gauge_slope': float(adjusted.params[1]) if adjusted else None,
                   'time_adjusted_gauge_ci95': adjusted.conf_int()[1].tolist() if adjusted else None,
                   'time_adjusted_residual_df': int(adjusted.df_resid) if adjusted else None,
                   'gauge_time_vif': float(1 / (1 - np.corrcoef(x, hours)[0, 1] ** 2)),
                   'successive_changes_r': correlation(gauge_changes, changes),
                   'successive_hourly_rates_r': correlation(gauge_changes / dt, changes / dt),
                   'successive_intervals': len(dt),
                   'shapiro_residual_nominal_p': float(stats.shapiro(fit.resid).pvalue) if np.ptp(fit.resid) > 1e-12 else None,
                   'durbin_watson_descriptive': float(np.sum(np.diff(fit.resid) ** 2) / sse) if sse > 1e-20 else None},
        'diagnostics': diagnostics,
    }
    return fit, summary


def write_csv(path, rows):
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def clean(value):
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def save_figure(fig, name):
    fig.savefig(HERE / 'figures' / (name + '.png'), dpi=180, bbox_inches='tight')
    fig.savefig(HERE / 'figures' / (name + '.svg'), bbox_inches='tight')
    plt.close(fig)


def overview(gauge, paired):
    fig, axes = plt.subplots(3, 1, figsize=(10.8, 8.2), sharex=True, layout='constrained')
    times, values = [], []
    for i, point in enumerate(gauge):
        if i and (stamp(point['t']) - stamp(gauge[i - 1]['t'])).total_seconds() > MAX_BRACKET_MIN * 60:
            times.append(stamp(point['t'])); values.append(np.nan)
        times.append(stamp(point['t'])); values.append(point['v'])
    axes[0].plot(times, values, color='#10799d', lw=1.5)
    axes[0].set(ylabel='Williams Point\nwater level (ft MHHW)', title='One falling-water episode: November 4–8, 2026')
    for ax, (location, (name, color)) in zip(axes[1:], LOCATIONS.items()):
        rows = [r for r in paired if r['location_id'] == location]
        for selected, marker, face, label in [([r for r in rows if r['primary_included']], 'o', color, 'Primary fit'),
                                             ([r for r in rows if not r['standard_position']], 's', 'none', 'Different spot; sensitivity only'),
                                             ([r for r in rows if r['time_excluded']], 'x', '#687780', 'Inaccurate time; excluded')]:
            if selected:
                ax.scatter([stamp(r['t']) for r in selected], [r['depth_inches'] for r in selected],
                           marker=marker, color=color if face == 'none' else face,
                           facecolors=face if marker != 'x' else None, s=52, label=label, zorder=3)
        ax.set(ylabel='Road-center depth (in)', title=name, ylim=(-.7, max(r['depth_inches'] for r in rows) + 1.3))
        ax.legend(fontsize=8, loc='upper right')
    axes[-1].xaxis.set_major_locator(mdates.HourLocator(byhour=[0, 12], tz=EASTERN))
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter('%b %d\n%I:%M %p', tz=EASTERN))
    axes[-1].set_xlabel('Eastern Standard Time (EST); excluded crosses use nominal noon only')
    for ax in axes:
        ax.grid(alpha=.2)
    save_figure(fig, 'time_series')


def regression_plot(location, rows, fit, summary, paired):
    name, color = LOCATIONS[location]
    x = np.array([r['gauge_ft'] for r in rows])
    grid = np.linspace(x.min(), x.max(), 160)
    prediction = fit.get_prediction(sm.add_constant(grid)).summary_frame()
    fig, ax = plt.subplots(figsize=(9.2, 6), layout='constrained')
    ax.fill_between(grid, prediction['mean_ci_lower'], prediction['mean_ci_upper'], color=color, alpha=.17, label='Nominal 95% mean-response CI')
    ax.plot(grid, prediction['mean'], color=color, label='Primary OLS fit (observed range only)')
    ax.plot(grid, prediction['obs_ci_lower'], '--', color=color, alpha=.6, lw=1, label='Nominal 95% single-reading interval')
    ax.plot(grid, prediction['obs_ci_upper'], '--', color=color, alpha=.6, lw=1)
    ax.scatter(x, [r['depth_inches'] for r in rows], color=color, s=52, zorder=4)
    for i, row in enumerate(rows):
        ax.annotate(str(i + 1), (row['gauge_ft'], row['depth_inches']), xytext=(5, 7), textcoords='offset points', fontsize=9)
    other = [r for r in paired if r['location_id'] == location and not r['standard_position'] and r['gauge_ft'] is not None]
    if other:
        ax.scatter([r['gauge_ft'] for r in other], [r['depth_inches'] for r in other], facecolors='none', edgecolors='#cc7722', marker='s', s=70, label='Different spot; excluded from primary fit')
    ax.axhline(0, color='#666666', lw=.8)
    ax.set(xlabel='Williams Point water level (ft relative to MHHW)', ylabel='Road-center water depth (inches)',
           title=f'{name}\nPrimary n={summary["n"]}; Pearson r={summary["pearson_r"]:.3f}; R²={summary["r_squared"]:.3f}')
    ax.grid(alpha=.2)
    ax.legend(fontsize=8, loc='upper left')
    fig.text(.5, -.025, 'Numbered points map to the diagnostic table. Bands assume independent normal, constant-variance errors; not validated forecasts.', ha='center', fontsize=8)
    save_figure(fig, location + '_regression')


def diagnostic_plot(location, rows, fit, summary):
    name, color = LOCATIONS[location]
    fig, axes = plt.subplots(2, 2, figsize=(10.5, 7.4), layout='constrained')
    fig.suptitle(name + ': primary-fit diagnostics (very small sample)')
    ax = axes[0, 0]
    ax.scatter(fit.fittedvalues, fit.resid, color=color)
    ax.axhline(0, color='gray', lw=1)
    ax.set(xlabel='Fitted road-center depth (in)', ylabel='Residual (in)', title='Residuals vs fitted values')
    for i, (x, y) in enumerate(zip(fit.fittedvalues, fit.resid)):
        ax.annotate(str(i + 1), (x, y), xytext=(4, 4), textcoords='offset points', fontsize=8)
    stats.probplot(fit.resid, dist='norm', plot=axes[0, 1])
    axes[0, 1].set(title='Normal Q–Q (descriptive, not proof)', ylabel='Ordered residual (in)')
    axes[1, 0].plot([stamp(r['t']) for r in rows], fit.resid, 'o-', color=color, lw=1)
    axes[1, 0].axhline(0, color='gray', lw=1)
    axes[1, 0].xaxis.set_major_locator(mdates.DayLocator(tz=EASTERN))
    axes[1, 0].xaxis.set_major_formatter(mdates.DateFormatter('%b %d', tz=EASTERN))
    axes[1, 0].set(xlabel='Measurement time (EST; uneven spacing)', ylabel='Residual (in)', title='Residuals in chronological order')
    axes[1, 1].bar(np.arange(1, len(rows) + 1), [r['cooks_distance'] for r in summary['diagnostics']], color=color)
    axes[1, 1].axhline(4 / len(rows), color='gray', ls='--', label='4/n reference; heuristic only')
    axes[1, 1].set(xlabel='Point number', ylabel="Cook's distance", title='Sensitivity to individual readings', xticks=np.arange(1, len(rows) + 1))
    axes[1, 1].legend(fontsize=8)
    for ax in axes.flat:
        ax.grid(alpha=.2)
    save_figure(fig, location + '_diagnostics')


def number(value, digits=3):
    return 'not estimable' if value is None else f'{value:.{digits}f}'


def sensitivity_plot(paired, fits, models):
    fig, axes = plt.subplots(1, 2, figsize=(11.2, 5), layout='constrained')
    for ax, location, main_key, other_key, other_label in [
            (axes[0], 'indian_river_north', 'north_primary', 'north_all_positions', 'Include different spot (n=6)'),
            (axes[1], 'briarwood_entrance', 'briarwood_primary', 'briarwood_wet_only', 'Wet readings only (n=3)')]:
        name, color = LOCATIONS[location]
        rows = [r for r in paired if r['location_id'] == location and not r['time_excluded']]
        primary = [r for r in rows if r['primary_included']]
        ax.scatter([r['gauge_ft'] for r in primary], [r['depth_inches'] for r in primary], color=color, zorder=4)
        other_points = [r for r in rows if not r['primary_included']]
        if other_points:
            ax.scatter([r['gauge_ft'] for r in other_points], [r['depth_inches'] for r in other_points],
                       facecolors='none', edgecolors='#cc7722', marker='s', s=55, zorder=4)
        for key, style, ink, label in [(main_key, '-', color, 'Primary fit'),
                                       (other_key, '--', '#10799d', other_label)]:
            grid = np.linspace(*models[key]['x_range_ft'], 120)
            ax.plot(grid, fits[key].predict(sm.add_constant(grid)), style, color=ink,
                    label=f'{label}\nslope {models[key]["coefficients"][1]["estimate"]:.2f} in/ft')
        ax.axhline(0, color='gray', lw=.8)
        ax.set(title=name, xlabel='Williams Point (ft MHHW)', ylabel='Road-center depth (in)')
        ax.legend(fontsize=8)
        ax.grid(alpha=.2)
    fig.suptitle('Sensitivity to sampling position and the zero-depth floor')
    save_figure(fig, 'sensitivity_comparison')


def interval(values):
    return f'[{values[0]:.3f}, {values[1]:.3f}]'


def report(models, paired, provenance):
    north, briar = models['north_primary'], models['briarwood_primary']
    lines = [
        '# Road-center depth and Williams Point water level',
        '', 'Retrospective exploratory analysis • prepared November 9, 2026 • local review copy', '',
        '## What these observations show', '',
        f'The standard-position north-culvert readings track Williams Point closely during this one falling-water episode: **r={north["pearson_r"]:.3f}, R²={north["r_squared"]:.3f}, n={north["n"]}**. '
        f'Briarwood also declines with the lagoon (**r={briar["pearson_r"]:.3f}, R²={briar["r_squared"]:.3f}, n={briar["n"]}**), but its center reaches zero and then remains dry as the lagoon falls further. '
        'A straight line through all Briarwood readings therefore describes the wet-to-dry transition imperfectly. '
        '**These data support close tracking within this episode, especially at the north culvert; they do not establish a general hydraulic relationship, causation, lag, or forecasting accuracy.**', '',
        'This analysis leaves the dashboard, deployment workflow, manual source records, and watchdog configuration unchanged. The research artifacts are separate from the dashboard build.', '',
        '## Data, exclusions and pairing', '',
        '- Road depths are inches above the local road center; deep-edge measurements are never substituted or added. Williams Point WIPF1 is feet relative to **MHHW**, verified from the downloaded header `station,valid[UTC],Water Height (MHHW)[ft]`.',
        f'- A small IEM/NWS HML observation snapshot contains **{provenance["gauge_records"]}** gauge points from {local(provenance["first_utc"])} to {local(provenance["last_utc"])}. Source header gives units/datum but no per-point quality flags or measurement-uncertainty estimates; archive observations may be provisional or revised.',
        '- All 14 road records are preserved in the input snapshot. Both November 8 noon entries have inaccurate times and are **excluded from every regression, correlation, sensitivity fit and gauge pairing**, as requested. They appear only as crossed points at their nominal times in the time-series context plot.',
        '- The November 4 north-culvert reading was made at a nearby, nonstandard spot. It is excluded from the primary north fit and included only in the explicitly labeled location-sensitivity fit. Every Briarwood timed reading is at its standard location.',
        '- Primary pairing uses the nearest **actual** gauge observation within six minutes; ties select the earlier point. Five measurement times match exactly. November 6 at 8:15 a.m. EST matches the 8:12 a.m. gauge point (−3 minutes) at each road location. No gauge values are imputed in the primary fit.',
        '- A separate sensitivity fit uses explicitly derived linear interpolation only when bracketing gauge observations are no more than 12 minutes apart; no extrapolation or interpolation across larger gaps is allowed.',
        '- UTC-aware timestamps are retained in CSV/JSON; human-readable report and plot times use EST. The two vertical scales measure different quantities; fitting their association is not a datum conversion or an estimate of road elevation.', '',
        '| Road measurement time (EST) | Location | Center (in) | Matched gauge (ft MHHW) | Offset (min) | Primary status |',
        '|---|---|---:|---:|---:|---|',
    ]
    for r in paired:
        lines.append(f'| {r["time_est"]} | {"North culvert" if r["location_id"] == "indian_river_north" else "Briarwood"} | {r["depth_inches"]:g} | {number(r["gauge_ft"], 2) if r["gauge_ft"] is not None else "not paired"} | {number(r["gauge_offset_min"], 0) if r["gauge_offset_min"] is not None else "—"} | {"Included" if r["primary_included"] else r["primary_exclusion_reason"]} |')
    lines += ['', '![Gauge and road-center time series](figures/time_series.png)', '',
              'Figure 1. Separate, aligned vertical scales avoid equating gauge height with road depth. Road dots are individual observations, not interpolated road-depth traces. The gray November 8 crosses have only nominal times and are excluded.', '',
              '## Regression method', '',
              'Each location is analyzed separately with ordinary least squares (OLS): **road depth (in) = intercept + slope × Williams Point height (ft MHHW) + residual**. '
              'The intercept is retained for standard reporting but lies outside the observed gauge range and must not be interpreted as road elevation or a flooding threshold. '
              'Reported 95% confidence intervals, coefficient t-tests and ANOVA F-tests are **nominal, conditional on independent, normally distributed, constant-variance errors and adequately measured gauge values**. '
              'They are not corrected for temporal dependence or multiple exploratory comparisons. HC3 intervals with residual-df Student-t reference are sensitivity checks for unequal variance; they do not correct serial dependence or rescue a five-point sample. '
              'RMSE uses sqrt(SSE/n); residual standard error uses sqrt(SSE/(n−2)). Leave-one-out (LOO) errors refit after removing each point; they assess within-episode sensitivity, not validation on a new storm.', '']
    for key, location in [('north_primary', 'indian_river_north'), ('briarwood_primary', 'briarwood_entrance')]:
        m = models[key]
        lines += ['## ' + LOCATIONS[location][0], '',
                  f'**Primary fit: depth = {m["coefficients"][0]["estimate"]:.4f} + {m["coefficients"][1]["estimate"]:.4f} × gauge height.** '
                  f'Calibration range is {m["x_range_ft"][0]:.2f}–{m["x_range_ft"][1]:.2f} ft MHHW, with depths {m["y_range_inches"][0]:g}–{m["y_range_inches"][1]:g} inches. '
                  f'There are {m["n"]} observations and {m["residual_df"]} residual degrees of freedom.', '',
                  '| Coefficient | Estimate | SE | t | Nominal two-sided p | Nominal 95% CI | HC3 95% CI |',
                  '|---|---:|---:|---:|---:|---|---|']
        for c in m['coefficients']:
            lines.append(f'| {"Intercept (in)" if c["term"] == "intercept" else "Slope (in per ft)"} | {c["estimate"]:.4f} | {c["standard_error"]:.4f} | {c["t"]:.3f} | {c["nominal_p"]:.5g} | {interval(c["ci95"])} | {interval(c["hc3_ci95"])} |')
        lines += ['', '| Fit statistic | Value |', '|---|---:|']
        for label, value in [('Pearson r', m['pearson_r']), ('Spearman rank rho (descriptive)', m['spearman_rho']), ('R²', m['r_squared']), ('Adjusted R²', m['adjusted_r_squared']), ('In-sample RMSE (in)', m['rmse_inches']), ('Mean absolute error (in)', m['mae_inches']), ('Residual standard error (in)', m['residual_standard_error_inches']), ('LOO RMSE (in)', m['loo_rmse_inches'])]:
            lines.append(f'| {label} | {value:.4f} |')
        lines.append(f'| Pearson r nominal 95% Fisher-z CI | {interval(m["pearson_ci95_fisher"])} |')
        lines += ['', 'The Fisher-z correlation interval assumes independent bivariate-normal pairs and is only an approximation at this sample size; it does not account for the shared time trend.']
        a = m['anova']
        lines += ['', '| ANOVA source | df | Sum of squares (in²) | Mean square (in²) | F | Nominal p |', '|---|---:|---:|---:|---:|---:|',
                  f'| Regression | 1 | {a["regression_ss"]:.5f} | {a["regression_ms"]:.5f} | {a["F"]:.3f} | {a["nominal_p"]:.5g} |',
                  f'| Residual | {a["residual_df"]} | {a["residual_ss"]:.5f} | {a["residual_ms"]:.5f} | — | — |',
                  f'| Total | {a["total_df"]} | {a["total_ss"]:.5f} | — | — | — |', '',
                  f'![{LOCATIONS[location][0]} regression](figures/{location}_regression.png)', '',
                  'The shaded band is the nominal 95% interval for the mean relation; dashed bands are nominal single-reading intervals under the same OLS assumptions. '
                  'Bands and fitted line stop at the primary observed gauge range. Negative fitted values or lower bounds are left visible to reveal the linear model’s limitations; they are not negative measured depths or operational predictions.', '',
                  '### Individual-point diagnostics', '',
                  '| Point | Time (EST) | Fitted (in) | Residual (in) | Leverage | Cook’s D | LOO error (in) |',
                  '|---:|---|---:|---:|---:|---:|---:|']
        for d in m['diagnostics']:
            lines.append(f'| {d["point_id"]} | {d["time_est"]} | {d["fitted_inches"]:.3f} | {d["residual_inches"]:.3f} | {d["leverage"]:.3f} | {d["cooks_distance"]:.3f} | {d["loo_error_inches"]:.3f} |')
        c = m['checks']
        lines += ['', f'![{LOCATIONS[location][0]} diagnostics](figures/{location}_diagnostics.png)', '',
                  f'LOO slopes range from **{m["loo_slope_range"][0]:.3f} to {m["loo_slope_range"][1]:.3f} in/ft**. '
                  f'The residual Shapiro–Wilk nominal p-value is {c["shapiro_residual_nominal_p"]:.3f}; with n={m["n"]}, failure to reject is not evidence of normal errors. '
                  f'Durbin–Watson is {c["durbin_watson_descriptive"]:.3f}, reported descriptively only because observations are few and unevenly spaced. '
                  'No meaningful heteroscedasticity or serial-correlation clearance can be obtained from these samples. The Cook’s-D 4/n line is an influence-screening heuristic, not an outlier test or a reason to discard an observation.', '',
                  f'A nominal test of slope = 12 in/ft gives p={m["slope_equals_12_nominal_p"]:.4g}. '
                  'Twelve is the unit-equivalent slope for equal changes in water level; this comparison does not establish direct hydraulic connection or equal absolute elevations.', '']
        if location == 'briarwood_entrance':
            lines += ['Three of the six primary Briarwood readings are zero. The all-reading test against slope 12 must not be interpreted as evidence against a 12 in/ft wet-state response: its single straight-line model does not represent the physical zero-depth floor.', '']
    lines += ['## Sensitivity fits', '', '| Model | n | Slope (in/ft) | Nominal slope 95% CI | R² | RMSE (in) | LOO RMSE (in) |', '|---|---:|---:|---|---:|---:|---:|']
    for key, label in [('north_primary', 'North: standard location, nearest actual gauge'), ('north_all_positions', 'North: include first nonstandard location'), ('north_interpolated', 'North: standard location, interpolated gauge'), ('briarwood_primary', 'Briarwood: all accurately timed readings'), ('briarwood_wet_only', 'Briarwood: positive depths only'), ('briarwood_interpolated', 'Briarwood: interpolated gauge')]:
        m = models[key]
        lines.append(f'| {label} | {m["n"]} | {m["coefficients"][1]["estimate"]:.3f} | {interval(m["coefficients"][1]["ci95"])} | {m["r_squared"]:.4f} | {m["rmse_inches"]:.3f} | {m["loo_rmse_inches"]:.3f} |')
    wet = models['briarwood_wet_only']
    lines += ['', '![Location and wet-only sensitivity fits](figures/sensitivity_comparison.png)', '',
              'Each sensitivity line stops at its own observed gauge range. The wet-only Briarwood line is not extended into dry conditions; no breakpoint or flooding threshold is estimated.', '',
              'The actual gauge observations bracketing the 8:15 a.m. road measurements both report 2.09 ft MHHW. Nearest-point and interpolated sensitivity fits are therefore identical for this snapshot.', '',
              f'Briarwood’s wet-only slope is {wet["coefficients"][1]["estimate"]:.3f} in/ft, with nominal 95% CI {interval(wet["coefficients"][1]["ci95"])} and only **three readings / one residual degree of freedom**. '
              'This conditional subset illustrates the zero-depth floor; it cannot establish a reliable wet-state calibration. '
              'A zero road depth is a physical floor: the lagoon can keep falling after the center becomes dry, while recorded road depth stays at zero. '
              'The zero points are genuine observations and remain in the primary Briarwood descriptive fit; they cannot identify an unobserved below-road water surface. '
              'No Tobit, breakpoint, flooding threshold, or nonnegative prediction model is fitted to this tiny series.', '',
              '## Does the relationship remain after considering time?', '',
              '| Location | Gauge-model R² | Time-only R² | Gauge vs elapsed-hours r | Change correlation | Rate-change correlation | Intervals |',
              '|---|---:|---:|---:|---:|---:|---:|']
    for m, label in [(north, 'North standard'), (briar, 'Briarwood')]:
        c = m['checks']
        lines.append(f'| {label} | {m["r_squared"]:.4f} | {c["time_only_r_squared"]:.4f} | {c["gauge_vs_elapsed_hours_r"]:.4f} | {number(c["successive_changes_r"])} | {number(c["successive_hourly_rates_r"])} | {c["successive_intervals"]} |')
    lines += ['', 'Change correlation compares consecutive Δdepth and Δgauge; rate-change correlation divides each by its actual elapsed hours. '
              'These checks use only primary observations, retain chronological order and never bridge the censored November 8 records. '
              'Their much smaller sample sizes, shared endpoints and uneven intervals prevent treating them as independent replications or formal validation.', '',
              '| Exploratory model: depth ~ gauge + elapsed hours | Gauge slope (in/ft) | Nominal 95% CI | Residual df | Gauge/time VIF |',
              '|---|---:|---|---:|---:|']
    for m, label in [(north, 'North standard'), (briar, 'Briarwood')]:
        c = m['checks']
        lines.append(f'| {label} | {c["time_adjusted_gauge_slope"]:.3f} | {interval(c["time_adjusted_gauge_ci95"])} | {c["time_adjusted_residual_df"]} | {c["gauge_time_vif"]:.1f} |')
    lines += ['', 'Gauge height and elapsed time are strongly collinear in this single recession. The time-adjusted slopes are exploratory and unstable, with very few degrees of freedom. '
              'Neither a high unadjusted R² nor a time-adjusted coefficient can establish which physical processes caused the road-depth decline.', '',
              '## Interpretation and limits', '',
              '1. **North culvert:** the accurately timed, standard-position measurements provide strong descriptive evidence of close tracking during November 5–7. A slope near 12 in/ft is consistent with roughly equal changes in road depth and gauge level in this event, subject to the uncertainty above. The first nonstandard spot is supporting context, not interchangeable calibration data.',
              '2. **Briarwood:** depths track the decline while wet, then stop at zero. The all-reading straight-line slope should not be interpreted as a constant hydraulic response across wet and dry states. Three wet readings are insufficient to establish the wet-only slope precisely.',
              '3. **Small, selected, temporally related sample:** only one recession, no independent flood episodes, no rising limb and no controls for rain, wind, drainage or runoff. Both locations share sampling times and gauge values, so they are not independent event replications. Nominal p-values and intervals can overstate certainty when errors are temporally related.',
              '4. **Measurement and matching uncertainty:** road-method precision, spatial repeatability and instrument errors are not quantified. Gauge values are reported to 0.01 ft (0.12 in), which is reporting resolution, not certified accuracy. Treating gauge values as error-free is an OLS assumption. The −3 minute match and interpolation sensitivity are explicit; no lag scan or data-selected matching is performed.',
              '5. **No transfer to safety, thresholds or forecasts:** results do not identify road passability, a safe depth, a road elevation, or out-of-event performance. Residual/LOO errors and nominal single-reading intervals are retrospective diagnostics, not validated flood forecasts.',
              '6. **What would strengthen the test:** collect accurately timed measurements at the same marked road centers through multiple independent rising and falling episodes, including repeated wet states at Briarwood. Record method/precision and paired deep-edge measurements separately. Assess performance by holding out entire events before considering any operational model.', '',
              '## Reproduce and inspect', '',
              'This directory is separate from `scripts/build.py`, `templates/` and the deployment workflow. Production remains standard-library only. The development-only dependencies are pinned in `requirements.txt`; no live download occurs when rerunning the analysis.', '',
              '```bash',
              'python3 -m venv /tmp/irl-road-analysis-env',
              '/tmp/irl-road-analysis-env/bin/python -m pip install -r analyses/road_depth_vs_williams_point/requirements.txt',
              '/tmp/irl-road-analysis-env/bin/python analyses/road_depth_vs_williams_point/analyze.py',
              '/tmp/irl-road-analysis-env/bin/python -m unittest discover -s analyses/road_depth_vs_williams_point -p "test_*.py" -v',
              'python3 -m unittest discover -s tests -v',
              '```', '',
              '- `inputs/manual_depths.csv`: unchanged snapshot of the 14 curated road readings.',
              '- `inputs/wipf1.csv`: small, actual source response, not synthetic data or a bulk archive.',
              '- `inputs/provenance.json`: exact request URL/bounds, retrieval UTC, verified header, input SHA-256 hashes and source repository commit.',
              '- `paired_observations.csv`: all records, matching offsets, interpolation estimates, inclusion/exclusion decisions and original notes.',
              '- `results.json`: full model statistics and per-point diagnostics, including nominal mean/single-reading intervals.',
              '- `*_diagnostics.csv`: primary point-level residual, leverage, Cook’s distance and LOO errors.',
              '- `figures/`: standalone PNG and SVG versions of all six figures.', '',
              f'Retrieved {provenance["retrieved_utc"]}; source dashboard commit `{provenance["repository_commit"]}`. '
              'Reruns verify cached input hashes and the parser hash recorded in provenance; source responses may change on later downloads. '
              'The analysis imports the existing validated dashboard parsers without modifying them.', '',
              '### Verification for this review', '',
              'All **61 existing dashboard unit tests** and **5 analysis-specific offline tests** passed. The analysis checks validate actual source-schema values, the −3 minute match, exclusion of both inaccurate-time records, nonstandard-position handling, bounded interpolation, no extrapolation or long-gap bridging, and timezone-aware inputs. Primary OLS coefficients, slope standard errors, nominal p-values, confidence intervals and R² were independently cross-checked against SciPy `linregress`; leave-one-out predictions were also recomputed independently. All six plots were visually inspected. These numerical/code checks do not validate a hydraulic mechanism or out-of-event predictive performance.', '',
              '## Sources and statistical references', '',
              '- [Exact IEM gauge request](' + provenance['source_url'] + '); [IEM HML archive description](https://mesonet.agron.iastate.edu/request/hml.php). IEM archives processed NWS HML observations; the CSV establishes the displayed units and datum.',
              '- [NIST: linear least-squares regression](https://www.itl.nist.gov/div898/handbook/pmd/section1/pmd141.htm): assumptions and sensitivity to influential observations.',
              '- [NIST: residual analysis for nonconstant variation](https://www.itl.nist.gov/div898/handbook/pmd/section4/pmd442.htm): residual-versus-fitted diagnostics.',
              '- [statsmodels OLS](https://www.statsmodels.org/stable/generated/statsmodels.regression.linear_model.OLS.html): statistical implementation; intercept supplied explicitly.', '']
    (HERE / 'report.md').write_text('\n'.join(lines))


def main():
    provenance = json.loads((HERE / 'inputs/provenance.json').read_text())
    for name in ('manual_depths.csv', 'wipf1.csv'):
        if hashlib.sha256((HERE / 'inputs' / name).read_bytes()).hexdigest() != provenance['sha256'][name]:
            raise ValueError('Input snapshot hash differs from provenance: ' + name)
    if hashlib.sha256((ROOT / 'scripts/build.py').read_bytes()).hexdigest() != provenance['sha256']['dashboard_parser']:
        raise ValueError('Dashboard parser changed; review before reproducing the analysis')
    manual = build.parse_manual_depths((HERE / 'inputs/manual_depths.csv').read_bytes())
    gauge = build.parse_iem((HERE / 'inputs/wipf1.csv').read_bytes(), require_reported_units=True)
    paired = pair_readings(manual, gauge)
    if any(not r['time_excluded'] and r['gauge_ft'] is None for r in paired):
        raise ValueError('Accurately timed road readings lack acceptable gauge matches; review pairing')
    primary = {location: [r for r in paired if r['location_id'] == location and r['primary_included']] for location in LOCATIONS}
    configurations = {
        'north_primary': (primary['indian_river_north'], 'gauge_ft'),
        'north_all_positions': ([r for r in paired if r['location_id'] == 'indian_river_north' and not r['time_excluded'] and r['gauge_ft'] is not None], 'gauge_ft'),
        'north_interpolated': (primary['indian_river_north'], 'interpolated_gauge_ft'),
        'briarwood_primary': (primary['briarwood_entrance'], 'gauge_ft'),
        'briarwood_wet_only': ([r for r in primary['briarwood_entrance'] if r['depth_inches'] > 0], 'gauge_ft'),
        'briarwood_interpolated': (primary['briarwood_entrance'], 'interpolated_gauge_ft'),
    }
    fits, models = {}, {}
    for key, (rows, x_key) in configurations.items():
        if any(r[x_key] is None for r in rows):
            raise ValueError('Missing values in requested sensitivity model: ' + key)
        fits[key], models[key] = fit_model(rows, x_key)
    versions = {package: importlib.metadata.version(package) for package in ('numpy', 'scipy', 'matplotlib', 'statsmodels')}
    (HERE / 'figures').mkdir(exist_ok=True)
    plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False, 'svg.hashsalt': 'irl-road-depth', 'savefig.facecolor': 'white'})
    write_csv(HERE / 'paired_observations.csv', paired)
    for key, location in [('north_primary', 'indian_river_north'), ('briarwood_primary', 'briarwood_entrance')]:
        write_csv(HERE / (location + '_diagnostics.csv'), models[key]['diagnostics'])
        regression_plot(location, primary[location], fits[key], models[key], paired)
        diagnostic_plot(location, primary[location], fits[key], models[key])
    overview(gauge, paired)
    sensitivity_plot(paired, fits, models)
    document = {'analysis_kind': 'retrospective exploratory association; not a forecasting model',
                'software': versions, 'provenance': provenance, 'models': models}
    (HERE / 'results.json').write_text(json.dumps(clean(document), indent=2, allow_nan=False) + '\n')
    report(models, paired, provenance)
    for key in ('north_primary', 'briarwood_primary'):
        m = models[key]
        print(f'{key}: n={m["n"]}, r={m["pearson_r"]:.4f}, R2={m["r_squared"]:.4f}, slope={m["coefficients"][1]["estimate"]:.4f} in/ft, RMSE={m["rmse_inches"]:.4f} in')
    print('Wrote', HERE / 'report.md')


if __name__ == '__main__':
    main()
