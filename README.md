# sfdp-monitor

Dashboards published by DawnLabs on top of public Solana data, plus the generator behind them.

**Live site: https://nagumo-dawnlabs.github.io/sfdp-monitor/**

| Dashboard | What it shows |
|---|---|
| [SFDP Criteria Miss Rate](https://nagumo-dawnlabs.github.io/sfdp-monitor/criteria-miss/) | What share of the last X epochs each SFDP validator failed to meet program criteria |

No runtime dependencies (Python 3.10+ standard library only). The pages themselves load nothing from
third parties either — validator logos are fetched at build time and served from the same origin, so a
visitor's IP never reaches anyone else. Pillow is used only to downscale those logos; it is a build-time
dependency, and without it the build still runs and keeps the logos already on disk.

```bash
python3 build.py                      # regenerate docs/
python3 build.py --skip-unchanged     # don't write when nothing changed (what CI does)
python3 -m http.server -d docs 8000   # preview at localhost:8000
```

---

## Layout

```
build.py                    the one entry point for a build
sfdp_status.py              ad-hoc reporting CLI (writes CSV / Markdown / JSON)

solanaorg/                  data access for api.solana.org
  client.py                   ApiClient: rate limiting + disk cache + retries
  sfdp.py                     SFDP endpoints, state definitions, state-string assembly

sitegen/                    data-agnostic static site generator
  render.py                   minimal dependency-free template expansion
  registry.py                 Dashboard / DashboardData / BuildEnv types
  build.py                    writing docs/, change detection, asset placement
  logos.py                    fetching, downscaling and manifesting external images

dashboards/                 one module per dashboard
  __init__.py                 DASHBOARDS (the registry)
  criteria_miss.py            collection, aggregation, CLI report

templates/                  the actual HTML / CSS / JS files
  base.html                   shared layout (masthead / footer / Powered by DawnLabs)
  hub.html                    the dashboard index on the front page
  criteria_miss.html          page body
  assets/theme.css            design tokens and components shared by every page
  assets/table.js             shared sorting / filtering / paging / CSV export
  assets/criteria_miss.js     aggregation and row rendering specific to this page

docs/                       build output (GitHub Pages serves /docs from main)
  index.html                  hub
  criteria-miss/index.html    dashboard
  data/criteria-miss.json     machine-readable snapshot (the source of truth for change detection)
  assets/                     theme.css / *.js / the DawnLabs logo (shared by every page)
  assets/logos/               validator logos as 48px WebP + index.json (recording source URLs)

tests/                      pytest (never touches the API)
```

### Design notes

- **HTML / CSS / JS live in real files.** They are not embedded in Python strings, so completion,
  linting and syntax highlighting all work, and the design does not fork as pages are added.
- **One aggregation algorithm.** `aggregate()` in `dashboards/criteria_miss.py` is the definition;
  `templates/assets/criteria_miss.js` carries the same algorithm to the browser (each references the
  other in a comment). The CLI and the dashboard cannot structurally disagree on a number.
- **Shared assets.** One copy of each lands in `docs/assets/` and every page references it with
  `?v=<content hash>`. Embedding the logo as a data URI per page is gone, so nothing duplicates as
  pages are added.
- **Data is embedded in the HTML too.** One request is enough, and the page works opened over
  `file://`. `docs/data/*.json` exists for change detection and reuse (spreadsheet imports, comparing
  against a past snapshot).
- **Zero external requests.** Validator logos come from `mnImageUrl` (served by media.stakewiz.com /
  s3.amazonaws.com), are fetched at build time, downscaled to 48px WebP and served from
  `docs/assets/logos/`. At full size 355 logos would be roughly 15MB; downscaled they total under 1MB.
  `index.json` records the source URL of each, so nothing is re-downloaded while the URL is unchanged
  and the daily job only ever diffs the logos that actually changed.

---

## Adding a dashboard

1. Write `collect(env) -> DashboardData` and `DASHBOARD = Dashboard(...)` in `dashboards/<name>.py`.
2. Add `templates/<name>.html` (the body) and, if you need one, `templates/<name>_footer.html`
   (sources and disclaimer).
3. If the page needs its own JS, add `templates/assets/<name>.js` and list it in `Dashboard.scripts`.
4. Register it in `DASHBOARDS` in `dashboards/__init__.py`.

Layout, shared assets, change detection, the hub listing and deployment are all handled by `sitegen`.
Whatever you put in `DashboardData.stats` as `(value, label)` becomes the KPIs on the hub card.

The `BuildEnv` passed to `collect()` carries `client` (an `ApiClient`), `out_dir`, `cluster`, `history`,
`concurrency`, `max_missing_pct`, `want_assets`, `fixtures` and `log`. For a source other than SFDP, add
one more access package alongside `solanaorg`. If the page needs side artifacts such as images, write
them under `out_dir` and use a helper like `sitegen.logos.sync_logos()`.

`DashboardData.context` **must define `coverage`** — the one-line "what is covered, and how far back"
shown in the freshness badge. Undefined tokens are a build error, so forgetting it fails CI.

---

## Template syntax

`sitegen/render.py` supports exactly three constructs. There are no loops and no conditionals.

| Syntax | Meaning |
|---|---|
| `{{ name }}` | insert the value, HTML-escaped |
| `{{& name }}` | insert the value as-is (for HTML / JSON that is already safe) |
| `{{> partial.html }}` | expand another template, recursively |

Anywhere repetition is needed (hub cards, KPIs) a small partial is rendered and `join`ed on the Python
side. Referencing an undefined token raises, so a typo never silently becomes an empty string.

JSON embedded in a `<script>` goes through `json_payload()`. `json.dumps` does not escape `<`, so a
validator named with a `</script>` in it would end HTML parsing early and break the page. Validator
operators choose those names freely, so `<`, `>`, `&` and U+2028/2029 are all escaped out.

---

## Automatic updates

`.github/workflows/update.yml` runs `build.py` **daily at 03:00 UTC (12:00 JST)** and, when something
changed, commits and pushes `docs/` (Pages redeploys on its own).

- SFDP data only moves per epoch (roughly every 2–2.5 days), and the API lags by about two epochs on
  top of that, so once a day is plenty.
- **Days with no change produce no commit.** The SHA-256 of the HTML (before the build timestamp is
  substituted in) plus the data JSON is written into `<!-- build: … -->`, and `--skip-unchanged` skips
  writing when it matches. Editing a template or the CSS changes the hash, so pages still update even
  when the data did not.
- As a result the **Data as of badge** at the top of a page means "when the data last changed". The
  absolute UTC time is in the HTML (readable with JS disabled) and JS fills in the relative time
  ("updated 3 hours ago") from `<time datetime>`.
- **The build aborts if more than 2% of fetches fail** (`--max-missing-pct`). This keeps a page where
  some validators were dropped by a 429 from being published and making the count move for no visible
  reason.
- Runner IPs are shared, so the job runs at `--rps 2 --concurrency 3` to stay under the rate limit
  (5–10 minutes).
- To run it by hand use **Run workflow** on the Actions tab (turning on `force` regenerates even with
  no change).
- **A failing job opens an issue automatically** (or comments on the existing open one).

`.github/workflows/ci.yml` runs `ruff` + `pytest` + a smoke build from a fixture on every push and PR.
It never touches the API, so it finishes in seconds.

To update by hand from a local checkout:
`python3 build.py && git add docs && git commit -m "update data" && git push`.

---

## Ad-hoc reporting CLI

```bash
python3 sfdp_status.py --epochs 10                                        # last 10 epochs (fetched from the API)
python3 sfdp_status.py --epochs 30 --min-rate 10                          # only miss rates of 10% or more
python3 sfdp_status.py --from docs/data/criteria-miss.json --epochs 64     # aggregate immediately, no API
python3 sfdp_status.py --from docs/data/criteria-miss.json --epochs 10 --end-epoch 990   # reproduce a past point in time
python3 sfdp_status.py --epochs 10 --cluster testnet
```

Passing a committed snapshot to `--from` finishes in tens of milliseconds. It runs the same
`aggregate()` as the dashboard, so the numbers match the table for the same window in the browser.

| Option | Default | Meaning |
|---|---|---|
| `--epochs N` | `10` | how many recent epochs to cover |
| `--end-epoch N` | latest | last epoch of the window (used to reproduce a past point in time) |
| `--from PATH` | — | snapshot JSON to read instead of calling the API |
| `--cluster` | `mainnet-beta` | `mainnet-beta` / `testnet` |
| `--states` | `Approved` | participant states to include, comma-separated; `all` for every one |
| `--min-rate PCT` | `0` | drop validators below this miss rate from the output |
| `--min-evaluated N` | `epochs/2` | drop validators with fewer rated epochs than this (excludes new onboardings) |
| `--top N` | `50` | rows to list in the Markdown report and on stdout |
| `--rps` / `--concurrency` | `4` / `4` | API rate (`api.solana.org` answers with 429, so don't push it) |
| `--no-cache` | off | bypass `.cache/` and always call the API |
| `--out-dir` | `out` | output directory (not tracked by git) |

It writes `out/sfdp_unmet_<cluster>_e<start>-<end>.{csv,md,json}`. The `csv` has the same columns as the
dashboard's CSV download; the `json` also lists the individual missed epochs.

A first run against the API takes about 3–5 minutes for 404 validators. Validator details are cached in
`.cache/` for an hour.

---

## How a miss is decided

In `GET https://api.solana.org/api/validators/<mainnetBetaPubkey>?cacheStatus=enable`, `mnStats.epochs`
is a full-history map of `{ "<epoch>": "<state>" }`, and that state corresponds one-to-one with the icon
shown on solana.org (verified against the frontend bundle's `ValidatorEpochStates` and against live
pages).

| state | UI icon | Meaning | Treated here as | Code |
|---|---|---|---|---|
| `Bonus` | 🟢 green star | met the matching criteria | met | `B` |
| `Baseline` | 🟠 orange check | matching unmet, residual met | **not counted as a miss** (only in `not_bonus`) | `L` |
| `None` | 🔴 red X | criteria not met | **miss** | `N` |
| `NoneHighThirdPartyStake` | 🟢 green party popper | third-party stake is high enough that no SFDP stake is needed | met | `H` |
| (absent from the map) | — | pre-onboarding or delinquent, no record | excluded from the denominator | `-` |

- **Miss rate** = `None` epochs ÷ epochs with data
- **not_bonus rate** = (`None` + `Baseline`) ÷ epochs with data
- **Streak** = consecutive `None` epochs ending at the most recent one. **Epochs with no data do not
  break a streak** (an absent record is not an achievement); `Bonus` / `Baseline` /
  `NoneHighThirdPartyStake` do.
- Miss rates are coloured **red at 20% or above, orange at 15%, yellow at 10%**, grey below that, and
  faintest at 0%. `RATE_TIERS` in `templates/assets/table.js` is the single definition of those
  thresholds.
- The denominator can be smaller than the requested window (new onboardings and so on), so by default
  only validators with data for at least half the window are shown.

Delinquency is decided by a different API (`/api/validators/vote-credits`) and never appears in the
`epochs` map, so it lands in `-` (no data) here.

Holding each epoch's state as a string of one-character codes (newest epoch first) is the central data
representation of this tool; every aggregation takes that string as input. The epoch map is walked in
exactly one place, `solanaorg/sfdp.py`.

---

## Data sources

- Participant list: `GET https://api.solana.org/api/community/v1/sfdp_participants`
  ([official docs](https://solana.org/delegation-api-docs#sfdp-participants))
  - Breakdown by state (as of 2026-07): Approved 404 / TestnetOnboarded 123 / Pending 11 /
    Retired 3,450 / Rejected 6,974
- Validator detail: `GET https://api.solana.org/api/validators/<pubkey>?cacheStatus=enable`
  (used internally by solana.org; outside the official docs)

This site is an unofficial aggregation of public API data, not a Solana Foundation publication.

---

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install ruff pytest pillow
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest

# smoke build that never calls the API
python3 build.py --fixture tests/fixtures/criteria-miss.json --out /tmp/site --history 64
```

`pillow` is needed only for downscaling logos (the build works without it, keeping the logos already on
disk). The tests use no network at all.

`tests/fixtures/criteria-miss.json` is 22 characteristic records pulled from real data plus one
synthetic record whose name contains `</script>`. It covers regressions in template expansion and in
script injection at the same time.
