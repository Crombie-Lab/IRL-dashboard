# Indian River Lagoon Observation Dashboard

Dashboard for recent **measured lagoon and coastal conditions** in Cocoa, Florida, with a separate **NOAA weather forecast** section. It intentionally contains no flood model and no safety classification.

## Publish rapidly on GitHub Pages

1. Create a new **public** repository named `IRL-dashboard` under the intended GitHub user or organization (for example `Crombie-Lab`).
2. Add all files from this starter repository, including `.github/workflows/pages.yml`, to its `main` branch. Do **not** publish any historical raw archives or house-specific information.
3. In **Settings → Pages → Build and deployment → Source**, choose **GitHub Actions**.
4. Open **Actions → Publish hourly lagoon monitor → Run workflow** (or push to `main`).
5. When deployed, the URL is `https://<owner>.github.io/IRL-dashboard/`. The `Crombie-Lab` example is `https://crombie-lab.github.io/IRL-dashboard/`.

The scheduled workflow runs at **17 minutes past each UTC hour**, but GitHub schedules are best-effort and may be delayed or skipped. Pushing a commit or clicking **Run workflow** triggers an immediate build (subject to runner availability).

## Local validation

```bash
python3 -m unittest discover -s tests -v
python3 scripts/build.py  # Requires external internet access
python3 -m http.server 8000 -d site
```

Open `http://localhost:8000/`.

The build uses Python 3's standard library; there are no pip dependencies. Plotly charts use a JavaScript CDN in the visitor's browser.

## Sources & handling

- **Williams Point WIPF1:** Iowa Environmental Mesonet (IEM) HML processed **observations** for the last 14 days. Values are feet relative to MHHW, verified from the returned `Water Height (MHHW)[ft]` header. The production build rejects unknown units/datums rather than applying this label to an unverified column. Do not compare absolute heights with other sites until datum conversion is verified.
- **Manual road depths:** eight user-reported road-center readings at the Briarwood Lane entrance/storm drain and Indian River Drive north culvert, transcribed from the supplied screenshot into `data/manual_depths.csv`. Original times include explicit EST offsets and are converted to UTC in published data. Depths are inches above the local road surface at road-center sampled low points. Display notes use the requested wording "depth at road center". Original sampling notes are preserved separately as `original_notes`, and the first north-culvert reading's nonstandard position remains flagged. The first metric card shows the latest north-culvert center-to-measured-deep-edge range when both were measured at that time, otherwise only the center depth, in red with its original sampling date, rather than implying it is continuously monitored. The chart overlays numbered depth markers on a separate right-hand inches axis, without interpolation, a fitted relationship, or a shared vertical scale/datum with Williams Point. These are historical spot measurements, not continuous road monitoring.
- **Trident Pier 8721604:** NOAA CO-OPS for 14-day wind, atmospheric pressure and observed water levels (MLLW), plus predicted tides through the next 3 days. Wind and pressure use hourly sample data; ocean water levels use recent 6-minute data where available.
- **NOAA / NWS weather forecast:** the grid covering the requested Cocoa-area point (28.3903, -80.8026), discovered via `api.weather.gov/points`. Forecast wind speed/gusts are converted from reported km/h to m/s; direction is degrees from true north. Precipitation is mm per original source interval, with probability in percent. Source JSON retains these metric units; the UI converts wind/gusts to mph (m/s ÷ 0.44704), rain to inches (mm ÷ 25.4), and Trident ocean/tide heights to feet (m ÷ 0.3048). Pressure stays in hPa; the gauge datums do not change. Small nonzero rain amounts below 0.01 inches are labeled <0.01 rather than zero. Multi-hour totals are not split into hourly estimates. The grid represents an area, not a residential measurement or an observation at Trident Pier. Forecast update times and missing/stale status are visible; a forecast outage does not block publication of valid observations.
- All plots display source timestamps and explicitly state that observations are not a road-flood warning. If WIPF1 fetching fails, the build fails and the previously published dashboard stays online; optional Trident sources may fail without blocking deployment and a warning is shown.
- IEM services are third-party archives of NWS hydrological observations. HML records may be provisional, may have gaps, or may be delayed. This project is not an official NWS, NOAA, or USGS alert system.

## Scope separation

`briarwood-flood-monitor`: historical downloads, rainfall datasets, modeling, thresholds, validation, HPC and NAS archives.

`IRL-dashboard`: public, read-only recent observations, separately labeled NOAA weather forecasts, and simple hydrology explanations. No lagoon flood forecasts or safety classifications.

