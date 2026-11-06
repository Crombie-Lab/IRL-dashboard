# Focused security review — November 6, 2026

Scope: the new cluster-side watchdog, current Python downloader, static HTML/Plotly presentation, tracked files, and Pages workflow. This is a targeted code/configuration review, not a penetration test or a guarantee that dependencies contain no vulnerabilities. No external service was attacked or fuzzed.

## Findings and changes

| Finding | Practical exposure | Change |
| --- | --- | --- |
| Cron executing a group-writable checkout could expose its token to changed code | A project-group writer could modify the script subsequently run by the account | Installer creates a reviewed private home-directory copy; cron uses isolated Python and never auto-pulls code. Private file ownership/modes, ancestors and symlinks are checked. |
| GitHub credential theft or accidental disclosure | A token could trigger/manage Actions in its permitted repository | Dedicated fine-grained token, one repository, Actions read/write only, private file, hidden prompt. No token in args, cron, public files, exception bodies or logs. No broad existing Git credential is reused. Fixed HTTPS API endpoints and refused redirects prevent forwarding the token elsewhere. |
| Repeated/storming dispatches | Missed schedules, uncertain POST responses or overlapping cron runs could consume Actions quota | Lock, pre-POST persisted cooldown, six-hour budget, active-run checks, publication grace, `Retry-After`, bounded requests. A dispatch always uses current `main`. |
| Plotly CDN script lacked integrity verification | A changed CDN response would execute in visitors' browsers | Added SHA-384 subresource integrity and anonymous CORS to the existing exact Plotly version. The hash was computed from the live 2.35.3 asset; CDN CORS support was verified. |
| Workflow actions used movable tags | A tag change could change executed code | Pinned the existing action major versions to commits resolved from their official `actions/*` repositories. This pins direct actions, not every transitive dependency inside those actions. |
| Build job inherited deployment write/OIDC permissions | A compromised build dependency would have unnecessary deployment permissions | Build receives Contents read and Pages read; only the deploy job receives Pages write and OIDC. Checkout no longer persists Git credentials. The hourly schedule and normal deployment flow are preserved. |
| Downloader read upstream bodies without a size limit | A compromised/misbehaving provider could consume excessive build memory | Added a 16 MiB bound to each HTTP download, with an offline boundary test. Existing timeouts, retries and the smaller SJRWMD ZIP uncompressed-size validation remain. |

## Existing protections checked

- No private credentials are needed or intentionally published by the static site. Browser requests do not carry the watchdog token.
- The embedded JSON renderer escapes `</` before inserting a payload into a script element; changing upstream strings cannot directly terminate that element. User-facing warnings/notes use `textContent`. The only `innerHTML` occurrence found in the dashboard is a fixed empty-state string. This review did not identify a concrete injection exploit through current source values.
- NWS grid URLs are constrained to the expected NOAA HTTPS host and grid path. Observation parsing validates expected scientific units/schema; invalid readings remain missing rather than becoming executable content.
- SJRWMD export tokens are ephemeral and omitted from published provenance/errors. ZIP content is read in memory, validated as one small CSV, and not extracted to filesystem paths.
- There is no server-side application, user login, form submission, database, or uploaded-content execution in this site. Runtime dependencies in the downloader/watchdog are Python standard library.
- A tracked-file credential-pattern scan is run without printing matched secret values. Its scope does not establish the absence of secrets from untracked private files, GitHub settings, or every historical commit.

## Dependency and residual limitations

An OSV API query for npm `plotly.js` version `2.35.3` returned no matching advisory on November 6, 2026. This is an exact package/version check, not a complete audit of bundled/transitive JavaScript. The Plotly version is unchanged. Integrity verification prevents unexpected CDN bytes; it does not prove the approved library itself is free of flaws. GitHub Pages header/CSP controls and transitive action dependencies were not comprehensively hardened in this small change.

Actions write permission is broader than permission to dispatch just `pages.yml`: token theft could disrupt Actions or consume quota in the one permitted repository. It does not grant Contents write through this configuration. An account compromise, root administrator, or malicious trusted code can still read/use the token. Token expiration and organization approval must be monitored. The cluster must permit cron/outbound HTTPS and remain available.

GitHub scheduler gaps and Pages outages remain availability risks; the watchdog only provides a bounded independent trigger. It cannot guarantee publication, validate upstream science beyond existing checks, or substitute for operational monitoring. No credential/cron entry is activated before the user creates the dedicated token.

Primary references: [GitHub fine-grained token permissions](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event), [GitHub Actions secure-use guidance](https://docs.github.com/en/actions/reference/security/secure-use), [Plotly security policy](https://github.com/plotly/plotly.js/security/policy), [OSV API](https://google.github.io/osv.dev/api/).
