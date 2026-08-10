import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from validate import check_split_leakage


def test_clean_split_has_no_leakage():
    df = pd.DataFrame(
        {
            "window_id": ["a1", "a2", "b1", "c1"],
            "scenario_family_id": ["fam_a", "fam_a", "fam_b", "fam_c"],
            "split": ["train", "train", "val", "test"],
        }
    )
    assert check_split_leakage(df) == []


def test_leakage_is_caught_when_a_family_spans_two_splits():
    """Deliberately break the split: fam_a has one window in train and one
    in test. This is exactly the failure mode the leakage check exists to
    catch (a model could memorize fam_a's waveform in train and get an
    unfair advantage recognizing it again in test)."""
    df = pd.DataFrame(
        {
            "window_id": ["a1", "a2", "b1", "c1"],
            "scenario_family_id": ["fam_a", "fam_a", "fam_b", "fam_c"],
            "split": ["train", "test", "val", "test"],  # fam_a leaks: train AND test
        }
    )
    leaked = check_split_leakage(df)
    assert leaked == ["fam_a"]


def test_leakage_across_three_splits_reports_the_family_once():
    df = pd.DataFrame(
        {
            "window_id": ["a1", "a2", "a3"],
            "scenario_family_id": ["fam_a", "fam_a", "fam_a"],
            "split": ["train", "val", "test"],
        }
    )
    assert check_split_leakage(df) == ["fam_a"]
