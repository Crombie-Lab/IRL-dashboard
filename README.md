# Indian River Lagoon Observation Dashboard

Separate **observational** dashboard for recent lagoon levels in Cocoa, Florida. It intentionally contains no flood model and no safety classification.

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

- **Williams Point WIPF1:** Iowa Environmental Mesonet (IEM) HML processed **observations** for the last 14 days. Keep the gauge's own reference datum; do not compare its absolute heights with other sites until datum conversion is verified.
- **Trident Pier 8721604:** NOAA CO-OPS for 7-day wind, atmospheric pressure and observed water levels (MLLW), plus predicted tides through the next 3 days. Wind and pressure use hourly sample data; ocean water levels use recent 6-minute data where available.
- All plots display source timestamps and explicitly state that observations are not a road-flood warning. If WIPF1 fetching fails, the build fails and the previously published dashboard stays online; optional Trident sources may fail without blocking deployment and a warning is shown.
- IEM services are third-party archives of NWS hydrological observations. HML records may be provisional, may have gaps, or may be delayed. This project is not an official NWS, NOAA, or USGS alert system.

## Scope separation

`briarwood-flood-monitor`: historical downloads, rainfall datasets, modeling, thresholds, validation, HPC and NAS archives.

`IRL-dashboard`: public, read-only recent observations and simple hydrology explanations.

When research is validated, expose *small, versioned, reviewed data products* from the analysis repository, rather than coupling the live dashboard directly to its development code or bulk raw archives.

## Limitations / first live test

This starter includes offline tests for parsing and rendering, but live HTTP response schemas and operational reliability **must be confirmed by the initial GitHub Actions run**. If the IEM WIPF1 stage column changes, update `select_stage_column` in `scripts/build.py`. If a NOAA CO-OPS product is unavailable for the station/time interval, the page displays an explicit missing-data message. Before broader publication, verify units, station datum and sample freshness against the source dashboards.
