# Repository Audit — August 2026

**Scope:** `datasnake-weather-intelligence` and `terrawatchapp-beta`
**Purpose:** Establish what is actually running, what is scaffolding, and what
should be retired before further work is invested.
**Status:** Audit only. **No code has been deleted.** Every disposition below
is a recommendation awaiting approval.

---

## Why this audit exists

Development paused on this repo for several months while `terrawatchapp-beta`
advanced independently. A new research dataset is being built in a separate
effort and will expose APIs for consumption here. Before wiring anything new
in — or building the location-based event browsing feature — we needed a
factual answer to "where are we," verified against running systems rather
than against the documentation.

The documentation turned out to describe an intended system, not the built
one. The gap is large enough that it changes what should be built next.

---

## Method

Findings below were verified against live systems, not inferred from docs:

- Queried the live Supabase project's `information_schema` directly for every
  table this repo claims to own.
- Read the actual bodies of the pipeline, API, and classification modules
  rather than their docstrings — the docstrings and the code disagree in
  several places.
- Cloned and read `terrawatchapp-beta` (migrations, edge functions, services).
- Grepped for call sites to distinguish live code from dead code.

---

## Finding 1 — Module 2 is scaffolding end to end. Nothing flows.

Module 2 (Vibration Intelligence) is documented across three files as a
working pipeline. It is not connected at any link in the chain.

| Chain link | Documented state | Verified state |
|---|---|---|
| Schema | `vibration_classified_events` live on Supabase | **Table does not exist** anywhere |
| Classification | PhaseNet wired into replay pipeline | **Hardcoded stub**, always abstains |
| Inference module | SeisBench inference for the API | **Zero callers** — dead code |
| API service | Deployed to Railway | **No evidence of deployment** |
| Consumer | `terrawatchapp-beta` reads `/events` | **Zero references** in that repo |

Evidence:

- `src/02_ml_pipeline/replay_pipeline.py:63-75` — `classify_window()` returns
  a literal `confidence: 0.0`, `abstain: True`, `requires_human_review: True`
  on every call. Its own docstring calls it a placeholder. Every row the
  replay pipeline could ever write would be an abstention.
- `src/03_api_service/app/modules/seismic/classify.py:27` — `classify_waveform()`
  has no call sites. A repo-wide grep returns only the definition itself and
  a passing mention in a docstring in `routers/events.py`. It has never been
  invoked by anything.
- `data/schema/pending_terrawatchapp_0049_vibration_classified_events.sql`
  was written to target `terrawatchapp-beta`'s database as migration `0049`.
  That repo is at migration **0048** and contains **zero** occurrences of
  `vibration_classified_events`. The migration was never applied and the
  consumer was never built.

**The `abstain: true` rows "dominating" is not a data condition to design
around.** It is the only possible output of the current code.

---

## Finding 2 — The database schema was never applied. Anywhere.

The only Supabase project reachable on this connection (`lkytlauunqhhfjyjqmsb`)
contains **none** of this repo's tables. A direct `information_schema` query
for all seven returned an empty result:

`weather_observations` · `seismic_events` · `flood_zones` · `seismic_stations`
· `risk_scores_cache` · `parametric_sensor_readings` · `vibration_classified_events`

That project is in fact a **different product entirely** — a podcast /
content-studio application (`collection_episodes`, `brand_shows`,
`voice_clones`, `admin_posts`, `episode_reels`). It has a `public.events`
table, but its columns are `episode_id`, `brand`, `cta_id` — web analytics,
not hazard events. The name collision is coincidental and actively
misleading.

`terrawatchapp-beta` runs on a **different Supabase project** whose ref is
held in CI secrets (`SUPABASE_PROJECT_REF`) and is not visible to this
session's connection.

**Consequence:** `noaa_ingestion.py` and `usgs_seismic.py` are genuinely
working code — 623 lines that correctly fetch, parse, retry, and deduplicate
— writing into tables that have never existed. They cannot have run
successfully against this project.

---

## Finding 3 — The chosen model cannot perform the stated task

This is an architectural defect, not an incomplete integration, and it would
not have been caught by finishing the wiring.

`classify.py:19-24` loads `seisbench.models.PhaseNet.from_pretrained("stead")`.
**PhaseNet is a seismic phase picker.** It identifies P-wave and S-wave
arrival times within a waveform. It does not classify events into categories.

The consuming code expects a categorical result:

```python
event_type=getattr(prediction, "event_type", "unknown"),
confidence=getattr(prediction, "confidence", 0.0),
severity_score=getattr(prediction, "severity_score", None),
```

PhaseNet's output carries none of those attributes. Every `getattr` falls
through to its default, so this function returns `event_type="unknown"`,
`confidence=0.0`, `abstain=True` — permanently, by construction, even once
"wired in."

