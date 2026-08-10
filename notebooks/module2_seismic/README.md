# Module 2: Seismic/Vibration Intelligence — Notebooks

Jupyter-based ML prototyping for the seismic/vibration event classifier,
following the bronze/silver/gold layering used across this project. Each
notebook is a thin wrapper over the corresponding script in
`src/02_ml_pipeline/` — the actual logic lives in the scripts (inspectable,
testable, reusable outside a notebook), not hidden in cells.

---

## Prerequisites

1. **Full outbound network access.** These notebooks pull data from
   SeisBench's mirrors (zenodo.org / huggingface.co). They will NOT run
   inside a network-restricted sandbox — run them on your own machine,
   Colab, or wherever you normally run Jupyter.
2. `pip install -r requirements-ml.txt` (separate from the root
   `requirements.txt` — see that file's header comment for why).
3. `.env` with `DATABASE_URL` set (only needed from `03_gold_label_split.ipynb`
   onward, if you want to write real rows via `replay_pipeline.py`).

---

## Running, in order

```bash
jupyter notebook notebooks/module2_seismic/
```

1. `00_dataset_licensing_check.ipynb` — records the verified STEAD/INSTANCE
   license terms. Read this first; it's the hard gate the rest depends on.
2. `01_bronze_ingest.ipynb` — pulls a small sample via SeisBench, writes a
   versioned manifest to `data/module2_vibration/manifests/`.
3. `02_silver_clean_window.ipynb` — bandpass filter, normalize, window.
4. `03_gold_label_split.ipynb` — labels, groups by `scenario_family_id`,
   splits train/val/test at the family level (never per-record, to prevent
   leakage). Runs the same pipeline validation checks as
   `src/02_ml_pipeline/tests/` against the real output.
5. `04_baseline_eval_phasenet_eqtransformer.ipynb` — runs pretrained
   PhaseNet, reports per-class precision/recall/F1, false-positive rate,
   and confidence calibration. Writes to `models/registry/`.

---

## Known limitation (read before trusting the eval numbers)

STEAD/INSTANCE only supply two of the four target classes directly:
`earthquake_local` → `seismic`, `noise` → a placeholder `environmental`
negative class. **`vehicle_human` has no labeled source in either dataset.**
Per the Module 2 plan doc, that class needs a separate public
vehicle/human vibration dataset merged in before it's meaningfully
trainable — until then, treat the baseline eval as a 3-class result, not a
4-class one. See the docstring in `src/02_ml_pipeline/gold_label_split.py`
for the full detail.

---

## Verification queries

```python
import pandas as pd
gold = pd.read_csv("data/module2_vibration/gold/stead_gold.csv")
gold["event_type"].value_counts()
gold["split"].value_counts()
```
