# Water-quality data discovery: northern Indian River Lagoon

Investigated **November 6, 2026**, using live public downloads, station metadata, and provider documentation. This is a discovery report, not a dashboard implementation. Dates below describe the responses retrieved that day, not guaranteed future availability. Compact request receipts and selected real records are in [the evidence file](water-quality-probes-2026-11-06.json); bulk responses remain outside the repository.

## Recommendation

1. **Start with continuous salinity at SJRWMD IRLI13.** A public export delivered recent hourly observations, explicit units, quality grades, and approval levels. Python standard-library retrieval worked without an account or browser. Recent values are **provisional**, not approved laboratory results.
2. **Treat local nitrogen as a separate historical, monthly dataset.** Verified IRLI13 results include total/dissolved Kjeldahl nitrogen, dissolved nitrate + nitrite, and dissolved ammonia. The newest sample returned by both tested WQP versions was **April 10, 2025**. Do not call these current nitrogen conditions or label Kjeldahl nitrogen as total nitrogen.
3. **Keep IRLI10 and IRLI15 as spatial comparisons**, after checking availability and comparable sample fractions/methods. Their retrieved WQP nutrient samples end December 4, 2024. These are not substitutes for missing IRLI13 observations.
4. **Do not use FAU as an automatic local fallback yet.** Titusville and Banana River datasets exist, but both returned entirely missing salinity/nitrate values in the recent week tested. Vero Beach has recent nitrate, but is about 100 km away and does not represent the neighborhood.

Before nitrogen integration, resolve the release lag with SJRWMD/FDEP, confirm the provider's preferred extract and qualifier definitions, and agree whether a separately labeled calculated total nitrogen product is wanted. No provider was contacted during this investigation.

## Stations and geographic relevance

