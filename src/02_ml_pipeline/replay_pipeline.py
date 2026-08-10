"""Idempotent replay pipeline: classify gold-layer windows and upsert into
vibration_classified_events.

This substitutes for a live sensor feed in Phase 1 (no hardware sensor yet —
see CLAUDE.md's phased scope). Re-running this script on the same gold data
must not create duplicate rows: it upserts on `event_id` (deterministic hash
of dataset+window_id), matching the idempotent-ingest SLA already established
elsewhere in this repo's ingestion scripts (usgs_seismic.py's
`ON CONFLICT (event_id) DO NOTHING`).

Follows this repo's existing DB-connection convention (see
src/01_data_ingestion/usgs_seismic.py) rather than introducing a new one.
"""

import argparse
import hashlib
import json
import logging
import os
import sys
import uuid
from pathlib import Path

import pandas as pd
import psycopg2
import psycopg2.extras
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

with open(ROOT / "config_vibration.yaml") as f:
    CFG = yaml.safe_load(f)

GOLD_DIR = ROOT / "data" / "module2_vibration" / "gold"

log_cfg = CFG["logging"]
Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=getattr(logging, log_cfg["level"]),
    format=log_cfg["format"],
    datefmt=log_cfg["datefmt"],
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(log_cfg["file"])],
)
log = logging.getLogger(__name__)


def get_connection() -> psycopg2.extensions.connection:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set — see .env.example")
    return psycopg2.connect(url)


def deterministic_event_id(dataset: str, window_id: str) -> str:
    """Same (dataset, window_id) always produces the same event_id, so a
    rerun upserts the same row instead of inserting a duplicate."""
    digest = hashlib.sha256(f"{dataset}:{window_id}".encode()).hexdigest()[:32]
    return str(uuid.UUID(digest))


def classify_window(row: pd.Series) -> dict:
    """Placeholder classification call. Wire this to the trained model from
    Slice 6 (models/registry/<name>/metadata.json) once available — this
    function is the seam between the pipeline and the model, kept isolated
    so swapping the model implementation doesn't touch the DB-write logic.
    """
    return {
        "event_type": row["event_type"],
        "confidence": 0.0,  # replace with real model output
        "severity_score": None,
        "abstain": True,  # abstain until a real model is wired in here
        "requires_human_review": True,
    }


def upsert_events(conn: psycopg2.extensions.connection, rows: list[dict], pipeline_run_id: str) -> int:
    query = """
        INSERT INTO vibration_classified_events (
            event_id, sensor_id, event_time, event_type, confidence, severity_score,
            scenario_family_id, raw_waveform_ref, split, source_dataset,
            data_version, pipeline_run_id, evidence, abstain, requires_human_review
        ) VALUES %s
        ON CONFLICT (event_id) DO UPDATE SET
            confidence = EXCLUDED.confidence,
            severity_score = EXCLUDED.severity_score,
            evidence = EXCLUDED.evidence,
            abstain = EXCLUDED.abstain,
            requires_human_review = EXCLUDED.requires_human_review
    """
    values = [
        (
            r["event_id"],
            r["sensor_id"],
            r["event_time"],
            r["event_type"],
            r["confidence"],
            r["severity_score"],
            r["scenario_family_id"],
            r["raw_waveform_ref"],
            r["split"],
            r["source_dataset"],
            r["data_version"],
            pipeline_run_id,
            json.dumps(r["evidence"]),
            r["abstain"],
            r["requires_human_review"],
        )
        for r in rows
    ]
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, query, values)
    conn.commit()
    return len(values)


def run(dataset: str, data_version: str = "v1") -> int:
    gold_path = GOLD_DIR / f"{dataset}_gold.csv"
    if not gold_path.exists():
        raise FileNotFoundError(f"Run gold_label_split.py --dataset {dataset} first")

    gold = pd.read_csv(gold_path)
    pipeline_run_id = str(uuid.uuid4())

    rows = []
    for _, row in gold.iterrows():
        classification = classify_window(row)
        rows.append(
            {
                "event_id": deterministic_event_id(dataset, row["window_id"]),
                "sensor_id": f"replay:{dataset}",
                "event_time": pd.Timestamp.utcnow().isoformat(),
                "event_type": classification["event_type"],
                "confidence": classification["confidence"],
                "severity_score": classification["severity_score"],
                "scenario_family_id": row["scenario_family_id"],
                "raw_waveform_ref": row["window_id"],
                "split": row["split"],
                "source_dataset": row["source_dataset"],
                "data_version": data_version,
                "evidence": {"window_id": row["window_id"], "source_idx": int(row["source_idx"])},
                "abstain": classification["abstain"],
                "requires_human_review": classification["requires_human_review"],
            }
        )

    conn = get_connection()
    try:
        n_written = upsert_events(conn, rows, pipeline_run_id)
    finally:
        conn.close()

    log.info(f"Replay run {pipeline_run_id}: upserted {n_written} rows for {dataset}")
    return n_written


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Idempotent replay pipeline for Module 2")
    parser.add_argument("--dataset", choices=["stead", "instance"], required=True)
    parser.add_argument("--data-version", default="v1")
    args = parser.parse_args()
    run(args.dataset, args.data_version)
