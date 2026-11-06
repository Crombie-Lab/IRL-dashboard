# Publication and source freshness audit — November 6, 2026

The hourly workflow is active, on `main`, with its original `17 * * * *` UTC schedule. The recorded run history shows gaps in scheduled execution; the recent UI pushes did not change this schedule. All local times below use America/New_York (EST on these dates).

## Recorded evidence

- A push published at approximately 10:18 p.m. EST November 5.
- [Scheduled run 42184406234](https://github.com/Crombie-Lab/IRL-dashboard/actions/runs/42184406234) started at 2:58 a.m. EST November 6 and published at 2:59 a.m. Its actual data-download step returned 3,331 Williams Point observations, with the latest at 1:54 a.m.; all four NOAA feeds were populated, and the forecast update was 1:39 a.m. No source warnings appeared in that actual download step.
- The next recorded publication was a manual dispatch at approximately 7:03 a.m. EST. This left the 2:59 a.m. snapshot online for over four hours.
- [Scheduled run 42248064376](https://github.com/Crombie-Lab/IRL-dashboard/actions/runs/42248064376) started at 10:58 a.m. EST and published at 10:59 a.m. The actual download step again populated Williams Point and all four NOAA feeds without source warnings. Williams Point's latest timestamp was 9:54 a.m.; the forecast was updated at 10:14 a.m.
- These were the only two recorded schedule-triggered runs in the inspected history. Several push-triggered publications occurred between them. An absent run record does not establish GitHub's internal reason for not starting a scheduled run.
- [Run 42256001210](https://github.com/Crombie-Lab/IRL-dashboard/actions/runs/42256001210) passed tests, downloaded observations, and uploaded the Pages artifact, but its publication remained at `updating_pages` until the ten-minute deployment timeout. This was a separate failure from missing scheduled execution.
- [Run 42259227116](https://github.com/Crombie-Lab/IRL-dashboard/actions/runs/42259227116) subsequently built and published successfully. No workflow changes were needed for that successful publication.

Build logs also include deliberately simulated missing-feed messages from offline unit tests. Those messages are not evidence of production HTTP failures; inspect the later **Download recent observations and build dashboard** step separately.

## Fix and existing safeguards

Previously, any global source warning turned the top status dot amber, even when the publication and primary observations were fresh. The dot now depends only on publication age, with “Site updated” and an explicit delayed label after three hours. Source warnings remain visible with their own feed names. Water-level and wind cards also mark their own delayed observations. SJRWMD variables retain their independent notices and timestamps. Forecast updates retain the separate twelve-hour freshness threshold.

The downloader already retries transient HTTP failures with bounded backoff and honors `Retry-After`. Each optional NOAA feed, the weather forecast, and each SJRWMD variable can fail independently. An offline regression test now exercises each of the four optional NOAA feeds failing while all others publish. Mandatory Williams Point failure after retries still stops publication and preserves the previous valid site, as required by the repository's scientific safeguards.

Open tabs already check for a newer published snapshot every five minutes and when becoming visible. A failed marker request retains the current snapshot; it does not itself mark the site stale. Browser polling cannot initiate a GitHub Actions run.

## Remaining limitation

These changes correct the status indicator; they cannot make GitHub's best-effort scheduler start a missed run or force Pages to finish publication. The existing schedule requires no manual pushes, but its recorded gaps demonstrate that hourly updates are not guaranteed. For more dependable unattended operation, the next separately scoped option is an independent timed trigger invoking the existing workflow, with authentication held outside the public repository. That requires a hosting/account decision; no new service, credential, workflow, or repository setting is introduced by this fix.