Williams Point water level and Trident Pier wind share one card with aligned upper/lower panels and a single UTC time axis (past three days by default). Road-depth markers retain their separate right axis on the upper panel; wind barbs occupy the space above the lower panel. All observation plots retain 14 days of history for exploration. Tide and pressure remain secondary context. The NOAA forecast sits directly below the combined observation card and defaults to the next three days, with a Full forecast option: wind/gusts in mph on the left and precipitation in inches per source period on the right. It uses connected midpoint markers, with breaks across missing intervals; connecting segments are visual guides rather than sub-period estimates. Original validity bounds remain in hover text and published JSON. Thin wind barbs occupy a dedicated aligned row above the curves, with compass labels. They sample speed and bearing only within their valid intervals, update on pan/resize, point toward the wind source, and encode speed rounded to 5 knots. The Next 72 hours / Full forecast controls make later forecast precipitation accessible. A summary distinguishes zero reported amounts from nonzero precipitation probability and flags missing coverage. Panning is bounded by the available data (up to 14 days back for observations), retaining the selected window width at either end. Charts use horizontal panning with fixed vertical ranges fitted to the full downloaded traces. Zoom controls, wheel zoom, double-click zoom, Shift-drag zoom, and axis range editing are disabled; Reset views restores the initial time windows. The two forecast buttons remain explicit preset views.

When research is validated, expose *small, versioned, reviewed data products* from the analysis repository, rather than coupling the live dashboard directly to its development code or bulk raw archives.

## Lagoon water quality

The first top card shows the latest valid IRLI13 water temperature (°F), salinity (ppt), and turbidity (FNU), with actual observation times and provisional/approved status. One card below the forecast stacks these three measurements on aligned panels sharing a time axis. It defaults to three days and retains fourteen days of hourly observations from SJRWMD's public AQUARIUS export, location `37375724`. No nitrogen data or calculated total nitrogen is added.

The November 6, 2026 source checks found **no public continuous feed for IRLI14 or IRLI15**. Both are explicitly labeled unavailable in this recent view. IRLI14 does exist in the historical catalog (`21FLSJWM_WQX-IRLI14`); IRLI15 is `21FLSJWM_WQX-44918`, with the latest retrieved salinity/temperature/turbidity samples dated December 4, 2024. These older monthly samples are not carried into the present or replaced with another station. Their NTU turbidity measurements are not assumed equivalent to IRLI13's FNU sensor method.

The backend downloads native `Salinity.YSI_Calc`, `Water Temp.YSI`, and `Turbidity Form Neph.YSI` series via public tokenized exports (no account required). Tokens are transient and omitted from published data/errors. Requests specify UTC, instantaneous points, full precision, grades and approvals. CSV dataset identity, UTC header and native units must match. JSON preserves °C; only the UI converts to °F. Values, grade/approval/interpolation codes, request bounds, retrieval time and named source links remain in published JSON.

Quality policy: accept instantaneous observations with AQUARIUS grade 0 (provisional), 1–3 (excellent), or 11–13 (good), and approval 800 (provisional) or 1200 (approved). Label a point provisional if either its grade or approval is provisional. Working/unknown approvals, unusable/fair/poor/unknown grades, and missing/nonfinite/sentinel values are excluded from plotted values; dated invalid values remain null to break lines. Invalid timestamps are omitted with a notice. These are provider quality categories, not QARTOD codes or flood thresholds. Each variable fails independently; visible panel notices report missing/excluded values or outages. Latest valid samples over three hours old are marked delayed even in an open tab.

Small offline fixtures in `tests/fixtures/aquarius_irli13_*.csv` contain selected real UTC export rows retrieved November 6, 2026, including two grade −2 salinity readings. Tests mutate copies only to exercise malformed schema, missing values, unverified units/timezones, invalid dates, future observations and failure paths. Discovery documentation and request receipts are under `docs/`.

## Limitations / first live test

Offline tests cover parsing, rendering, retries and failure handling. A local live build has populated Williams Point and all four NOAA feeds; deployment and browser appearance still require verification after a successful GitHub Actions run. NOAA requests explicitly select metric units and GMT, with MLLW for water levels and astronomical tides. If the IEM WIPF1 stage column changes, update `select_stage_column` in `scripts/build.py`. If a NOAA CO-OPS product is unavailable for the station/time interval, the page displays an explicit missing-data message. Before broader publication, verify units, station datum and sample freshness against the source dashboards.

## Adding a manual reading

Append a row to `data/manual_depths.csv` with an ISO timestamp including its UTC offset, a supported location ID, depth in inches, `true`/`false` for the standard position, and a sampling note. Do not infer missing depths or change historical readings silently. A malformed row stops the build so a measurement is not silently omitted. The source CSV and published `data.json` preserve these readings even after they move outside the default three-day chart window.

## Wind-barb symbols

