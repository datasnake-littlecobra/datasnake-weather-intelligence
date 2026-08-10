# Module 2: Seismic/Vibration Intelligence — ML Pipeline

Bronze/silver/gold pipeline as inspectable, testable scripts. The notebooks
in `notebooks/module2_seismic/` are thin wrappers over these — run the
scripts directly for automation, or through the notebooks for EDA/visual
sanity checks.

---

## Files

| File | Purpose |
|---|---|
| `manifest.py` | Versioned dataset manifest read/write — dataset lineage/reproducibility |
| `bronze_ingest.py` | Pull a small STEAD/INSTANCE sample via SeisBench |
| `silver_clean.py` | Bandpass filter, normalize, window |
| `gold_label_split.py` | Label, group by `scenario_family_id`, split train/val/test |
| `validate.py` | Pipeline-level checks: schema, split leakage, duplicates |
| `model_registry.py` | Small metadata.json per trained model version (code sha, data version, eval metrics) |
| `replay_pipeline.py` | Idempotent: classifies gold-layer windows, upserts into `vibration_classified_events` |
| `tests/` | pytest suite for `validate.py`, runs without network access |

---

## Setup

```bash
pip install -r requirements-ml.txt   # separate from root requirements.txt
```

## Running

```bash
python src/02_ml_pipeline/bronze_ingest.py --dataset stead      # needs network access
python src/02_ml_pipeline/silver_clean.py --dataset stead
python src/02_ml_pipeline/gold_label_split.py --dataset stead
python src/02_ml_pipeline/replay_pipeline.py --dataset stead    # needs DATABASE_URL
```

## Tests

```bash
pytest src/02_ml_pipeline/tests/ -v
```

These run against synthetic fixtures, not real STEAD/INSTANCE data, so they
work without network access. `test_split_leakage.py` includes a test that
deliberately breaks a split and asserts the check catches it — not just that
the check exists.

## Isolation from the existing ingestion pipeline

This directory, `requirements-ml.txt`, and `config_vibration.yaml` are
entirely additive — nothing in `src/01_data_ingestion/`, `requirements.txt`,
or `config.yaml` was modified to build this. `vibration_classified_events`
(this module's output table) is a separate table from the existing
`seismic_events` (raw USGS catalog) — see the header comment in
`data/schema/02_vibration_intelligence.sql` for why they're different
concepts despite the name similarity.
