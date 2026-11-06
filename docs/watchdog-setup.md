# Independent publication watchdog

The public repository contains the reusable watchdog, installer, and offline tests. Installation copies reviewed code into a **private home-directory location**. Credentials, runtime state, cron backups and logs remain there and are never published. The dashboard still builds and deploys entirely in GitHub Actions; the cluster only checks publication freshness and occasionally triggers `pages.yml` on `main`.

## Behavior

- Cron invokes a short-lived Python standard-library process at minutes 7, 22, 37 and 52 each hour. It does not need an interactive login to remain open. Confirm the chosen login host permits this use and owns the intended crontab; cluster cron configuration and outbound networking are separate from installing a script.
- If the public `update.json` timestamp is less than 90 minutes old, it exits after one HTTPS request, without reading the token.
- For an overdue publication, it checks the workflow's recent `main` runs. Queued/running/waiting runs are left alone. A 15-minute grace period after completed runs allows Pages/CDN publication to settle. It does not cancel jobs.
- If still overdue, it dispatches the existing workflow on current `main`. It does not rerun an obsolete commit, push code, or change GitHub settings. The existing hourly UTC schedule is unchanged.
- A private file lock prevents overlapping watchdog processes. A persisted one-hour cooldown starts **before** the dispatch request, so a lost POST response does not cause an immediate duplicate. At most six dispatch attempts are allowed per six-hour window. Valid `Retry-After` values are honored without immediate HTTP retries.
- A malformed/missing/future-dated marker, failed GitHub query, unexpected API schema, or unsafe private file causes a logged error and no dispatch. An unreachable marker is not assumed to mean a missed build.
- Only GitHub's fixed API destinations receive authorization. Redirects are refused. HTTP requests have 20-second timeouts and 1 MiB response limits. Logs omit credentials/response bodies and rotate at 128 KiB, retaining two backups.

This catches missed schedules and can trigger a new build after an earlier deployment failure. It does not itself retry steps inside GitHub, fix a provider outage, force Pages to complete, or bypass a stuck active workflow. A cluster outage or expired token can also stop recovery. It is an informational service, not guaranteed hourly monitoring.

## 1. Create a dedicated token

In GitHub, open **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**.

Select:

- A descriptive name, such as `IRL dashboard watchdog`.
- Resource owner **Crombie-Lab**.
- Repository access: **Only select repositories → IRL-dashboard**.
- Repository permission **Actions: Read and write**; leave other optional permissions unset. Metadata read access is automatic. Do not grant Contents write, administration, account-wide, or organization-wide permissions.
- A finite expiration consistent with organization policy; note a renewal date.

Organization approval may be required before the token can dispatch runs. A fine-grained token with Actions write can manage other Actions operations in this repository too; GitHub does not restrict it to a single workflow. Limiting the repository is essential.

Do not paste the token in chat, a shell command, a crontab line, the repo, or a shared environment file. The installer prompts using hidden terminal input and writes it directly to the private file.

References: [GitHub token setup](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens), [workflow dispatch permission](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event).

## 2. Install the private copy and token

Run from a reviewed checkout on the chosen cron host:

```bash
python3 scripts/install_watchdog.py --set-token
```

Use your intended Python environment for both setup commands and check `python3 --version` first. The cron entry records that interpreter's absolute path, so it does not need interactive environment activation on each run. The small watchdog/installer support Python 3.6+ standard-library interfaces; a currently maintained Python environment is preferred. This does not change the dashboard build's Python 3.12 environment in GitHub Actions.

If an older pinned checkout reports `unlink() got an unexpected keyword argument 'missing_ok'`, update to the reviewed compatibility-fix commit before rerunning setup. Both installer cleanup and watchdog state saving avoid that Python 3.8-only argument. A failure while copying `watchdog.py` occurs before the token prompt; rerunning installation safely replaces that partial private copy.

The default location is `~/.local/share/irl-dashboard-watchdog/`, with directory mode 700 and private files mode 600. Group/world-writable ancestors, symlinks and unsafe existing files are rejected. Installation requires no administrator privileges. This command prepares the private code and token but **does not change cron**.

The shared project checkout can be writable by a project group. The cron process deliberately runs its private installed copy, with Python isolated mode (`-I`), rather than executing a changing shared checkout or automatically pulling remote code. Review future changes and rerun installation deliberately when upgrading. Anyone who controls the user account or trusted parent directories still controls its private code/token.

## 3. Check without triggering a build

```bash
python3 -I ~/.local/share/irl-dashboard-watchdog/watchdog.py \
  --directory ~/.local/share/irl-dashboard-watchdog --dry-run
```

Dry run uses public status endpoints and never reads the token or dispatches a workflow. It reports fresh, already active, cooldown, or “would dispatch.” The authenticated API path and dispatch permission remain unverified until the first real overdue check. Public dry runs can encounter the cluster's shared anonymous GitHub IP rate limit; real overdue checks authenticate API requests with the dedicated token.

## 4. Enable cron

After token setup and the dry run succeed:

```bash
python3 scripts/install_watchdog.py --install-cron
crontab -l
```

The installer backs up the current crontab privately, updates only its marked `IRL-dashboard watchdog` block, preserves other entries, and verifies that its entry was installed. No token appears in the entry. Repeating installation updates the managed block instead of duplicating it. The entry uses absolute paths and suppresses cron email/output; the watchdog writes its own rotating private log.

## Check operation and maintain it

```bash
tail -n 20 ~/.local/share/irl-dashboard-watchdog/watchdog.log
```

Normal fresh checks log `Publication fresh; no dispatch`. An overdue check should eventually log `Dispatched pages.yml on main` and appear in GitHub Actions as a `workflow_dispatch` event. Check that the public `update.json` advances after deployment. HTTP 401 commonly indicates an invalid/expired token; HTTP 403 can indicate missing permission, pending organization approval, or a rate limit. Response bodies are deliberately not logged. Renew a token with `--set-token`; revoke the previous token in GitHub.

The private `state.json` holds cooldown/attempt times, not the token. Do not delete it casually to bypass cooldowns. A one-hour quiet period after an uncertain request is intentional. A busy workflow is not cancelled or bypassed by this helper.

To disable the scheduler, use `crontab -e` and remove only the block between `# BEGIN IRL-dashboard watchdog` and `# END IRL-dashboard watchdog`. Preserve unrelated jobs. Revoke the token when retiring the watchdog. The ordinary GitHub schedule continues independently.

## Verification scope at handoff

Offline tests cover real publication/run schemas, invalid dates, failure paths, permissions, symlinks, locks, cooldowns, rate limits, credential destinations, response limits, and cron preservation. A live public dry run is separate from unit tests. No account token, active cron entry, or authenticated watchdog dispatch is installed as part of this handoff; those require the token creation steps above.
