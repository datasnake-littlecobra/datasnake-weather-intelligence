import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from validate import validate_schema


def _valid_gold_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "window_id": ["stead_0_0", "stead_0_1", "stead_1_0"],
            "source_idx": [0, 0, 1],
            "window_index": [0, 1, 0],
            "scenario_family_id": ["fam_a", "fam_a", "fam_b"],
            "event_type": ["seismic", "seismic", "environmental"],
            "split": ["train", "train", "val"],
            "source_dataset": ["STEAD", "STEAD", "STEAD"],
        }
    )


def test_valid_schema_passes():
    assert validate_schema(_valid_gold_df()) == []


def test_missing_column_detected():
    df = _valid_gold_df().drop(columns=["scenario_family_id"])
    problems = validate_schema(df)
    assert any("scenario_family_id" in p for p in problems)


def test_invalid_event_type_detected():
    df = _valid_gold_df()
    df.loc[0, "event_type"] = "definitely_not_a_real_type"
    problems = validate_schema(df)
    assert any("Invalid event_type" in p for p in problems)


def test_invalid_split_detected():
    df = _valid_gold_df()
    df.loc[0, "split"] = "training"  # wrong spelling, not in VALID_SPLITS
    problems = validate_schema(df)
    assert any("Invalid split" in p for p in problems)


def test_duplicate_window_id_detected():
    df = _valid_gold_df()
    df.loc[2, "window_id"] = "stead_0_0"  # collides with row 0
    problems = validate_schema(df)
    assert any("Duplicate window_id" in p for p in problems)
