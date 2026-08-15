import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from validate import detect_duplicates


def test_no_duplicates_returns_empty():
    df = pd.DataFrame({"window_id": ["a", "b", "c"]})
    assert detect_duplicates(df).empty


def test_duplicate_window_id_is_returned():
    df = pd.DataFrame({"window_id": ["a", "b", "a"], "value": [1, 2, 3]})
    dups = detect_duplicates(df)
    assert len(dups) == 2
    assert set(dups["window_id"]) == {"a"}


def test_duplicate_check_respects_custom_key_columns():
    df = pd.DataFrame(
        {
            "sensor_id": ["s1", "s1", "s2"],
            "event_time": ["t1", "t1", "t1"],
            "window_id": ["w1", "w2", "w3"],  # window_id differs, but (sensor_id, event_time) collides
        }
    )
    dups = detect_duplicates(df, key_columns=["sensor_id", "event_time"])
    assert len(dups) == 2
