"""Versioned dataset manifest helper for Module 2 (Seismic/Vibration Intelligence).

A manifest records exactly what raw data a pipeline run was built from —
dataset name, version, source, checksum, sample count, license, and the
code commit that pulled it — so any later model or gold-layer table can be
traced back to the precise data it came from (data lineage / reproducibility
requirement). Manifests are small JSON files and ARE committed to git,
unlike the raw waveform data itself (see data/module2_vibration/.gitignore).
"""

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

MANIFEST_DIR = Path(__file__).resolve().parents[2] / "data" / "module2_vibration" / "manifests"


def _current_git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True
        ).strip()
    except Exception:
        return "unknown"


def checksum_file(path: Path) -> str:
    """SHA-256 of a file's contents, for verifying a pull is byte-identical later."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def checksum_files(paths: list[Path]) -> str:
    """Combined checksum over multiple files (order-independent), for a sample pull
    spread across several waveform files."""
    h = hashlib.sha256()
    for p in sorted(paths, key=lambda x: x.name):
        h.update(checksum_file(p).encode())
    return h.hexdigest()


def write_manifest(
    dataset_name: str,
    version: str,
    source_url: str,
    checksum: str,
    sample_count: int,
    license_name: str,
) -> Path:
    """Write a versioned manifest JSON. Re-running with the same inputs produces
    the same checksum, so this is idempotent by construction — the manifest file
    itself changes only if the underlying data pull actually changed."""
    manifest = {
        "dataset_name": dataset_name,
        "version": version,
        "source_url": source_url,
        "checksum": checksum,
        "sample_count": sample_count,
        "license": license_name,
        "pulled_at": datetime.now(timezone.utc).isoformat(),
        "pipeline_code_git_sha": _current_git_sha(),
    }
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    out_path = MANIFEST_DIR / f"{dataset_name.lower()}_{version}_manifest.json"
    with open(out_path, "w") as f:
        json.dump(manifest, f, indent=2)
    return out_path


def read_manifest(dataset_name: str, version: str) -> dict:
    path = MANIFEST_DIR / f"{dataset_name.lower()}_{version}_manifest.json"
    if not path.exists():
        raise FileNotFoundError(
            f"No manifest for {dataset_name} {version} — run the bronze ingest step first."
        )
    with open(path) as f:
        return json.load(f)


def latest_version(dataset_name: str) -> str:
    """Highest version string found for a dataset among committed manifests."""
    candidates = sorted(MANIFEST_DIR.glob(f"{dataset_name.lower()}_*_manifest.json"))
    if not candidates:
        raise FileNotFoundError(f"No manifests found for {dataset_name}")
    latest = candidates[-1]
    version = latest.stem.replace(f"{dataset_name.lower()}_", "").replace("_manifest", "")
    return version