The documented four-class target (`seismic` / `vehicle_human` /
`environmental` / `unknown`) requires an **event classifier**, not a phase
picker. This is a different model family and a different training objective.
The docs separately note `vehicle_human` has no labeled data in
STEAD/INSTANCE — so even the correct model architecture lacks a training set
for one of its four classes.

**Any plan that treats Module 2 as "nearly done, just needs the model wired
in" is proceeding on a false premise.**

---

## Finding 4 — TerraWatch has already superseded this repo

`terrawatchapp-beta` is not a downstream consumer awaiting this repo's API.
It independently built — and shipped — this repo's roadmap.

Scale: **48 migrations, 24 edge functions, 4 CI workflows, ~200 source files.**

Most directly: `terrawatchapp-beta/supabase/migrations/0040_flash_flood_rpc.sql`
opens by citing **this repo's architecture document** and implements its
formula verbatim:

```
P_flood = ((rainfall_mm - 40) / 100) * ((saturation - 0.3) / 0.2)
```

Likewise `insurance-risk-verdict/index.ts` implements the Risk Verdict API
specified in `docs/ARCHITECTURE.md` — with API-key auth, quota enforcement,
and live FEMA NRI data behind it.

TerraWatch is where DataSnake's design was actually built.

### Capability mapping

| Capability | This repo | TerraWatch | Verdict |
|---|---|---|---|
| Seismic ingest | `usgs_seismic.py` → missing table | `ingest-seismic` → `events`, hourly cron | **Superseded** |
| Weather ingest | `noaa_ingestion.py` → missing table | `ingest-weather`, `ingest-noaa-nws-obs` | **Superseded** |
| Risk Verdict API | Docs only, never built | `insurance-risk-verdict` (auth + quota) | **Superseded** |
| Flash flood EP curve | Formula in docs | `0040_flash_flood_rpc.sql` | **Superseded** |
| Events API | FastAPI, never deployed | `events_near()` RPC + `events.ts` | **Superseded** |
| Spatial event query | Planned | PostGIS `geography` + GiST, live | **Superseded** |
| Model registry | `model_registry.py`, unused | `0044`/`0045`/`0046` AI registry + log | **Superseded** |
| Scheduled ingestion | None | pg_cron, staggered, 10+ sources | **Superseded** |
| Vibration/waveform ML | Stub, wrong model | Not present | **Unique — but non-functional** |

TerraWatch's live hazard feeds: USGS seismic, NWS weather, NOAA space
weather, EONET/FIRMS wildfires, Smithsonian volcanoes, GDACS, NHC hurricanes,
OpenAQ air quality, NDBC buoys.

---

## Finding 5 — The location-browsing feature is largely already built

The proposed feature — *user types or selects a location, sees seismic and
disaster events there* — exists in TerraWatch today:

- **`events_near(center_lat, center_lon, radius_km, since_hours, max_rows)`**
  — PostGIS RPC in `0002_events_ingest.sql`, severity-then-recency sorted,
  granted to `anon` and `authenticated`. This is the feature's core query.
- **`searchPlaces()`** in `src/services/geocode.ts` — Open-Meteo geocoding
  with a 24h cache. Type-ahead location search already works.
- **UI**: `ExploreView` (MapLibre), `EventsMapView`, `EventsList`,
  `EventsFilters`, `EventDetailModal`, `RecentEventsStrip`, `GlobalEventsView`.
- **`events_recent` RPC** (`0008`) and **category counts RPC** (`0013`).

Remaining work is curation and tuning, not construction.

---

## Finding 6 — Two defects that would break the proposed locations

Recorded as audit findings. **No remediation work has been done or specced**
— deferred by decision.

### 6a. The magnitude floor excludes the named target regions

`ingest-seismic/index.ts` pulls `2.5_week.geojson` — a **M2.5 minimum**, 7-day
window. The comment explains the choice as noise reduction and payload size.

The regions of interest — New Madrid (St. Louis) and Ramapo (NJ / NY) — produce
events that are overwhelmingly **M1.5–M3.0**. A M2.5 floor filters out most
of the seismicity that makes those regions interesting, and the 7-day window
discards the rest quickly.

**Selecting those locations against the current feed would render a near-empty
map.** USGS publishes `all_hour.geojson` (all magnitudes, ~1 minute refresh)
which does not have this limitation.

### 6b. Retention deletes the historical record at 30 days

`events_prune(older_than_days integer default 30)` in `0002_events_ingest.sql`
hard-deletes events older than 30 days. This directly conflicts with showing
historical context alongside current activity. Any historical view needs
either extended retention for tracked locations or a separate archive table.

---

## Finding 7 — Security: RLS disabled on 9 tables

