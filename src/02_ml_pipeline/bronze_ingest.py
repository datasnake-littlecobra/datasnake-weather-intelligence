"""Bronze layer: pull a small STEAD/INSTANCE sample via SeisBench, unmodified.

Bronze = raw, as-is data. No filtering, no windowing, no labeling here —
that's silver_clean.py and gold_label_split.py. This script's only job is
"pull a known-good sample and record exactly what was pulled" (manifest.py).

NOTE ON EXECUTION ENVIRONMENT: this script needs outbound network access to
SeisBench's data mirrors (zenodo.org / huggingface.co). It cannot run inside
a network-restricted sandbox — run it wherever notebooks normally execute
(local machine, Colab, etc.), not inside a locked-down CI/agent environment.

NOTE ON SEISBENCH API: SeisBench's exact dataset class name for INSTANCE has
changed across versions (e.g. InstanceCountsCombined / InstanceGM / InstanceNoise
in more recent releases vs. a single InstanceCounts class in older ones). Verify
the class name against `import seisbench.data as sbd; dir(sbd)` for whatever
seisbench==0.7.0 (pinned in requirements-ml.txt) actually ships, before relying
on the exact name used below.
"""

import argparse
from pathlib import Path

import yaml

import manifest

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config_vibration.yaml"
BRONZE_DIR = ROOT / "data" / "module2_vibration" / "bronze"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def pull_stead_sample(sample_size: int) -> tuple[Path, int]:
    import seisbench.data as sbd

    data = sbd.STEAD(sampling_rate=100, cache=str(BRONZE_DIR / "stead_cache"))
    sample = data.metadata.iloc[:sample_size]
    out_path = BRONZE_DIR / "stead_sample_metadata.csv"
    sample.to_csv(out_path, index=False)
    return out_path, len(sample)


def pull_instance_sample(sample_size: int) -> tuple[Path, int]:
    import seisbench.data as sbd

    # See module docstring — verify this class name against the installed
    # seisbench version before running.
    data = sbd.InstanceCountsCombined(sampling_rate=100, cache=str(BRONZE_DIR / "instance_cache"))
    sample = data.metadata.iloc[:sample_size]
    out_path = BRONZE_DIR / "instance_sample_metadata.csv"
    sample.to_csv(out_path, index=False)
    return out_path, len(sample)


def run(dataset: str) -> Path:
    cfg = load_config()["datasets"][dataset]
    BRONZE_DIR.mkdir(parents=True, exist_ok=True)

    if dataset == "stead":
        out_path, count = pull_stead_sample(cfg["sample_size"])
    elif dataset == "instance":
        out_path, count = pull_instance_sample(cfg["sample_size"])
    else:
        raise ValueError(f"Unknown dataset: {dataset}")

    checksum = manifest.checksum_file(out_path)
    manifest_path = manifest.write_manifest(
        dataset_name=cfg["name"],
        version="v1",
        source_url=cfg["source"],
        checksum=checksum,
        sample_count=count,
        license_name=cfg["license"],
    )
    print(f"Pulled {count} {cfg['name']} records -> {out_path}")
    print(f"Manifest written -> {manifest_path}")
    return manifest_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bronze-layer ingest for Module 2")
    parser.add_argument("--dataset", choices=["stead", "instance"], required=True)
    args = parser.parse_args()
    run(args.dataset)
