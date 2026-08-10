# Module 2 (Seismic/Vibration Intelligence) — Architecture

**Status:** Phase 1 (DataSnake sole user/admin, public replayed data, no live
sensor yet — see CLAUDE.md's phased scope)

This is a standalone doc rather than a section added to `docs/ARCHITECTURE.md`
— deliberately, to honor the constraint that existing files/setup in this
repo aren't modified as part of this work. `docs/ARCHITECTURE.md` describes a
separate, earlier initiative (5 insurance use cases: flash flood, seismic
precursor via catalog frequency, parametric trigger, competitive
underwriting, claims validation). Module 2 is a parallel effort in the same
repo, not a continuation of that roadmap — this doc exists so the connection
(and the deliberate separation) is written down somewhere, without touching
that file.

---

## Relationship to the existing weather-intelligence pipeline

Shares this repo and its Postgres database, nothing else:

- **Different tables.** The existing `seismic_events` table (raw USGS
  earthquake catalog) is untouched. Module 2 writes to
  `vibration_classified_events` (ML-classified sensor waveform events) — see
  `data/schema/02_vibration_intelligence.sql` for why these are different
  concepts despite the similar name.
- **Different terminology, deliberately.** The existing pipeline's "seismic
  precursor" signal (`seismic_precursor_risk()`, catalog-frequency based) is
  unrelated to Module 2's waveform classification. Module 2 code/docs use
  "vibration" specifically to avoid the two being confused.
- **Different config file.** `config_vibration.yaml`, not `config.yaml` —
  isolated so Module 2 config changes can never break the existing NOAA/USGS
  ingestion config.
- **Different dependencies.** `requirements-ml.txt`, not `requirements.txt`
  — keeps `torch`/`seisbench` out of the ingestion scripts' install.

---

## Data flow

```
STEAD / INSTANCE (public, CC BY 4.0)
        v  SeisBench
Bronze  (data/module2_vibration/bronze/, .gitignored — raw samples)
        v  bandpass filter, normalize, window
Silver  (data/module2_vibration/silver/)
        v  label, group by scenario_family_id, split train/val/test
Gold    (data/module2_vibration/gold/)
        v  pretrained PhaseNet, per-class eval
Model registry (models/registry/<name>/metadata.json)
        v
Replay pipeline (src/02_ml_pipeline/replay_pipeline.py, idempotent upsert)
        v
vibration_classified_events (Supabase Postgres)
        v
FastAPI service (src/03_api_service/, GET /events)
        v
terrawatchapp-beta dashboard (hyperlocalwatch.com) — built in a separate session
```

---

## Hosting (deliberately independent of Vultr)

- **Pipeline/notebooks:** run locally or wherever Jupyter runs with full
  network access — not deployable infra, no hosting decision needed.
- **API service:** Railway (git-push deploy, phone-manageable dashboard).
  Confirmed independent of the Vultr box running `datasnake-fastapi-router`
  and `datasnake-sensor-data` — those are reference-only per the current
  plan, not a target for Module 2.
- **Database:** Supabase Postgres — same project this repo's `.env.example`
  already points at.

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

## Known Phase 1 limitations

- `vehicle_human` event type has no labeled training data yet (STEAD/INSTANCE
  don't cover it) — see `src/02_ml_pipeline/gold_label_split.py`.
- No live sensor — `replay_pipeline.py` replays public gold-layer data
  instead.
- `datasnake-fastapi-router`'s `datasnake.io/datapreview` outage is a
  separate, pre-existing issue, explicitly out of scope here.
