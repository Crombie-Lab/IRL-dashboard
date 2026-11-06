# AGENTS.md — IRL-dashboard

## Mission

Maintain a **small, reliable, observation-only** Indian River Lagoon monitoring website using GitHub Actions and GitHub Pages. Ship incremental improvements quickly without sacrificing scientific accuracy. For background, first read `PROJECT_CONTEXT.md` and the repository `README.md`.

## Repository boundaries

- This repo is **`IRL-dashboard`**, not the modeling project `briarwood-flood-monitor`.
- No flood predictions, road passability determinations, emergency warnings, or speculative thresholds without a separately validated and approved scientific workflow.
- Do not move bulk historical archives, personal data, house-specific locations, private credentials, or HPC/NAS configuration into the public repo or public site.
- Keep dependencies minimal. The existing downloader is Python standard library; the frontend is static Plotly HTML/JS. Do not introduce frameworks, services, databases, or major refactors for routine fixes.
- Preserve a clean separation between observation fetching/parsing (`scripts/build.py`), presentation (`templates/index.html`), tests (`tests/`), and deployment (`.github/workflows/pages.yml`).

## Required development workflow

1. Inspect current files and `git status` before editing. Do not assume a previously suggested fix was actually committed.
2. State the specific problem and propose the smallest change that fixes it. Prefer a targeted patch over rewriting working code.
3. For every parser change, add a small **offline fixture-based regression test** using the real observed schema. Test missing/invalid values, dates, units and failure paths as appropriate. Never require network access to run unit tests.
4. Run `python3 -m unittest discover -s tests -v`; report the results. Live HTTP tests are separate and should respect API limits, retries and timeouts.
5. When possible, run the build and inspect generated `site/` data and plots. Never label a synthetic example as a real observation.
6. Summarize exactly what changed, what was verified, what is still unverified and the deployment implications.
7. Do not push, alter GitHub repository settings, disable tests, or modify production workflows without user authorization; if authorized, keep commits narrowly scoped and monitor Actions after deployment.

## Data integrity and scientific conventions

- All observation timestamps stored as timezone-aware UTC; UI may format local time but must identify it.
- Keep **measured observations**, **astronomical tide predictions**, and later **model forecasts** explicitly distinct.
- Label stations, source providers, last observed timestamp, units and vertical datum directly in the UI.
- Williams Point `WIPF1` via IEM HML: inspect the actual header; one known header is `station,valid[UTC],Water Height (MHHW)[ft]`. Its values are **feet relative to MHHW** according to that header.
- Trident Pier NOAA CO-OPS `8721604`: current dashboard requests metric units; water level/tide use **meters relative to MLLW**, wind speed is **m/s**, pressure is **hPa**. Confirm units in actual responses before displaying values.
- Wind direction is the direction the wind **comes from**; 0°=N, 90°=E, 180°=S, 270°=W. Do not accidentally invert vectors/arrows.
- Do not compare or subtract absolute gauge levels across different stations/datums without a validated conversion. Never interpret a gauge height as water depth on a road.
- Do not silently impute missing observations, connect lines across long data gaps, display old readings as current, or hide upstream service errors. Add visible stale/missing notices.
- When explaining lagoon flooding, distinguish wind-driven redistribution, tidal boundary conditions, rainfall and restricted drainage. Avoid asserting causation without analysis.

## Reliability and deployment

- Preserve the existing GitHub Pages build/deploy workflow and its `17 * * * *` hourly UTC schedule unless a specific change is requested.
- Treat the schedule as **best effort**; use timestamps and freshness indicators. This is informational and not an alerting or safety-critical service.
- Honor API rate limits. For HTTP 429/5xx, retry with bounded exponential backoff and `Retry-After` when supplied; do not hammer upstream services.
- Williams Point observations are the primary dataset. If unavailable, fail safely or clearly preserve/mark the previously published data; optional NOAA feeds may be absent if clearly labeled. Avoid generating an apparently successful but empty site.
- The output folder `site/` is generated and `.gitignore`d. Keep all provenance metadata necessary to understand published values.
- Never log personal access tokens, store secrets in the repository, or paste credentials into scripts. GitHub Actions uses its built-in `GITHUB_TOKEN` for Pages deployment.

## Current first priority

The initial Actions run failed because `select_stage_column()` did not recognize `Water Height (MHHW)[ft]` from IEM. Before doing anything else, check if `scripts/build.py` already includes `waterheight` in its prefix match, and verify a regression test for that header. The corrected local starter had this fix, but the **status of live `main` is unknown**. After fixing/testing, run a fresh deployment and inspect the first live site's data.

## Deferred ideas (not part of initial bugfix)

Rainfall panels, gauge comparison, map of the lagoon and stormwater system, explanatory illustrations, and eventual publication of scientifically validated flood predictions. Treat each as a separate, reviewable change after stable live observation updates.
