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
- **Manual road depths:** six user-reported readings at the Briarwood Lane entrance/storm drain and Indian River Drive north culvert, transcribed from the supplied screenshot into `data/manual_depths.csv`. Original times include explicit EST offsets and are converted to UTC in published data. Depths are inches above the local road surface at road-center sampled low points. Display notes use the requested wording "depth at road center". Original sampling notes are preserved separately as `original_notes`, and the first north-culvert reading's nonstandard position remains flagged. The first metric card shows the latest north-culvert spot depth in red with its original sampling date, rather than implying it is continuously monitored. The chart overlays numbered depth markers on a separate right-hand inches axis, without interpolation, a fitted relationship, or a shared vertical scale/datum with Williams Point. These are historical spot measurements, not continuous road monitoring.
- **Trident Pier 8721604:** NOAA CO-OPS for 7-day wind, atmospheric pressure and observed water levels (MLLW), plus predicted tides through the next 3 days. Wind and pressure use hourly sample data; ocean water levels use recent 6-minute data where available.
- **NOAA / NWS weather forecast:** the grid covering the requested Cocoa-area point (28.3903, -80.8026), discovered via `api.weather.gov/points`. Forecast wind speed/gusts are converted from reported km/h to m/s; direction is degrees from true north. Precipitation is mm per original source interval, with probability in percent. Multi-hour totals are not split into hourly estimates. The grid represents an area, not a residential measurement or an observation at Trident Pier. Forecast update times and missing/stale status are visible; a forecast outage does not block publication of valid observations.
- All plots display source timestamps and explicitly state that observations are not a road-flood warning. If WIPF1 fetching fails, the build fails and the previously published dashboard stays online; optional Trident sources may fail without blocking deployment and a warning is shown.
- IEM services are third-party archives of NWS hydrological observations. HML records may be provisional, may have gaps, or may be delayed. This project is not an official NWS, NOAA, or USGS alert system.

## Scope separation

`briarwood-flood-monitor`: historical downloads, rainfall datasets, modeling, thresholds, validation, HPC and NAS archives.

`IRL-dashboard`: public, read-only recent observations, separately labeled NOAA weather forecasts, and simple hydrology explanations. No lagoon flood forecasts or safety classifications.

The two main observation charts show water level and wind on identical default UTC ranges (past seven days) and equal plot margins. Williams Point retains 14 days of data for exploration. Tide and pressure remain secondary context. The combined forecast chart defaults to the next 72 hours: wind/gusts in m/s on the left and precipitation in mm per source period on the right. It uses connected midpoint markers, with breaks across missing intervals; connecting segments are visual guides rather than sub-period estimates. Original validity bounds remain in hover text and published JSON. Sparse wind barbs sample speed and bearing only within their valid intervals; they update on zoom/resize, point toward the wind source, and encode speed rounded to 5 knots. Additional source periods remain available by zooming out.

When research is validated, expose *small, versioned, reviewed data products* from the analysis repository, rather than coupling the live dashboard directly to its development code or bulk raw archives.

## Limitations / first live test

Offline tests cover parsing, rendering, retries and failure handling. A local live build has populated Williams Point and all four NOAA feeds; deployment and browser appearance still require verification after a successful GitHub Actions run. NOAA requests explicitly select metric units and GMT, with MLLW for water levels and astronomical tides. If the IEM WIPF1 stage column changes, update `select_stage_column` in `scripts/build.py`. If a NOAA CO-OPS product is unavailable for the station/time interval, the page displays an explicit missing-data message. Before broader publication, verify units, station datum and sample freshness against the source dashboards.

## Adding a manual reading

Append a row to `data/manual_depths.csv` with an ISO timestamp including its UTC offset, a supported location ID, depth in inches, `true`/`false` for the standard position, and a sampling note. Do not infer missing depths or change historical readings silently. A malformed row stops the build so a measurement is not silently omitted. The source CSV and published `data.json` preserve these readings even after they move outside the default seven-day chart window.

## Wind-barb symbols

`assets/vendor/wind-barbs.js` reuses SVG glyphs from [qulle/svg-wind-barbs](https://github.com/qulle/svg-wind-barbs) pinned at `cdf807f0565673850c116490bcbd548c099c5fec`, under the included BSD 2-Clause license. A small wrapper selects the nearest 5-knot glyph and rotates its north-pointing shaft by the reported meteorological from-bearing. It runs locally with the existing Plotly version; no package installation or additional charting framework is required. Calm rounded winds use the circular symbol.