`assets/vendor/matplotlib-barbs.js` contains vector paths generated by **Matplotlib 3.10.8**, matching the [Matplotlib wind-barb example](https://matplotlib.org/stable/gallery/images_contours_and_fields/barb_demo.html). The included Matplotlib license applies. Standard half/full feathers and filled flags encode 5/10/50 knots, rounded to the nearest 5 knots. The 28-pixel shaft is centered, with clearer feathers and an unfilled low-speed circle. `assets/wind-barb-adapter.js` converts input m/s to knots and rotates the north-pointing paths clockwise to NOAA’s wind-from bearing; plotted wind curves remain mph. Low-speed circles show their actual mph value (or calm), and compass labels remain beneath other symbols. Symbols occupy a separate row and resize/reposition when panning. Very high-speed glyphs scale down to keep all flags within the symbol box; missing speed or a missing non-calm direction produces no symbol.

The Trident Pier panel in the combined observation chart uses the same Matplotlib barb track above its wind/gust curves, replacing the separate direction-dot axis. Both curves use mph and connected markers with breaks across observation gaps. Direction remains available in wind hover text. The track selects at most one actual observation per UTC sampling bucket, with spacing adjusted to the visible range and screen width. It uses each selected record's timestamp, speed and wind-from bearing together; it never interpolates or carries a reading through a missing interval. The forecast track continues to sample only within NOAA's explicit valid intervals. Both tracks share positioning and rendering code and update when panning, resetting or resizing.

The checked-in paths cover 0–700 knots, including the forecast parser’s full accepted speed range. **No new production dependencies:** the hourly build remains Python standard library and the browser uses only saved SVG geometry. For intentional asset regeneration, install `matplotlib==3.10.8` in a development environment and run `python3 scripts/generate_barb_paths.py`; the generator is not invoked by builds or unit tests.

The page keeps short neighborhood-facing captions. Detailed source, datum, sampling, and wind-symbol notes remain available in expandable sections; units, observation dates, missing-data notices, and attribution links remain visible.

## Freshness and open tabs

The hourly GitHub schedule is best effort: scheduled runs can be delayed or dropped even while the workflow is enabled. A manual Actions dispatch rebuilds the site without a code change. The page checks a small `update.json` publication marker every five minutes while visible and when returning to the tab, reloading a newer published snapshot with cache revalidation. Freshness notices are recalculated each minute even if no new publication arrives. Poll failures preserve the currently displayed data; they do not mark old observations as fresh. This browser check cannot trigger a missed Actions run or provide guaranteed hourly updates.

The top status dot and “Site updated” timestamp describe publication freshness only: amber means the published build is over three hours old. Individual missing/delayed feeds and quality notices remain labeled by source; a failed optional fetch does not turn the whole site amber. Williams Point and wind cards also mark their own observations delayed after three hours. Optional NOAA and SJRWMD outages do not block other feeds; failure of mandatory Williams Point after bounded HTTP retries preserves the previous publication. Forecast freshness uses its separate twelve-hour threshold. The hourly schedule cannot guarantee unattended hourly publication during GitHub scheduler gaps or Pages outages; a separately authorized external trigger would be needed to reduce dependence on that scheduler.


## Next rain card

The rain card summarizes the first future/active group of adjoining NOAA accumulation periods with positive forecast amounts. It sums each source total once, converts mm to inches, and shows the original window in Eastern time. Dry periods, missing values, and time gaps break groups; overlapping accumulation periods disable the card summary with a visible source warning rather than double-counting. It does not multiply the amount by precipitation probability. The percentage is the maximum NOAA probability among periods overlapping the window, labeled peak chance; it is not an inferred probability for the entire event. Incomplete probability coverage is labeled highest available chance. A window already underway retains its full source total and is explicitly marked as including earlier hours, rather than estimating remaining rainfall. Earlier missing rain coverage is noted. No positive amount is described as 0 inches only with complete valid coverage; a nonzero rain chance may still be shown. Missing/expired forecasts show unavailable. The card advances past completed windows each minute; the pressure chart remains available below.


The November 6, 2026 8:15 a.m. EST readings are 4.25 inches at the north-culvert road center and 0 inches at Briarwood's road center. The paired north-culvert deep edge was measured at 9.5 inches and is stored separately in optional `deep_edge_depth_inches`. The card shows 4.25–9.5 inches, labeled center to deep edge; only 4.25 is plotted. The 5.25-inch difference is a single paired observation, not a validated fixed correction, and is not applied to any other date or location. Briarwood's suggested 3–6 inches at the edge was explicitly not measured and remains only in the original note. Blank edge fields mean unmeasured; they are never filled from older readings. A new manual reading can advance the shared three-day observation window beyond a lagging gauge timestamp so it remains visible; gauge traces stop at their actual last observation and the shared latest manual time bounds panning.
