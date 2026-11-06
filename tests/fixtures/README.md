`nws_grid.json` is a small excerpt of the NOAA/NWS MLB/49,64 grid response fetched November 6, 2026 UTC (updateTime November 5, 2026 23:29:48 UTC). It retains the first four source intervals for each displayed weather variable, with original units and values. These are forecast periods, not measured observations. Tests modify copies for invalid/missing cases.

`manual_depths.csv` contains the first paired road-depth readings from the user-supplied screenshot (November 4, 2026 at 4:00 p.m. EST), preserving the stated depths, time offsets, and sampling notes. It is an offline parser fixture; tests also verify all six curated source readings against the transcription.

Manual display notes were subsequently corrected by the user to "depth at road center"; the screenshot's initial wording remains in the `original_notes` column.
