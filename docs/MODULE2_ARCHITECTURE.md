# Module 2 (Seismic/Vibration Intelligence) — Architecture

**Status:** Phase 1. Schema is live on the real database. Pipeline and API
service are built but not yet run/deployed. A dedicated repo split is in
progress — this doc will move there once it exists; see "Repo topology"
below for the current split of responsibility.

This is a standalone doc rather than a section added to `docs/ARCHITECTURE.md`
— deliberately, to honor the constraint that existing files/setup in this
repo aren't modified as part of this work. `docs/ARCHITECTURE.md` describes a
separate, earlier initiative (5 insurance use cases: flash flood, seismic
precursor via catalog frequency, parametric trigger, competitive
underwriting, claims validation). Module 2 is a parallel effort, not a
continuation of that roadmap.

---

## Signal path

```
STEAD / INSTANCE (public, CC BY 4.0)
        v  SeisBench  [runs on: your machine/notebook — needs real network access]
Bronze  (data/module2_vibration/bronze/, .gitignored — raw samples)
        v  bandpass filter, normalize, window
Silver  (data/module2_vibration/silver/)
        v  label, group by scenario_family_id, split train/val/test
Gold    (data/module2_vibration/gold/)
        v  pretrained PhaseNet, per-class eval
Model registry (models/registry/<name>/metadata.json)   [local metadata, separate from the DB table below]
        v
Replay pipeline (src/02_ml_pipeline/replay_pipeline.py, idempotent upsert)
        v
vibration_classified_events (Supabase Postgres, terrawatchapp's project)  [LIVE — schema applied]
  + one seed row in the existing model_registry table (slug: seismic-vibration-ground)
        v
FastAPI service (src/03_api_service/, GET /events)  [BUILT — not yet deployed]
        v
terrawatchapp-beta dashboard (hyperlocalwatch.com) — separate repo, separate session, not started for Module 2
```

---

## Database — the one piece that's actually live

The target database was corrected mid-build: earlier drafts of this doc
assumed a dedicated Supabase project for this repo. It's actually
**terrawatchapp's own Supabase project** — the same one backing
`terrawatchapp-beta` — chosen so Module 2 slots into that app's existing
conventions instead of standing up parallel infrastructure.

- **New table**: `vibration_classified_events` — dedicated, purpose-built
  (typed `event_type`, `abstain`, `requires_human_review`,
  `scenario_family_id`, full data lineage). Deliberately *not* folded into
  the existing generic `model_inference_log` table, even though that table
  covers similar ground for other models (`pipeline-detection`, `oil-spill`,
  `seismic-insar`) — kept separate so Module 2 doesn't collapse into a shape
  built for other models' needs.
- **Catalog entry**: also seeded one row into the existing `model_registry`
  table (`slug: seismic-vibration-ground`, `status: demo`) so Module 2 shows
  up in the already-live `/ai-models` hub UI for free. Naming deliberately
  distinct from the existing `seismic-insar` model — that one is satellite
  InSAR deformation, a different modality entirely.
- **Migration file**: `data/schema/pending_terrawatchapp_0049_vibration_classified_events.sql`
  in this repo — applied manually via the Supabase SQL Editor (see
  Troubleshooting below for why), verified live by querying `model_registry`
  back afterward. Once the repo split happens, this becomes
  `terrawatchapp-beta/supabase/migrations/0049_...` for real, following that
  repo's own numbering.
- **RLS**: enabled, public-select policy, writes reserved for the service
  role / pooler credential — matches every other table in that project.

---

## Hosting

- **Pipeline/notebooks**: run locally or wherever Jupyter runs with full
  network access. Not deployable infra.
- **API service**: Railway (git-push deploy). Independent of the Vultr box
  running `datasnake-fastapi-router` / `datasnake-sensor-data` — those stay
  reference-only, not a target for Module 2.
- **Database**: Supabase Postgres, terrawatchapp's project (see above).
  Connect via the **transaction pooler** (port 6543), not the direct host
  (port 5432) — see Troubleshooting.

---

## Repo topology

Module 2's code currently lives inside `datasnake-weather-intelligence`,
alongside the unrelated NOAA/USGS ingestion pipeline it was built next to.
**A dedicated repo split is in progress** — `src/02_ml_pipeline/`,
`src/03_api_service/`, `notebooks/module2_seismic/`, `config_vibration.yaml`,
`requirements-ml.txt`, and the Module-2-specific docs move wholesale into a
new repo (fresh copy, no history carried over — internal layout stays
identical so path-dependent code keeps resolving correctly). Railway then
points at that new repo directly, root directory `src/03_api_service`.
`datasnake-weather-intelligence` goes back to being ingestion-only once that
lands.

---

## Pluggable-module principle (for Module 3/4, later)

`src/03_api_service/app/routers/events.py` has no seismic-specific logic —
just `GET /events`, `GET /events/{id}` reading a governance-shaped row.
Seismic-specific code lives entirely under `app/modules/seismic/`. A future
module (coastal visual, infrastructure condition) should be able to write
into its own table and reuse the same route shape without touching
`events.py`, provided its output conforms to the same governance fields
(`evidence`, `confidence`, `abstain`, `requires_human_review`,
`scenario_family_id`).

---

## Troubleshooting log

- **Direct Postgres host resolves IPv6-only.** `db.<ref>.supabase.co:5432`
  has no IPv4 address unless the project has the IPv4 add-on. Use the
  **transaction pooler** host instead (`aws-<n>-<region>.pooler.supabase.com:6543`
  — Dashboard → Connect → Transaction pooler tab). Same fix this repo's
  `.env.example` already anticipated with `DATABASE_POOLER_URL`.
- **Raw-TCP database connections don't work from a locked-down build
  sandbox** — confirmed against the sandbox's own documented network policy,
  not a bug. No connection string fixes it; the pipeline has to run from a
  real machine, and the API service is only reachable once actually
  deployed (Railway has normal outbound access).
- **Verify which project a connection string actually points to before
  trusting it.** One shared early on turned out to be a different, unrelated
  Supabase project (a podcast/media product — tables like `brands`,
  `voice_clones`, no `model_registry`). Caught via
  `select tablename from pg_tables where schemaname = 'public'` before
  anything was written. Worth re-running any time credentials change hands.

---

## Known Phase 1 limitations

- `vehicle_human` event type has no labeled training data yet (STEAD/INSTANCE
  don't cover it) — see `src/02_ml_pipeline/gold_label_split.py`.
- No live sensor — `replay_pipeline.py` replays public gold-layer data
  instead.
- `datasnake-fastapi-router`'s `datasnake.io/datapreview` outage is a
  separate, pre-existing issue, explicitly out of scope here.
