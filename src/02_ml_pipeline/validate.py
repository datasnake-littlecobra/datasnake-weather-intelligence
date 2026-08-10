"""Pipeline-level validation checks for Module 2's gold layer.

These check the PIPELINE's output, not the model — schema shape, split
leakage, and duplicate rows. Same category of check as the sibling
text-diagnostics product's propagate.py validation, per this project's
stated engineering standards.
"""

import pandas as pd

REQUIRED_GOLD_COLUMNS = {
    "window_id",
    "source_idx",
    "window_index",
    "scenario_family_id",
    "event_type",
    "split",
    "source_dataset",
}

VALID_EVENT_TYPES = {"seismic", "vehicle_human", "environmental", "unknown"}
VALID_SPLITS = {"train", "val", "test"}


def validate_schema(df: pd.DataFrame) -> list[str]:
    """Returns a list of problems found (empty list = valid)."""
    problems = []
    missing = REQUIRED_GOLD_COLUMNS - set(df.columns)
    if missing:
        problems.append(f"Missing required columns: {sorted(missing)}")

    if "event_type" in df.columns:
        bad_types = set(df["event_type"].dropna().unique()) - VALID_EVENT_TYPES
        if bad_types:
            problems.append(f"Invalid event_type values: {sorted(bad_types)}")

    if "split" in df.columns:
        bad_splits = set(df["split"].dropna().unique()) - VALID_SPLITS
        if bad_splits:
            problems.append(f"Invalid split values: {sorted(bad_splits)}")

    if "window_id" in df.columns and df["window_id"].duplicated().any():
        problems.append("Duplicate window_id values found")

    return problems


def check_split_leakage(df: pd.DataFrame, family_col: str = "scenario_family_id", split_col: str = "split") -> list[str]:
    """A family (e.g. all stations recording the same earthquake) must land
    entirely in one split. Returns the list of family ids that leak across
    more than one split (empty list = no leakage)."""
    families_per_split = df.groupby(family_col)[split_col].nunique()
    return families_per_split[families_per_split > 1].index.tolist()


def detect_duplicates(df: pd.DataFrame, key_columns: list[str] | None = None) -> pd.DataFrame:
    """Returns the duplicate rows (by key_columns, default window_id).
    Empty DataFrame = no duplicates."""
    key_columns = key_columns or ["window_id"]
    return df[df.duplicated(subset=key_columns, keep=False)]
