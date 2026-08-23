# DataSnake Weather Intelligence — Claude Code Context

Quick-reference for Claude Code sessions working in this repo.

---

## What this project is

Real-time insurance risk signals from public meteorological data (NOAA, USGS,
FEMA). Two parallel efforts share this repo and its Postgres database:

- **Original pipeline** (`src/01_data_ingestion/`, `docs/ARCHITECTURE.md`) —
  NOAA + USGS ingestion, flash flood / seismic precursor / coastal wind risk
  scoring, 5 insurance use cases. Phase 1 complete.
- **Module 2: Vibration Intelligence** (`src/02_ml_pipeline/`,
  `src/03_api_service/`, `docs/MODULE2_ARCHITECTURE.md`) — ML-classified
  waveform events exposed via FastAPI, deployed to Railway, consumed by the
  `terrawatchapp-beta` dashboard at `hyperlocalwatch.com`.

These are additive, not integrated. Do not conflate the original pipeline's
`seismic_events` table (raw USGS catalog) with Module 2's
`vibration_classified_events` table (ML-classified sensor waveforms). See
`data/schema/02_vibration_intelligence.sql` and `docs/MODULE2_ARCHITECTURE.md`
for why they're deliberately kept separate.

---

## Tech stack

| Layer | Technology |
|---|---|
| Language | Python 3.10+ |
| Data ingestion | `requests`, `pandas`, `tenacity` (retry), `tqdm` |
| Database | PostgreSQL 14+ + PostGIS — hosted on **Supabase** |
| DB access | `psycopg2-binary`, `SQLAlchemy`, `GeoAlchemy2`, `shapely` |
| ML pipeline | `torch`, `seisbench`, `obspy`, `scipy` |
| API service | `fastapi`, `uvicorn`, `pydantic` |
| API deployment | **Railway** (Nixpacks, git-push deploy, `railway.json`) |
| Notebooks | Jupyter (Module 2 exploration: `notebooks/module2_seismic/`) |
| Config | `config.yaml` (original pipeline), `config_vibration.yaml` (Module 2) |
| Secrets | `.env` (never committed) — see `.env.example` |
| Testing | `pytest` |

### Key separation: two requirements files

- `requirements.txt` — original pipeline only. No ML deps.
- `requirements-ml.txt` — Module 2 additions (`torch`, `seisbench`, `obspy`).
  Install this when working on `src/02_ml_pipeline/` or `src/03_api_service/`.

Never add ML deps to `requirements.txt`; they'd break the ingestion scripts'
install on machines without CUDA.

---

## Phased scope

Both the original pipeline and Module 2 follow the same phased model:

**Phase 1 (current):** DataSnake is the sole user and admin.
- Single static API token (`MODULE2_API_TOKEN` header: `x-api-token`).
- No multi-tenancy, no per-client auth.
- Data is replayed public datasets (STEAD/INSTANCE), not a live sensor feed.
  `sensor_id` values look like `replay:stead` / `replay:instance`.
- `abstain: true` rows dominate until a real model is wired into
  `replay_pipeline.py`'s `classify_window()`.

**Phase 2 (not yet built):** Per-client auth, live sensors, multi-tenancy.
Do not design or build Phase 2 features unless explicitly scoped. The
`requires_human_review` and `abstain` governance fields are forward-looking
hooks — they exist in the schema now so the table shape doesn't need to
change when Phase 2 adds human-review workflows.

---

## Pluggable-module principle

`src/03_api_service/app/routers/events.py` is **module-agnostic** — it reads
from a governance-shaped row and exposes `GET /events` / `GET /events/{id}`
with no knowledge of what produced those rows.

All seismic-specific logic lives under `app/modules/seismic/`:
- `classify.py` — the only file that imports SeisBench/PyTorch
- `schemas.py` — seismic-specific Pydantic models

A future Module 3 (e.g. coastal visual) or Module 4 (infrastructure
condition) should:
1. Write into its own table (not `vibration_classified_events`).
2. Populate the same governance fields: `evidence`, `confidence`, `abstain`,
   `requires_human_review`, `scenario_family_id`.
3. Live entirely under `app/modules/<module_name>/`.
4. Reuse `routers/events.py` without modifying it.

Do not add module-specific logic to `events.py`.

---

## Project structure

```
src/
  01_data_ingestion/       # NOAA + USGS ingestion scripts (Phase 1, complete)
  02_ml_pipeline/          # Module 2: bronze→silver→gold ETL + model registry
  03_api_service/          # Module 2: FastAPI service (Railway deploy)
    app/
      main.py              # app factory, CORS, health check
      core/                # config, db, auth
      routers/events.py    # MODULE-AGNOSTIC route handler
      modules/seismic/     # seismic-specific logic (classify, schemas)

data/
  schema/
    ddl.sql                           # original pipeline schema
    02_vibration_intelligence.sql     # Module 2 tables
  module2_vibration/                  # bronze/silver/gold data layers (.gitignored)

docs/
  ARCHITECTURE.md           # original pipeline: DB schema, formulas, tech stack
  MODULE2_ARCHITECTURE.md   # Module 2: data flow, hosting, pluggable-module principle
  API_CONTRACT_MODULE2.md   # handoff contract for terrawatchapp-beta frontend

notebooks/module2_seismic/  # 00–04 exploration notebooks (require full network access)

config.yaml                 # original pipeline config (DB, NOAA, USGS, risk thresholds)
config_vibration.yaml       # Module 2 config (ML datasets, model, API CORS)
.env.example                # required env vars template
```

---

## Common commands

```bash
# Install original pipeline deps
pip install -r requirements.txt

# Install Module 2 deps (includes ML libs)
pip install -r requirements-ml.txt

# Run NOAA ingestion
python src/01_data_ingestion/noaa_ingestion.py

# Run Module 2 ML pipeline (bronze → silver → gold)
python src/02_ml_pipeline/bronze_ingest.py
python src/02_ml_pipeline/silver_clean.py
python src/02_ml_pipeline/gold_label_split.py

# Replay pipeline (writes to vibration_classified_events)
python src/02_ml_pipeline/replay_pipeline.py

# Run FastAPI service locally
cd src/03_api_service
uvicorn app.main:app --reload --port 8000
curl -H "x-api-token: $MODULE2_API_TOKEN" http://localhost:8000/events

# Run tests
pytest src/01_data_ingestion/
pytest src/02_ml_pipeline/tests/
```

---

## Environment variables

See `.env.example` for the full list. Minimum required per context:

| Context | Required vars |
|---|---|
| Original pipeline | `DATABASE_URL` or `DB_HOST`/`DB_PORT`/`DB_NAME`/`DB_USER`/`DB_PASSWORD` |
| Module 2 pipeline | Same DB vars |
| Module 2 API (local) | `DATABASE_POOLER_URL`, `MODULE2_API_TOKEN` |
| Module 2 API (Railway) | Set in Railway dashboard — not in `.env` |

---

## Key constraints

- **Do not modify existing files** when adding Module 2 features — use separate
  files, config, and deps. This is the explicit additive-only constraint from
  the Module 2 architecture decision.
- **Do not touch `seismic_events`** from Module 2 code — that table belongs to
  the original pipeline.
- **Do not add seismic logic to `routers/events.py`** — see pluggable-module
  principle above.
- **Do not commit `.env`** — it's in `.gitignore`.
- **Do not add ML deps to `requirements.txt`** — use `requirements-ml.txt`.
