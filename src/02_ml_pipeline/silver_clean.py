"""Silver layer: bandpass filter, normalize, and window bronze-layer waveforms.

Silver = cleaned, filtered, windowed — still one row per source trace, not
yet labeled or split (that's gold_label_split.py). Kept as a distinct,
inspectable stage rather than folded into bronze or gold, per the project's
bronze/silver/gold layering requirement.
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from scipy.signal import butter, sosfiltfilt

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config_vibration.yaml"
BRONZE_DIR = ROOT / "data" / "module2_vibration" / "bronze"
SILVER_DIR = ROOT / "data" / "module2_vibration" / "silver"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def bandpass_filter(trace: np.ndarray, sampling_rate_hz: float, low_hz: float = 1.0, high_hz: float = 45.0) -> np.ndarray:
    """Strip frequencies outside the seismic band. Butterworth, zero-phase
    (filtfilt) so the filter doesn't shift event timing."""
    nyquist = sampling_rate_hz / 2
    sos = butter(4, [low_hz / nyquist, high_hz / nyquist], btype="bandpass", output="sos")
    return sosfiltfilt(sos, trace, axis=-1)


def normalize(trace: np.ndarray) -> np.ndarray:
    """Amplitude-normalize to unit max-abs, per trace. Avoids divide-by-zero
    on a dead/flat channel."""
    peak = np.max(np.abs(trace))
    if peak == 0:
        return trace
    return trace / peak


def window_trace(trace: np.ndarray, sampling_rate_hz: float, window_length_sec: float) -> list[np.ndarray]:
    """Segment a (possibly longer) trace into fixed-length, non-overlapping windows.
    Drops a trailing partial window rather than zero-padding it, to avoid
    training the model on artificial silence."""
    window_len = int(window_length_sec * sampling_rate_hz)
    n_windows = trace.shape[-1] // window_len
    return [trace[..., i * window_len:(i + 1) * window_len] for i in range(n_windows)]


def process_trace(trace: np.ndarray, sampling_rate_hz: float, window_length_sec: float) -> list[np.ndarray]:
    filtered = bandpass_filter(trace, sampling_rate_hz)
    normalized = normalize(filtered)
    return window_trace(normalized, sampling_rate_hz, window_length_sec)


def run(dataset: str) -> Path:
    """Reads bronze-layer sample metadata, filters/normalizes/windows each trace,
    writes one row per window to the silver layer.

    Requires the actual waveform arrays behind the bronze-layer sample (not just
    the metadata CSV bronze_ingest.py writes) — load them via the same SeisBench
    dataset object bronze_ingest.py used, keyed by the metadata's trace index.
    """
    cfg = load_config()
    bronze_meta_path = BRONZE_DIR / f"{dataset}_sample_metadata.csv"
    if not bronze_meta_path.exists():
        raise FileNotFoundError(f"Run bronze_ingest.py --dataset {dataset} first")

    meta = pd.read_csv(bronze_meta_path)
    sampling_rate_hz = cfg["model"]["sampling_rate_hz"]
    window_length_sec = cfg["model"]["window_length_sec"]

    SILVER_DIR.mkdir(parents=True, exist_ok=True)
    silver_rows = []
    windows_out = []

    import seisbench.data as sbd

    sb_dataset_cls = sbd.STEAD if dataset == "stead" else sbd.InstanceCountsCombined
    sb_data = sb_dataset_cls(sampling_rate=sampling_rate_hz, cache=str(BRONZE_DIR / f"{dataset}_cache"))

    for idx in meta.index:
        trace = sb_data.get_waveforms(idx)
        windows = process_trace(trace, sampling_rate_hz, window_length_sec)
        for w_i, window in enumerate(windows):
            window_id = f"{dataset}_{idx}_{w_i}"
            windows_out.append((window_id, window))
            silver_rows.append({"window_id": window_id, "source_idx": idx, "window_index": w_i})

    silver_meta = pd.DataFrame(silver_rows)
    meta_path = SILVER_DIR / f"{dataset}_silver_metadata.csv"
    silver_meta.to_csv(meta_path, index=False)

    arrays_path = SILVER_DIR / f"{dataset}_silver_windows.npz"
    np.savez_compressed(arrays_path, **{wid: w for wid, w in windows_out})

    print(f"{dataset}: {len(meta)} source traces -> {len(silver_rows)} silver windows")
    print(f"Metadata -> {meta_path}")
    print(f"Windows -> {arrays_path}")
    return meta_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Silver-layer clean/window for Module 2")
    parser.add_argument("--dataset", choices=["stead", "instance"], required=True)
    args = parser.parse_args()
    run(args.dataset)
