"""Gold layer: label, group into scenario families, and split train/val/test.

Gold = model-ready. One row per window, with a label, a scenario_family_id,
and a split assignment — the last clean tabular stage before model training.

IMPORTANT LIMITATION, stated plainly rather than hidden: STEAD and INSTANCE
only give us two of the four target classes directly —
  - `trace_category == "earthquake_local"` -> "seismic"
  - `trace_category == "noise"`            -> mapped to "environmental" here
    as a placeholder negative class, NOT a validated environmental-noise
    label. It's non-seismic background noise, not confirmed vehicle/human
    or genuine environmental activity.
The "vehicle_human" class has NO labeled source in either dataset. Per the
Module 2 plan doc itself ("STEAD's labels plus any public non-seismic
vibration data for the negative classes"), a separate public vehicle/human
vibration dataset needs to be sourced and merged before that class has any
real training signal. Until then, the baseline model in Slice 6 should be
evaluated as effectively a 3-class problem (seismic / environmental /
unknown-by-abstention) with vehicle_human called out as not-yet-trainable,
not silently reported as if it were.
"""

import argparse
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config_vibration.yaml"
SILVER_DIR = ROOT / "data" / "module2_vibration" / "silver"
GOLD_DIR = ROOT / "data" / "module2_vibration" / "gold"

TRACE_CATEGORY_TO_EVENT_TYPE = {
    "earthquake_local": "seismic",
    "noise": "environmental",  # placeholder negative class, see module docstring
}


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def assign_scenario_family(bronze_meta: pd.DataFrame) -> pd.Series:
    """Group by the originating earthquake/source event so multiple stations
    recording the SAME event are treated as one family — never split across
    train/val/test independently (that would be leakage: the model could
    memorize a specific event's waveform character from train and get an
    unfair advantage recognizing it again in test).

    STEAD/INSTANCE metadata carries a `source_id` column for real earthquake
    traces. Noise traces have no shared source event, so each is its own
    family (using the trace's own index).
    """
    if "source_id" in bronze_meta.columns:
        return bronze_meta["source_id"].fillna(bronze_meta.index.to_series().astype(str))
    return bronze_meta.index.to_series().astype(str)


def split_by_family(families: pd.Series, train_frac: float, val_frac: float, seed: int) -> pd.Series:
    """Assign train/val/test at the family level — every window belonging to
    the same family gets the same split. Uses a hash of the family id so the
    split is deterministic and reproducible across reruns (not a random
    shuffle that changes every invocation)."""
    unique_families = sorted(families.unique())
    rng_frac = pd.util.hash_array(pd.array(unique_families, dtype="string")) % 1000 / 1000.0
    family_split = {}
    for fam, frac in zip(unique_families, rng_frac):
        if frac < train_frac:
            family_split[fam] = "train"
        elif frac < train_frac + val_frac:
            family_split[fam] = "val"
        else:
            family_split[fam] = "test"
    return families.map(family_split)


def run(dataset: str) -> Path:
    cfg = load_config()
    bronze_meta_path = ROOT / "data" / "module2_vibration" / "bronze" / f"{dataset}_sample_metadata.csv"
    silver_meta_path = SILVER_DIR / f"{dataset}_silver_metadata.csv"
    if not bronze_meta_path.exists() or not silver_meta_path.exists():
        raise FileNotFoundError(f"Run bronze_ingest.py and silver_clean.py --dataset {dataset} first")

    bronze_meta = pd.read_csv(bronze_meta_path)
    silver_meta = pd.read_csv(silver_meta_path)

    bronze_meta["scenario_family_id"] = f"{dataset}_" + assign_scenario_family(bronze_meta).astype(str)
    bronze_meta["event_type"] = bronze_meta.get("trace_category", pd.Series(dtype=str)).map(
        TRACE_CATEGORY_TO_EVENT_TYPE
    ).fillna("unknown")

    split_cfg = cfg["split"]
    family_to_split = dict(
        zip(
            bronze_meta.index.astype(str),
            split_by_family(
                bronze_meta["scenario_family_id"],
                split_cfg["train_frac"],
                split_cfg["val_frac"],
                split_cfg["random_seed"],
            ),
        )
    )

    gold_rows = silver_meta.merge(
        bronze_meta[["scenario_family_id", "event_type"]],
        left_on="source_idx",
        right_index=True,
        how="left",
    )
    gold_rows["split"] = gold_rows["source_idx"].astype(str).map(family_to_split)
    gold_rows["source_dataset"] = cfg["datasets"][dataset]["name"]

    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    out_path = GOLD_DIR / f"{dataset}_gold.csv"
    gold_rows.to_csv(out_path, index=False)

    print(f"{dataset}: {len(gold_rows)} gold rows written -> {out_path}")
    print(gold_rows["split"].value_counts())
    print(gold_rows["event_type"].value_counts())
    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gold-layer label/split for Module 2")
    parser.add_argument("--dataset", choices=["stead", "instance"], required=True)
    args = parser.parse_args()
    run(args.dataset)
