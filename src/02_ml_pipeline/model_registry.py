"""Minimal model registry for Module 2.

Every trained model version is traceable to the data version and code
version that produced it (mirrors the sibling text-diagnostics product's
system/taxonomy/dataset/model_artifacts versioning). Weights themselves are
NOT committed to git (large binary files) — only this small metadata.json,
with a `weights_location` pointer to wherever the actual weights live
(a Railway volume, object storage, etc., decided at deploy time).
"""

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_DIR = ROOT / "models" / "registry"


def _current_git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def write_model_metadata(
    model_name: str,
    model_version: str,
    data_version: str,
    eval_metrics: dict,
    weights_location: str = "not-yet-uploaded",
) -> Path:
    metadata = {
        "model_name": model_name,
        "model_version": model_version,
        "code_git_sha": _current_git_sha(),
        "data_version": data_version,
        "eval_metrics": eval_metrics,
        "weights_location": weights_location,
        "registered_at": datetime.now(timezone.utc).isoformat(),
    }
    out_dir = REGISTRY_DIR / f"{model_name}_{model_version}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "metadata.json"
    with open(out_path, "w") as f:
        json.dump(metadata, f, indent=2)
    return out_path


def read_model_metadata(model_name: str, model_version: str) -> dict:
    path = REGISTRY_DIR / f"{model_name}_{model_version}" / "metadata.json"
    if not path.exists():
        raise FileNotFoundError(f"No registry entry for {model_name} {model_version}")
    with open(path) as f:
        return json.load(f)
