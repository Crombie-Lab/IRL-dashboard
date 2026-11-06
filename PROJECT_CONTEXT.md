# IRL-dashboard — Project context and Codex handoff

**Project:** `Crombie-Lab/IRL-dashboard`  
**Repository:** https://github.com/Crombie-Lab/IRL-dashboard  
**Planned public site:** https://crombie-lab.github.io/IRL-dashboard/  
**Status at handoff:** GitHub repository created; first GitHub Actions deployment failed during the IEM CSV parsing step. The one-line fix has been identified; whether it has been pushed and whether a subsequent deployment has succeeded are **not confirmed**.

## Purpose and scope

Create a simple, trustworthy, public **observation-only** dashboard for the northern Indian River Lagoon near Cocoa, Florida. The site should display recent measured lagoon water levels, local/coastal weather, and Atlantic tide context, accompanied by a concise scientifically grounded explanation of wind setup, restricted ocean exchange, local rain, and stormwater drainage. It should be useful now, while the separate `briarwood-flood-monitor` project develops historical analyses and rigorously validated forecasts.

**Not in scope yet:** flood prediction, road passability or safety ratings, flood-warning alerts, historical model fitting, large archive downloads, research refactoring, or exposing residential/private location details. All public data should have visible source, units/datum, timestamps and stale-data status.

## Deployment architecture

- **Static GitHub Pages site:** no persistent backend, server, NAS connection, or HPC scheduler required.
- **GitHub Actions workflow:** `.github/workflows/pages.yml` on `main` pushes and manual dispatches; scheduled with `17 * * * *` (17 minutes past every hour, **UTC**, best-effort).
- **Build script:** `scripts/build.py` uses Python 3.12 in Actions; runtime dependencies are Python standard library only. Fetches public HTTP APIs; generates `site/index.html` and `site/data.json` from `templates/index.html`.
- **Front end:** static HTML/CSS/JavaScript with Plotly loaded from a CDN; `site/` is generated output ignored by Git.
- **Workflow permissions:** `contents: read`, `pages: write`, `id-token: write`; `actions/configure-pages@v5`, `actions/upload-pages-artifact@v4`, `actions/deploy-pages@v4`.
- **Pages setting:** Settings → Pages → Build and deployment → Source = **GitHub Actions**.

## Data displayed in the starter

| Layer | Station/provider | Current script window | Units/reference |
| --- | --- | --- | --- |
| Lagoon level | Williams Point `WIPF1`, NWS data via Iowa Environmental Mesonet HML CSV (`https://mesonet.agron.iastate.edu/cgi-bin/request/hml.py`) | Last 14 days | **Feet relative to MHHW**, per returned column name; audit against live source before broader publication |
| Coastal wind | NOAA CO-OPS Trident Pier `8721604` | Last ~7 days | Speed **m/s**; direction degrees **from** true north; gust if available |
| Atmospheric pressure | NOAA CO-OPS `8721604` | Last ~7 days | hPa |
| Observed ocean water level | NOAA CO-OPS `8721604` | Last ~7 days | **Meters relative to MLLW** |
| Predicted astronomical tide | NOAA CO-OPS `8721604` | ~7 days back, 3 days ahead | **Meters relative to MLLW** |

NOAA CO-OPS API: `https://api.tidesandcurrents.noaa.gov/api/prod/datagetter`.

**Scientific caution:** Williams Point and Trident Pier observations are at different locations and use different vertical reference datums. Never subtract or compare their absolute values without validated datum conversion. Do not equate lagoon gauge height with water depth on neighborhood roads. Actual observed and predicted tide levels may be compared only when station, units, times, and datums align. An IEM archive may lag, contain provisional measurements, or change CSV schemas.

## Exact failure from first Actions run

Workflow run: https://github.com/Crombie-Lab/IRL-dashboard/actions/runs/42141165543  
Job: **build** → `Download recent observations and build dashboard`  
Traceback from `python scripts/build.py`:

```text
ValueError: Cannot identify IEM stage column; CSV columns: station, valid[UTC], Water Height (MHHW)[ft]
```

**Root cause:** `select_stage_column()` in `scripts/build.py` did not recognize IEM's actual `Water Height (MHHW)[ft]` field. This shows the API response was received; the problem was local parsing, not evidence that observations were unavailable.

**Minimal fix** (check current code first; it may already have been applied):

```python
# in select_stage_column()
if compact.startswith(('stage', 'primary', 'gageheight', 'waterheight')):
```

The corrected starter ZIP includes this fix and a regression test, `test_iem_water_height_mhhw`, in `tests/test_build.py`. **Do not overwrite the live repository with a ZIP or assume it has the fix**—inspect current `main` first.

## Immediate next steps (in order)

1. `git status` and read the current `scripts/build.py`, `tests/test_build.py`, workflow, and template. Check whether the IEM column fix and regression test are already present.
2. Apply the smallest remaining parser correction, if needed. Preserve the returned units/datum in charts. Add or retain a regression test for the exact CSV header.
3. Run `python3 -m unittest discover -s tests -v`. Then, if network access permits, run `python3 scripts/build.py` and inspect `site/index.html` / `site/data.json` locally. Do not include real network calls in unit tests.
4. Commit a focused change and push to `main` **only with user's authorization**; otherwise show the diff/commands. Observe the next Actions build and deploy jobs; inspect failures rather than speculating.
5. Verify the published page in a browser: Williams Point plot populated, fresh observation timestamps, wind/pressure units and directions correct, observed/predicted tide plot populated (or clearly marked unavailable), mobile layout readable, and source links visible.
6. Improve graceful handling of upstream outages/stale data after the first working release. Avoid publishing a successfully refreshed page with silently empty or misleading graphs.

Useful CLI commands, when `gh` is authenticated:

```bash
python3 -m unittest discover -s tests -v
python3 scripts/build.py                        # Requires outgoing HTTP
python3 -m http.server 8000 -d site             # Local preview

gh run list --repo Crombie-Lab/IRL-dashboard --limit 5
gh run view RUN_ID --repo Crombie-Lab/IRL-dashboard --log-failed
```

## Relationship to research project

**`briarwood-flood-monitor`** is separate and should remain so for now. It holds historical station downloads, weather archives, geospatial drainage analyses, statistical modeling and validation. Its recent water-level acquisition recovered Williams Point observations from October 2024 to November 2026 and longer histories at Melbourne Causeway and USGS Haulover Canal. The standalone public dashboard **does not need** these large datasets to operate and should not copy them into the website repo.

Eventually, bring **validated, compact, versioned outputs** (e.g. reviewed thresholds or forecasts plus uncertainty and backtesting documentation) from the research project to the dashboard by a documented interface, not by prematurely merging repositories.

## Open questions for verification (not assumptions)

- Has the one-line IEM parser fix been pushed to GitHub `main`?
- Have the NOAA CO-OPS wind, air pressure, water level and predictions requests worked in a live Actions runner?
- Are the newest data timestamps recent enough for an informational monitor, and do we display a warning when delayed?
- Is `Crombie-Lab/IRL-dashboard` Pages configured with **GitHub Actions** and publishing at the expected URL?
- Should rainfall and local drainage maps be added after the initial deployment stabilizes? Not necessary to ship v1.

## Success criteria for v1

A successful manual or push-triggered GitHub Actions run publishes a functional, fast, mobile-readable site displaying genuine recent observations (not mock data) from Williams Point, visible measurement time and MHHW datum, other NOAA data where available, clear error/freshness indicators, and an accurate explanation of what these data can—and cannot—tell us about local flooding. An hourly schedule remains configured, without any claim of guaranteed hourly freshness or flood safety.