The [FDEP June 2025 final North IRL BMAP](https://floridadep.gov/sites/default/files/25-1053.pdf) lists IRLI10, IRLI13, and IRLI15 as active monthly lagoon stations in NIRL-B. That verifies the monitoring design as of that report, **not uninterrupted collection or publication through November 2026**. Modern [WQP station metadata](https://www.waterqualitydata.us/data/Station/search?organization=21FLSJWM_WQX&lat=28.42&long=-80.75&within=15&mimeType=csv&zip=no) confirms their identifiers and coordinates.

| Station | Modern WQP identifier | Latitude, longitude (NAD83) | Approximate distance | Interpretation |
| --- | --- | --- | --- | --- |
| IRLI13 | `21FLSJWM_WQX-44916` | 28.393066, -80.735861 | 3.3 km | Best verified nearby lagoon site; west side, about 1 km south of SR 528 |
| IRLI10 | `21FLSJWM_WQX-44913` | 28.501210, -80.768594 | 9.2 km | Northern North IRL comparison |
| IRLI15 | `21FLSJWM_WQX-44918` | 28.335345, -80.713094 | 10.1 km | Southern North IRL comparison |

Distances are straight-line calculations from a deliberately coarse Cocoa/Briarwood-area reference, 28.42, -80.75. They are neither surveyed neighborhood distances nor hydrologic travel distances. The SR 528 causeway/channel separates the neighborhood area from IRLI13; geographic proximity alone does not establish identical mixing, salinity, or nutrient exposure. Lagoon samples do not measure road puddles or identify a source of nitrogen.

Nearby search results also included Banana River and inland/tributary stations. They should not be selected solely by distance: basin, barriers, waterbody type, and sampling method matter. The existing dashboard's NOAA forecast coordinate is not a verified neighborhood reference and was not used for station selection.

## SJRWMD continuous salinity: strongest immediate candidate

The [official water-quality hub](https://www.sjrwmd.com/data/water-quality/) links to the [public AQUARIUS portal](https://secure.sjrwmd.com/aqportal). Actual dataset selection, CSV export, and unauthenticated HTTP retrieval confirmed:

| Property | Verified result |
| --- | --- |
| Public location | `37375724`, named `IRLI13 - IRLI13 IRL S SR528` |
| Dataset | `Salinity.YSI_Calc@37375724`; current portal dataset number `4002`, location number `94` |
| Quantity | Sonde-derived/calculated salinity, provider unit **ppt / Parts per thousand** |
| Metadata record bounds | April 24, 2017 18:00 UTC through November 6, 2026 15:00 UTC at retrieval |
| Download tested | 184 consecutive hourly records, October 30 00:00 UTC–November 6 15:00 UTC; no hourly gaps in this short extract |
| Latest retrieved value | **18.265299 ppt**, November 6, 2026 **15:00 UTC / 10:00 a.m. EST** |
| Quality of this extract | Every record grade **0 = PROV**, approval **800 = Provisional**, interpolation type **1 = instantaneous** |

The older start date is metadata, not proof of continuous valid coverage since 2017. Calibration history, long gaps, sensor immersion depth, and performance over seasons were not audited. The 24 datasets returned for IRLI13 include conductivity, temperature, dissolved oxygen, pH, turbidity, relative chlorophyll and fDOM, but **no nitrogen dataset**. A `Field Visits` series is distinct from the continuous `YSI_Calc` series; selecting the former initially returned old field-visit data.

### Retrieval and UTC check

The provider's [dataset export page](https://secure.sjrwmd.com/aqportal/Data/DataSet/Export/Location/37375724/DataSet/Salinity/YSI_Calc/Interval/Latest) exposes a public two-step export: POST for a short-lived download token, then GET the ZIP/CSV. This is a download mechanism, not an account login. Both steps worked in `urllib.request` without cookies or browser automation. Do not persist or log the ephemeral token.

This exact pattern was tested; it is documentation, not production downloader code:

```python
import io, json, urllib.parse, urllib.request, zipfile

base = "https://secure.sjrwmd.com/aqportal/Export/"
params = dict(
    DataSet="Salinity.YSI_Calc@37375724", Calendar="CALENDARYEAR",
    DateRange="Days7", UnitID=240, Conversion="Instantaneous",
    IntervalPoints="PointsAsRecorded", ApprovalLevels="True", Step=1,
    ExportFormat="csv", Compressed="true", RoundData="False",
    GradeCodes="True", InterpolationTypes="True", Timezone=0,
)
request = urllib.request.Request(
    base + "DataSetToken?" + urllib.parse.urlencode(params),
    data=b"", method="POST", headers={"User-Agent": "IRL-dashboard discovery"},
)
with urllib.request.urlopen(request, timeout=30) as response:
    token = json.load(response)["Token"]
url = base + "DataSet?" + urllib.parse.urlencode(dict(params, Token=token))
with urllib.request.urlopen(url, timeout=30) as response:
    archive = response.read(1024 * 1024)
with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
    csv_text = zipped.read(zipped.namelist()[0]).decode("utf-8-sig")
```

The CSV starts with a dataset comment, then `Timestamp (UTC),Value (ppt),Grade Code,Approval Level,Interpolation Type`. Its timestamp text has no suffix, but the **explicit UTC header** supplies the timezone. A future parser must validate that header and attach UTC, not infer the timezone from the computer running the build. Preserve unrounded values internally; round only for display.

The public [dataset metadata](https://secure.sjrwmd.com/aqportal/Data/DataSets?locationid=94) and JSON `Data/DatasetGrid` also worked. **The grid's `timezone=-300` response used a `Z` suffix on local display times.** For the same value it returned `2026-11-06T10:00:00Z`, while `timezone=0` returned the correct `2026-11-06T15:00:00Z`. The UTC CSV and all 48 overlapping UTC grid records agreed within 1e-12 ppt. Never trust that grid suffix under a nonzero timezone parameter. The portal advertises a UTC−05 location timezone; it must not be mistaken for year-round Florida civil time.

These are portal-backed endpoints, not a verified stable, versioned API contract. Numeric IDs and unit conversion IDs should be checked against metadata before use; prefer the named export dataset. A guessed Swagger URL returned HTTP 200 with an **empty body**, so API documentation was not established by that response. Test the eventual 14-day export explicitly before shipping; the discovery download used the actual seven-day UI option.

Keep AQUARIUS grades and approval levels separately. Its grade `3`, for example, means an excellent calculated value in the portal legend; it is **not QARTOD flag 3**. Provisional values can be displayed with that label under a documented policy. Unknown/unusable/gap grades require explicit handling, not automatic acceptance because the value is numeric.

## Monthly nitrogen and salinity: SJRWMD via WQP and FDEP WIN

### Identifiers, coverage, and version checks

The [legacy IRLI13 station](https://www.waterqualitydata.us/provider/STORET/21FLSJWM/21FLSJWM-IRLI13/) is real, but querying only `21FLSJWM-IRLI13` misses the modern series. Its nutrient extract contained 1,982 result rows dated June 18, 1997–June 1, 2009. Modern data use **`21FLSJWM_WQX-44916`**. The older coordinates/datum also differ slightly; preserve aliases and coordinate provenance rather than treating names as unique keys.

Live results:

| Query | Result |
| --- | --- |
| Modern IRLI13, all physical/chemical results since Jan. 1, 2025 | 142 result rows; four sampling dates: Jan. 13, Feb. 13, Mar. 12, **Apr. 10, 2025** |
| Modern IRLI10 and IRLI15, results since Jan. 1, 2025 | Zero result rows in the tested WQP responses |
| Modern IRLI10 and IRLI15, nutrients since Jan. 1, 2024 | 84 rows each; 12 monthly sampling dates, Jan. 8–**Dec. 4, 2024** |
| WQX 3.0 `fullPhysChem`, all three modern stations since Jan. 1, 2025 | Same 142 IRLI13 rows; no newer sample or comparison-station results |

The [legacy API](https://www.waterqualitydata.us/data/Result/search?siteid=21FLSJWM_WQX-44916&startDateLo=01-01-2025&mimeType=csv&zip=no&dataProfile=resultPhysChem) and [WQX 3.0 API](https://www.waterqualitydata.us/wqx3/Result/search?siteid=21FLSJWM_WQX-44916&siteid=21FLSJWM_WQX-44913&siteid=21FLSJWM_WQX-44918&startDateLo=01-01-2025&mimeType=csv&zip=no&dataProfile=fullPhysChem) both delivered CSV with Python's standard library. WQX 3.0 changes column names; use its documented `fullPhysChem` profile, **not** legacy `resultPhysChem`, which produced HTTP 400. See the [official WQX 3.0 service guide](https://www.waterqualitydata.us/beta/webservices_documentation/) and [EPA migration reference](https://www.epa.gov/waterdata/water-quality-portal-modernization-quick-reference-guide).

These are **publication bounds of the tested extracts**, not demonstrated program end dates. The latest retrieved IRLI13 sample is roughly 19 months old. Result `LastUpdated`/`LastChangeDate` timestamps can be much newer than sample collection; they must never refresh the observation clock. Full modern historical coverage and provider release lag remain unverified.

### What the nitrogen numbers actually mean

Examples below are from IRLI13 activity `L20250571-001`, **April 10, 2025 11:42 EDT = 15:42 UTC**, and are historical observations, not current readings.

| Measurement | Fraction | Value | Method | Qualification |
| --- | --- | --- | --- | --- |
| Total Kjeldahl nitrogen (organic N + ammonia) | Total | **1.187 mg N/L** | 351.2 | No qualifier in the selected result fields |
| Kjeldahl nitrogen | Dissolved | **0.950 mg N/L** | 351.2 | No qualifier in the selected result fields |
| Nitrate + nitrite | Dissolved | **0.0351 mg N/L** | 353.2 | **I**, below practical quantitation limit 0.04; MDL 0.01 in WIN |
| Ammonia nitrogen | Dissolved | **0.091841 mg N/L** | 4500-NH3(G) | No qualifier in the selected result fields |

WQP explicitly supplies `as N` for these analytes. **No direct total nitrogen characteristic appeared in the tested modern results.** TKN excludes nitrate/nitrite; nitrate alone is also not total nitrogen. Ammonia is already part of TKN and must not be added to it again. Total and dissolved fractions cannot be silently interchanged.

The [SJRWMD status/trends methods](https://www.sjrwmd.com/data/water-quality/) describe a calculated TN product using TKN and nitrate + nitrite, including substitutions for unavailable components. That assessment procedure should not become an undocumented dashboard calculation. A future TN product needs an agreed formula, matching activities/fractions, treatment of censored values, and propagated qualifiers. Never substitute zero for a missing component. The 2025 status map summarizes earlier years; its medians/trends are not new nutrient observations.

The same monthly events include field salinity, conductivity, water temperature, dissolved oxygen, pH, chlorophyll and phosphorus measurements. April 10 has salinity **24.05 and 24.04 `ppth`** in two distinct field activities ten minutes apart; WIN calls these **PSU**. Keep both source unit labels and activity identities. Do not count the eight 2025 field salinity rows as eight months or merge them with continuous salinity without identifying methods and sampling context. Depth values are present, but their reference/relative-depth fields are incomplete; surface/bottom classification was not established.

### Qualifiers are an integration requirement

Both WQP versions returned blank dedicated qualifier fields even for some qualified results. For example, nitrate + nitrite above is `Final` with a blank qualifier field, but its comment contains `**I****I**`. FDEP WIN independently returns `valueQualifier="I"` for the matching activity/value and supplies both MDL and PQL.

Other retrieved comments contain `U`, `T`, `Q`, `J`, and combined tokens. Preserve the original qualification text internally and decode only explicit provider tokens; do not search arbitrary prose for single letters. “Final” is a processing status, not proof of an unqualified measurement. FDEP's [sampling guidance](https://floridadep.gov/sites/default/files/WMS-SamplingManual.pdf) describes I as between detection and practical quantitation limits, U as not detected, and T as below the laboratory detection limit. Confirm the applicable provider definitions before plotting. A non-detect is neither zero nor an ordinary point at its reported limit. Display censored/estimated values distinctly or omit them with an explanation; unknown flags should not silently pass.

### FDEP WIN: working API, but broader queries and latency

The [official WIN program](https://floridadep.gov/dear/watershed-information-network) provides [Swagger documentation](https://prodapps.dep.state.fl.us/dear-watershed/swagger-ui/index.html) and a working [OpenAPI document](https://prodapps.dep.state.fl.us/dear-watershed/v3/api-docs). GET `https://prodapps.dep.state.fl.us/dear-watershed/result-activities` worked without authentication with URL-encoded parameters:

```text
ActivityStartDateFrom (>=) = 2025-04-10
ActivityStartDateTo (<=)   = 2025-04-10
Organization ID          = 21FLSJWM
page                     = 0
size                     = 100
sort                     = resultKey,ASC
```

Exact spaces and comparison symbols are part of those parameter names. Responses have `content`, `totalElements`, `totalPages`, `size`, and zero-based `number`. The sample day reported 1,128 agency-wide results. A request for size 1,500 was **capped at 500**, so pagination must follow returned metadata. That first 500-row page included **35 IRLI13 rows**, location `44916`; the selected salinity/nitrogen values, activity IDs and times matched WQP. This confirms a usable alternate route and clearer native qualifiers, not an independent second set of measurements. Deduplicate mirror records by provider station/activity/result, never count WIN and WQP twice.

The documented filters cover organization and sampling/loading/update date, **not station**, requiring client filtering after pagination. One 2026 query timed out and another returned HTTP 500; successful known-day probes establish functionality but not production reliability or the newest local collection date. Large repeated exports should respect the API's off-hours guidance; do not page through the entire agency on every hourly dashboard build. The separate SJRWMD discrete-data tool failed TLS/access checks in this environment; that does not establish a provider-wide outage.

## FAU / SECOORA ERDDAP: verified coverage and missing-data traps

The [SECOORA catalog search](https://erddap.secoora.org/erddap/search/index.csv?page=1&itemsPerPage=100&searchFor=indian%20river%20lagoon) and individual metadata responses identify FAU as provider. Four datasets were tested using bounded hourly CSV queries and server-side last-numeric-value queries. The [FAU network site](https://www.irlon.org/) supplies station context, but station existence does not establish current sensor operation.

| Station / ERDDAP dataset ID | Coordinates | Distance | Metadata start | Last numeric salinity retrieved | Last numeric nitrate retrieved |
| --- | --- | --- | --- | --- | --- |
| Titusville / `indian-river-lagoon-titusville-i` | 28.5985, -80.7913 | 20.3 km | 2022-01-01 | **2026-06-29 18:00 UTC**, QC 2 | **2026-07-01 14:00 UTC**, QC 2 |
| Banana River / `indian-river-lagoon-banana-river` | 28.4549, -80.6387 | 11.6 km | 2022-01-01 | **2026-07-01 16:00 UTC**, QC 2 | **2026-07-01 16:00 UTC**, QC 2 |
| Malabar / `indian-river-lagoon-malabar-irl-` | 27.9751, -80.5368 | 53.7 km | 2022-01-01 | **2025-07-08 19:00 UTC**, QC 1 | **2023-06-18 02:00 UTC**, QC 1 |
| Vero Beach / `indian-river-lagoon-vero-beach-i` | 27.590117, -80.355258 | 100.1 km | 2014-12-17 | **2026-11-03 03:00 UTC**, QC 2 | **2026-11-06 08:00 UTC**, QC 2 |

Distances use the same coarse reference as above. Banana River is across Merritt Island in a different lagoon basin; its shorter map distance does not establish stronger hydrologic relevance than Titusville. Metadata starts are dataset bounds, not verified analyte-specific start dates.

Between October 30 00:00 UTC and November 6 15:00 UTC, each dataset returned **184 hourly rows**. Titusville, Banana River, and Malabar had **zero numeric salinity or nitrate values** in that extract. Current row timestamps and catalog coverage end dates therefore cannot establish freshness. Vero Beach had 100 numeric salinity values (35 QC 1, 65 QC 2) and 177 numeric nitrate values (111 QC 1, 66 QC 2). Its latest QC 1 salinity was October 31 10:00 UTC; latest QC 1 nitrate was November 6 07:00 UTC. These are more informative than file modification time.

The metadata exposes many other quantities—temperature, conductivity, oxygen, pH, chlorophyll, turbidity, phosphate and some weather/current variables—but the common schema does not prove that all sensors are installed, valid or reporting at each station. There is **no verified total nitrogen series** here.

### Variables, units, and flags

For metadata use `https://erddap.secoora.org/erddap/info/{dataset_id}/index.json`; for CSV use `/erddap/tabledap/{dataset_id}.csv?{variables}&{constraints}`. Python `urllib`, `json`, and `csv` suffice; no ERDDAP client package is needed. CSV has a header row **and a units row** before observations. Query receipts in the evidence file preserve actual encoded URLs.

| Field | Native metadata | Required handling |
| --- | --- | --- |
| `time` | UTC ISO timestamps | Require timezone-aware UTC |
| `sea_water_practical_salinity` | `1e-3`, standard name practical salinity | Retain provider convention and numerical values; confirm presentation as practical salinity before integration. Do not multiply the displayed values by 0.001 or relabel as absolute salinity in g/kg |
| `nitrate` | `mg.L-1`, long name Nitrate Concentration (NO3) | Metadata does not explicitly establish mass **as N** versus **as NO3** |
| `mole_concentration_of_nitrate_in_sea_water` | `micromol.L-1` | Unambiguous nitrate molarity; retain as such if used |
| `{variable}_qc_agg` | 1 pass, 2 not evaluated, 3 suspect, 4 fail, 9 missing | Read alongside every value; 2 is not a completed QC pass |
| `{variable}_qc_tests` | Encoded individual QARTOD test results | Preserve raw values/metadata for diagnosis |

Numeric fill values include `-9999`; flag fill values include `-127`; downloaded missing observations were `NaN`. A QC code alone cannot make `NaN` a real measurement. Reject missing/nonfinite values first. Keep QC 2 separate from QC 1, exclude fail/missing, and establish a policy for suspect/unknown values before display. Automated QARTOD pass is not proof of final laboratory validation.

Paired Vero Beach mass/molar nitrate values have a ratio about **0.014007 mg per micromole**, consistent with a nitrogen-mass basis, whereas nitrate-ion mass would give about 0.062005. This is an **inference from the downloaded values**, not an explicit provider definition. Do not silently rename `nitrate` as mg N/L. Confirm with FAU/SECOORA or use nitrate molarity with its native label. Nitrate remains only one nitrogen component regardless of unit conversion. Metadata `z=0 m` is not sufficient evidence of actual sampling depth.

A bounded last-value query was tested using `&time>=2022-01-01T00:00:00Z&nitrate!=NaN&orderByMax("time")` with selected time/value/QC columns. It returns the last **numeric** value, including QC 2; it does not itself return the latest QC-passed observation. Do not treat the result as current without checking its timestamp and flag. Requests should be bounded and infrequent; do not repeatedly download the full archive.

## Proposed integration after review

Keep the existing hourly GitHub Pages workflow and standard-library backend. Add optional observation fetchers to `scripts/build.py`, presentation to `templates/index.html`, and small real-schema offline fixtures/tests. Avoid new services, databases, browser dependencies, or coupling to the modeling repository.

- **Salinity:** request a bounded recent window from the named IRLI13 export with explicit UTC, native units, grades and approvals. Verify a 14-day option and source metadata. Display the latest valid sample time and provisional label; break traces at gaps. An optional water-quality failure must not erase the primary water-level dashboard or make an old sample appear fresh.
- **Nutrients:** use station-specific WQP retrieval initially, with WIN for qualifier cross-checking or a compact provider-approved extract. Fetch periodically at a pace suitable for monthly sampling, rather than traversing agency-wide WIN records hourly. A small reviewed observation snapshot committed at update time is a simple alternative if release/access remains inconsistent. Do not use Actions caches as the only durable scientific record.
- **Presentation:** separate recent hourly salinity from dated monthly nitrogen dots. Label each nitrogen form/fraction; do not interpolate sparse samples into current conditions. A longer historical window is appropriate for monthly data, independently of the 14-day weather/water-level view. Maintain conventional water-quality units rather than converting concentrations to household/imperial units.
- **Provenance:** retain canonical station plus aliases, coordinates/datum, provider, dataset/activity/result IDs, collection timestamp and original timezone, sample depth/reference, characteristic, fraction, speciation, native value/unit, method, censoring/detection limits, quality/approval fields, source URL, and retrieval time. Observation time, release/update time, and build time are separate clocks. Retain scientific comments needed to decode flags; exclude personal sampler/analyst identifiers from public outputs.
- **Acceptance tests:** exact UTC conversion (including EST/EDT), the AQUARIUS timezone trap and comment/header rows, blank/NaN/fill values, provisional and unusable grades, WQP comment-only qualifiers, WIN capped pagination and duplicates, total versus dissolved fractions, nitrogen basis, incomplete TN components, failed HTTP/empty/header-only responses, and traces with real gaps. Use the existing bounded retry/timeout approach; honor `Retry-After` and never hammer providers.

No health classifications, nutrient thresholds, flood relationships, or causal interpretations are supported by this discovery exercise.

## Verification and remaining work

Verified live: station identity/coordinates, both WQP schemas, actual monthly sample dates and nitrogen forms, WIN retrieval and matching IRLI13 results/qualifiers, AQUARIUS public CSV/JSON agreement in UTC, and FAU metadata, recent missingness and last numeric observations. Access failures and empty results are retained in the evidence receipts rather than interpreted as zero concentrations.

Still unverified: current monthly sample availability directly from the sampling program; full modern historical coverage; preferred stable SJRWMD API contract; continuous-sensor calibration/depth history and long-term gaps; FAU nitrate mass basis; complete provider-specific QC policy; long-term runner reliability; and new chart design. A later integration needs its own build and browser verification.

Repository inspection confirmed the existing IEM `waterheight` fix/regression test and the hourly `17 * * * *` schedule. **All 27 existing offline tests passed** (`python3 -m unittest discover -s tests -v`). Only research documentation/evidence was added; no production parser, template, data feed, workflow, generated public site, deployment or repository setting was changed. No commit or push was made for this research task.