Flagged by Supabase's own advisor on the podcast/content-studio project:

`admin_posts` · `collection_episodes` · `broadcast_posts` · `app_settings`
· `page_views` · `episode_reels` · `episode_publications`
· `episode_social_posts` · `events`

These are fully exposed to the `anon` and `authenticated` roles — anyone
holding the public anon key can read or modify every row.

**Not remediated here, deliberately.** Enabling RLS without first defining
policies blocks all access and would take that application down. This needs
per-table policy decisions before any `ALTER` runs. It is outside this repo's
scope but is the highest-severity finding in the audit and should be routed
to whoever owns that project.

---

## Recommended disposition

Nothing below has been executed. Presented for approval.

### Retire — non-functional, superseded, or misleading

| Path | Rationale |
|---|---|
| `src/02_ml_pipeline/` | Stub classifier; wrong model family; target table never existed |
| `src/03_api_service/` | Never deployed; no consumer; superseded by `events_near` |
| `notebooks/module2_seismic/` | Exploration for a pipeline being retired |
| `config_vibration.yaml` | Config for retired modules |
| `requirements-ml.txt` | Deps for retired modules |
| `data/schema/02_vibration_intelligence.sql` | Never applied |
| `data/schema/pending_terrawatchapp_0049_*.sql` | Written for TerraWatch; never applied; consumer never built |
| `docs/MODULE2_ARCHITECTURE.md` | Describes a system that does not exist |
| `docs/API_CONTRACT_MODULE2.md` | Contract for an API with no server and no client |

### Retain

| Path | Rationale |
|---|---|
| `src/01_data_ingestion/` | 623 lines of working fetch/parse/retry logic + 340 lines of tests. Superseded operationally, but the NOAA station handling and CSV parsing are a useful reference if TerraWatch's ingestion needs hardening. Retain as reference; do not resume development. |
| `docs/ARCHITECTURE.md` | The source design TerraWatch implemented. Historically important. Should gain a header noting where each component now lives. |
| `README.md` | Needs a status correction (see below) |
| `data/schema/ddl.sql` | Reference for the original data model |

### Correct

- **`CLAUDE.md`** — currently describes Module 2 as an operating system with
  a live table and a Railway deployment. Every one of those claims is false.
  It should be rewritten to describe the repo's real state, or removed with
  the module it documents.
- **`README.md`** — the build log marks "Phase 1: NOAA data ingestion +
  PostgreSQL schema" complete. The schema was never applied and the
  ingestion has no database to write to. Phases 2–5 were built in
  TerraWatch, not here.

---

## Recommended sequencing

1. **Approve dispositions above.** Retirement is a single mechanical commit
   once agreed.
2. **Correct `CLAUDE.md` and `README.md`** so the next session — human or
   agent — is not misled the way this one initially was. This is the highest
   value-per-effort item in the audit: the false documentation is what makes
   the repo expensive to re-enter.
3. **Route the RLS finding** to the owner of the content-studio project.
4. **Define the research-dataset API contract** before consuming it. That
   contract belongs here (this repo's remaining useful role is specification),
   while implementation belongs in TerraWatch.
5. **Location-browsing feature and ingestion cadence** — deferred. Findings
   6a and 6b are recorded above for whenever that work is picked up.

---

## Working-split recommendation

Split by **repository, not by layer**:

- **This repo** — audit follow-through, doc correction, retirement. Small,
  finite, completable in a single session.
- **TerraWatch** — a dedicated session owning **both** UI and backend
  (migrations + edge functions) together.

Two concrete reasons TerraWatch needs its own session:

1. **Access.** This session holds read-only git access to
   `terrawatchapp-beta`. UI development requires push. This alone is
   blocking.
2. **Migration serialization.** TerraWatch's migrations are sequentially
   numbered against one Supabase project and deployed by CI on push. Two
   sessions writing migrations concurrently will collide on numbering and
   race the deploy workflow. One owner per database.

Splitting TerraWatch's UI from its backend across two sessions is the one
arrangement to avoid — the UI reads RPCs that the backend session would be
changing underneath it.

---

## Summary

This repo holds ~2,000 lines of Python. Roughly 960 of those (the Module 2
pipeline and API service) implement a system that has never run and, because
of the model mismatch in Finding 3, could not run as designed. The remaining
~1,060 lines work correctly but address a problem TerraWatch has since solved
in production.

The repo's durable value is its **design work** — the architecture document
whose formulas TerraWatch implemented directly. Its liability is documentation
that asserts a running system where none exists, which cost real time to
disprove at the start of this session and would cost it again for anyone
returning cold.

The recommendation is to retire the non-functional modules, correct the
documentation to match reality, and consolidate active development in
TerraWatch.
