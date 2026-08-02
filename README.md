# sfdp-monitor

Dashboards published by DawnLabs on top of public Solana data, plus the generator behind them.

**Live site: https://nagumo-dawnlabs.github.io/sfdp-monitor/**

| Dashboard | What it shows |
|---|---|
| [SFDP Criteria Miss Rate](https://nagumo-dawnlabs.github.io/sfdp-monitor/criteria-miss/) | What share of the last X epochs each SFDP validator failed to meet program criteria |
| [IBRL Criteria](https://nagumo-dawnlabs.github.io/sfdp-monitor/ibrl-criteria/) | Median slot time of each SFDP validator, slowest first, with its client and IBRL component scores |

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
  client.py                   ApiClient: rate limiting + disk cache + retries (shared by bam/ too)
  sfdp.py                     SFDP endpoints, state definitions, state-string assembly

trillium/                   data access for api.trillium.so
  rewards.py                  every figure the IBRL page tabulates, per validator per epoch

bam/                        data access for Jito's BAM APIs (what ibrl.wtf calls)
  ibrl.py                     IBRL score endpoints and score definitions (explorer.bam.dev)
  roster.py                   the BAM validator roster (kobe.mainnet.jito.network)

solanarpc/                  data access for the Solana JSON-RPC
  nodes.py                    getClusterNodes: validator client id / version, and the name table

sitegen/                    data-agnostic static site generator
  render.py                   minimal dependency-free template expansion
  registry.py                 Dashboard / DashboardData / BuildEnv types
  build.py                    writing docs/, change detection, asset placement
  logos.py                    fetching, downscaling and manifesting external images

dashboards/                 one module per dashboard
  __init__.py                 DASHBOARDS (the registry, and therefore the build order)
  criteria_miss.py            collection, aggregation, CLI report
  ibrl_criteria.py            collection and aggregation for the IBRL page

templates/                  the actual HTML / CSS / JS files
  base.html                   shared layout (masthead / footer / Powered by DawnLabs)
  hub.html                    the dashboard index on the front page
  criteria_miss.html          page body
  ibrl_criteria.html          page body
  assets/theme.css            design tokens and components shared by every page
  assets/table.js             shared sorting / filtering / paging / CSV export
  assets/criteria_miss.js     aggregation and row rendering specific to this page
  assets/ibrl_criteria.js     same, for the IBRL page

docs/                       build output (GitHub Pages serves /docs from main)
  index.html                  hub
  criteria-miss/index.html    dashboard
  ibrl-criteria/index.html    dashboard
  data/*.json                 machine-readable snapshots (the source of truth for change detection)
  assets/                     theme.css / *.js / the DawnLabs logo (shared by every page)
  assets/logos/               validator logos as 48px WebP + index.json (recording source URLs)

tests/                      pytest (never touches the API)
```

### Design notes

- **HTML / CSS / JS live in real files.** They are not embedded in Python strings, so completion,
  linting and syntax highlighting all work, and the design does not fork as pages are added.
- **One aggregation algorithm.** `aggregate()` in `dashboards/criteria_miss.py` is the definition;
  `templates/assets/criteria_miss.js` carries the same algorithm to the browser (each references the
  other in a comment). The CLI and the dashboard cannot structurally disagree on a number. The IBRL
  page does the same with `summarize()` / `score_class()`, and `tests/test_ibrl.py` additionally
  asserts that the JS colour thresholds still match the Python ones.
- **Data sources are packages, dashboards are pages.** `solanaorg/`, `bam/`, `trillium/` and
  `solanarpc/` only know how to fetch and shape data; `dashboards/` decides what a page means. A
  dashboard may read from several — the IBRL page takes its ranking metric from `trillium/`, component
  scores from `bam/`, the client from `solanarpc/`, and validator names, logos and stake from
  `solanaorg/`, joining them all on the identity pubkey for one common epoch. `solanaorg/client.py` is the generic HTTP layer (rate limiting, disk cache,
  retries) and is used for both hosts; `BuildEnv.make_client(base_url)` hands out a client that
  inherits the build's rate and cache settings.
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
- **Only one dashboard owns the logo directory.** `sync_logos()` deletes logos outside the set it was
  given, so a second dashboard syncing the same directory would delete the first one's files. The IBRL
  page therefore calls `available_logos()`, which only reads the manifest. That is why `criteria-miss`
  comes first in `DASHBOARDS`; running `--only ibrl-criteria` against an empty `docs/` just falls back
  to initial-letter avatars.

---

## Adding a dashboard

1. Write `collect(env) -> DashboardData` and `DASHBOARD = Dashboard(...)` in `dashboards/<name>.py`.
2. Add `templates/<name>.html` (the body) and, if you need one, `templates/<name>_footer.html`
   (sources and disclaimer).
3. If the page needs its own JS, add `templates/assets/<name>.js` and list it in `Dashboard.scripts`.
4. Register it in `DASHBOARDS` in `dashboards/__init__.py`.
5. Add `tests/fixtures/<slug>.json` and list it in `FIXTURES` in `tests/test_build.py`, so the tests
   and the CI smoke build keep working without the network.

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
- As a result the **Updated badge** at the top of a page means "when the data last changed". The
  absolute UTC time is in the HTML (readable with JS disabled); JS rewrites it into the viewer's own
  timezone — keeping the UTC value in `title` — and appends the relative time ("3 hours ago") from
  `<time datetime>`.
- **The build aborts if more than 2% of fetches fail** (`--max-missing-pct`). This keeps a page where
  some validators were dropped by a 429 from being published and making the count move for no visible
  reason.
- Runner IPs are shared, so the job runs at `--rps 2 --concurrency 3` to stay under the rate limit
  (5–10 minutes).
- **The IBRL page moves every day, not every epoch.** Its current-epoch scores are still accumulating
  while the epoch runs, so unlike the SFDP page it will normally produce a commit each day.
- The IBRL dashboard adds 15 Trillium requests (one per epoch of history, ~6MB each — the bulk of its
  build time), one tiny request for the epoch number, two more for the client column (`getClusterNodes`
  and the BAM roster), plus a re-read of the validator details that `criteria-miss` already pulled into
  `.cache/` earlier in the same job. Raising `HISTORY` raises the Trillium transfer linearly, so treat
  it as a real cost borne by someone else's free API rather than a free knob.
- If the public Solana RPC turns out to be unreliable from the runner, set a `SOLANA_RPC_URL` secret
  and pass it through as an environment variable — no code change needed. Until then a failure there
  only empties the Client column.
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

## How median slot time is measured

The ranking axis is **`slot_duration_median` from [Trillium](https://trillium.so/)** — the median time
the validator's slots actually took during the epoch, in milliseconds. The page sorts by it descending,
slowest first: a validator that is consistently slow holds up the whole leader rotation, and that is what
the page exists to surface.

- **Avg** is the mean of that median over the last `HISTORY` epochs, skipping epochs with no record. A
  single epoch bounces around, so the average is the steadier read.
- **Δ** is computed here from the embedded history (`this epoch − previous epoch`), **not** taken from an
  API field. A positive Δ means the validator got *slower*, so it is coloured like a regression — the
  opposite sign convention from a score.
- **Trend** plots the same epochs, newest on the left. Bar height is the slot time itself, so a **taller
  bar means a slower epoch**; this is the reverse of a score sparkline, which is why the column tooltip
  and the page notes both spell it out.
- Colour tiers are green ≤400ms, plain ≤420, yellow ≤440, orange ≤470, red beyond. **400ms is not an
  arbitrary round number** — it is the allowance IBRL's methodology gives a continuation slot for a
  perfect slot time score, and the validators fall into two visible groups either side of it.
  `MS_TIERS` in `dashboards/ibrl_criteria.py` is mirrored in `templates/assets/ibrl_criteria.js`, and a
  test fails if the two drift apart.
- A median over very few blocks swings a lot, which is what the **≥ 32 blocks** filter is for.

- Trillium's own `slot_duration_is_lagging` verdict is carried as `lag` and exposed through the
  **Lagging only** filter, a hover title on flagged rows and the CSV — but **not** as a column: 244 of
  358 validators carry it, so it groups rather than alarms, and the number in the Slot time column
  already says the same thing more precisely.

### The component scores alongside it

The three score columns are the components of the IBRL score from [ibrl.wtf](https://ibrl.wtf/), a
community tool from Jito that watches leader behaviour block by block. **Trillium republishes those exact
values** — verified identical to 4 decimal places for all 358 SFDP validators at epoch 1009 — so this
page reads them from Trillium rather than calling a second API for numbers it can already get. They are
kept as context for *why* a validator is slow. **The composite IBRL score itself is not displayed** (it
is still in the snapshot JSON). From [ibrl.wtf/methodology](https://ibrl.wtf/methodology/):

```
IBRL = 0.40 x Slot Time + 0.15 x Vote Packing + 0.45 x Non-Vote Packing
```

| Column | Weight in IBRL | Field in the API | What earns a perfect score |
|---|---|---|---|
| Slot score | 40% | `build_time_score` | 550ms or less on a handoff slot, 400ms on a continuation slot. Past that it decays exponentially |
| Vote pack | 15% | `vote_packing_score` | 90% of vote transactions inside the first 48 PoH ticks. Including no votes at all scores 0 |
| Non-vote | 45% | `non_vote_packing_score` | Half from spending 50% of the block's compute in the first 32 ticks, half from an even compute distribution across the 64 ticks (Gini coefficient) |

**Two different medians exist and they are not the same number.** IBRL publishes `median_block_build_ms`
and Trillium publishes `slot_duration_median`; they measure the same idea differently and usually agree
within a few ms, but not always (up to ~40ms apart at epoch 1009). This page shows Trillium's, and does
not display or store IBRL's — mixing two similarly-named medians in one table is a trap worth avoiding.

- **Every number in the table comes from one source, for one epoch.** The epoch is Trillium's own latest
  (`GET /api/epochs`, 52 bytes — no need to pull 6MB just to learn the epoch number), so no column can
  describe a different point in time, or a different methodology, from its neighbours.
- `explorer.bam.dev` is therefore no longer called by this dashboard. `bam/roster.py` still is, for the
  BAM-versus-Jito client distinction, and `bam.WEIGHTS` remains as a constant for the notes table.
- Validators with no slot duration for the epoch are left out of the table rather than shown as a zero,
  and the count is stated in the page's notes. At epoch 1010 that was 11 of 369.
- Scores are coloured green at 95, plain at 90, yellow at 80, orange at 70 and red below (`SCORE_TIERS`,
  mirrored in JS the same way).

### The Client column

What the validator advertises over gossip, read from `getClusterNodes` (one request for the whole
cluster) and shown with the version it reports.

`clientId` is an enum, and clients without a registered name arrive as `Unknown(<n>)`. The number-to-name
table in `solanarpc/nodes.py` is the same one ibrl.wtf uses — that is where *Rakurai* and *Harmonic* come
from. Numbers absent from the table are printed verbatim (`Unknown(12)`) rather than folded into Agave,
so a new client shows up as unrecognised instead of silently mislabelled.

**BAM needs a second source.** Running the BAM binary does not by itself make a validator an active BAM
validator, so a node advertising `AgaveBam` / `Unknown(6)` is labelled `BAM` only when its identity is
also on Jito's BAM roster, and `Jito` otherwise. This is what ibrl.wtf does, and the two agreed on all
15 validators spot-checked against the live site.

The RPC defaults to `https://api.mainnet-beta.solana.com`; override it with `--rpc-url` or the
`SOLANA_RPC_URL` environment variable. **The Client column degrades on its own**: if the RPC or the
roster cannot be fetched, the build logs a warning, leaves the column empty and still publishes the
page. It is one supplementary column, so it is not worth failing a build over — unlike the scores
themselves, which do abort the build.

---

## Data sources

- Participant list: `GET https://api.solana.org/api/community/v1/sfdp_participants`
  ([official docs](https://solana.org/delegation-api-docs#sfdp-participants))
  - Breakdown by state (as of 2026-08): Approved 369 / TestnetOnboarded 120 / Pending 12 /
    Retired 3,477 / Rejected 6,985
- Validator detail: `GET https://api.solana.org/api/validators/<pubkey>?cacheStatus=enable`
  (used internally by solana.org; outside the official docs)
- Everything the IBRL page tabulates:
  `GET https://api.trillium.so/validator_rewards/<epoch>` — `slot_duration_median` (ms, as a string),
  `slot_duration_is_lagging`, the three component scores and `blocks_produced`, per `identity_pubkey`,
  one request per epoch. **Roughly 6MB per epoch**, of which this site uses a handful of the 279 fields;
  that cost is why `HISTORY` is 15 rather than 30. The `epoch_validators_slim` route is far smaller but
  carries no slot duration, so it is not usable here.
- Latest epoch: `GET https://api.trillium.so/api/epochs` — 52 bytes. It lists only the last 10 epochs,
  but `validator_rewards/<epoch>` still serves considerably older ones, so treat it as "what is newest",
  not "what is available".
- `explorer.bam.dev` (`ibrl_validators`, `ibrl_stats`) is **no longer called by any dashboard** —
  Trillium carries the same score values. `bam/ibrl.py` is kept because it is the written-down
  definition of what those scores mean.
- Validator client and version: `POST https://api.mainnet-beta.solana.com` `getClusterNodes`
  (`clientId` + `version` per identity, whole cluster in one request)
- BAM roster: `GET https://kobe.mainnet.jito.network/api/v1/bam_validators?epoch=<n>` — used only to
  separate `BAM` from `Jito`; `is_eligible` is deliberately not filtered on, since being on the roster
  and being reward-eligible are different questions

The `explorer.bam.dev` endpoints are the ones ibrl.wtf itself calls; they are public and unauthenticated
but not formally documented, so treat their shape as subject to change.

This site is an unofficial aggregation of public API data, published by neither the Solana Foundation
nor Jito.

---

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install ruff pytest pillow
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest

# smoke build that never calls the API (every dashboard needs its fixture passed)
python3 build.py --out /tmp/site --history 64 \
  --fixture tests/fixtures/criteria-miss.json \
  --fixture tests/fixtures/ibrl-criteria.json
```

`pillow` is needed only for downscaling logos (the build works without it, keeping the logos already on
disk). The tests use no network at all.

Each fixture is a couple of dozen characteristic records pulled from real data — the extremes of every
column, rows with gaps in their history, a validator with no name and one with no logo — plus one
synthetic record whose name contains `</script>`. That covers regressions in template expansion and in
script injection at the same time. **A new dashboard needs a fixture**: without one the smoke build and
the tests fall through to the live API, and `test_every_registered_dashboard_has_a_fixture` fails to
remind you.
