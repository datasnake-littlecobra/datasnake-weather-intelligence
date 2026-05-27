"""
USGS earthquake catalog ingestion pipeline.

Fetches seismic events from the USGS FDSN Event API and loads them
into PostgreSQL. Covers Bay Area and other regions in config.yaml.

Usage:
    python src/01_data_ingestion/usgs_seismic.py
    python src/01_data_ingestion/usgs_seismic.py --region bay_area --days 365
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg2
import requests
import yaml
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential

# ── Setup ──────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

with open(ROOT / "config.yaml") as f:
    CFG = yaml.safe_load(f)

log_cfg = CFG["logging"]
Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=getattr(logging, log_cfg["level"]),
    format=log_cfg["format"],
    datefmt=log_cfg["datefmt"],
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_cfg["file"]),
    ],
)
log = logging.getLogger(__name__)

BASE_URL = CFG["usgs"]["fdsn_api_base"] + "/query"


# ── Database ───────────────────────────────────────────────────────────────────

def get_connection() -> psycopg2.extensions.connection:
    url = os.getenv("DATABASE_URL")
    if url:
        return psycopg2.connect(url)
    db = CFG["database"]
    return psycopg2.connect(
        host=db["host"],
        port=db["port"],
        dbname=db["name"],
        user=os.getenv("DB_USER", db.get("user", "postgres")),
        password=os.getenv("DB_PASSWORD", db.get("password", "")),
    )


# ── USGS API ───────────────────────────────────────────────────────────────────

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=30))
def fetch_usgs_events(
    lat_min: float,
    lat_max: float,
    lon_min: float,
    lon_max: float,
    start_time: str,
    end_time: str,
    min_magnitude: float,
) -> list[dict]:
    """Fetch GeoJSON earthquake events from USGS FDSN API."""
    params = {
        "format": "geojson",
        "starttime": start_time,
        "endtime": end_time,
        "minlatitude": lat_min,
        "maxlatitude": lat_max,
        "minlongitude": lon_min,
        "maxlongitude": lon_max,
        "minmagnitude": min_magnitude,
        "orderby": "time",
    }

    resp = requests.get(
        BASE_URL,
        params=params,
        timeout=CFG["usgs"]["request_timeout_sec"],
    )
    resp.raise_for_status()

    geojson = resp.json()
    features = geojson.get("features", [])
    log.debug("USGS returned %d features", len(features))
    return features


def parse_usgs_feature(feature: dict) -> dict | None:
    """Extract fields from a USGS GeoJSON feature."""
    try:
        props = feature.get("properties", {})
        geom = feature.get("geometry", {})
        coords = geom.get("coordinates", [])

        if len(coords) < 3:
            return None

        lon, lat, depth_neg = coords[0], coords[1], coords[2]
        # USGS depth is in km, positive = below surface
        depth_km = abs(depth_neg) if depth_neg is not None else 0.0

        event_id = feature.get("id")
        if not event_id:
            return None

        # USGS time is milliseconds since epoch
        time_ms = props.get("time")
        if time_ms is None:
            return None
        event_time = datetime.fromtimestamp(time_ms / 1000, tz=timezone.utc)

        mag = props.get("mag")
        if mag is None:
            return None

        return {
            "event_id": event_id,
            "magnitude": float(mag),
            "magnitude_type": props.get("magType"),
            "depth_km": float(depth_km),
            "latitude": float(lat),
            "longitude": float(lon),
            "event_time": event_time.isoformat(),
            "region": props.get("place", ""),
            "event_type": props.get("type", "earthquake"),
            "felt_reports": props.get("felt"),
            "significance": props.get("sig"),
            "raw_record": json.dumps(props),
        }
    except Exception as e:
        log.debug("Failed to parse USGS feature %s: %s", feature.get("id"), e)
        return None


# ── Insert ─────────────────────────────────────────────────────────────────────

INSERT_SQL = """
INSERT INTO seismic_events (
    event_id, magnitude, magnitude_type, depth_km,
    latitude, longitude, event_time,
    region, event_type, felt_reports, significance,
    data_source, raw_record, geometry
) VALUES (
    %(event_id)s, %(magnitude)s, %(magnitude_type)s, %(depth_km)s,
    %(latitude)s, %(longitude)s, %(event_time)s,
    %(region)s, %(event_type)s, %(felt_reports)s, %(significance)s,
    'USGS', %(raw_record)s,
    ST_SetSRID(ST_MakePoint(%(longitude)s, %(latitude)s), 4326)
)
ON CONFLICT (event_id) DO NOTHING;
"""


def insert_events(conn, records: list[dict]) -> int:
    if not records:
        return 0
    with conn.cursor() as cur:
        inserted = 0
        for rec in records:
            cur.execute(INSERT_SQL, rec)
            inserted += cur.rowcount
        conn.commit()
    return inserted


# ── Main pipeline ──────────────────────────────────────────────────────────────

def run_region(conn, region_name: str, days: int) -> dict:
    region = CFG["usgs"]["regions"].get(region_name)
    if not region:
        raise ValueError(f"Region '{region_name}' not in config.yaml usgs.regions")

    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=days)
    start_str = start_dt.strftime("%Y-%m-%dT%H:%M:%S")
    end_str = end_dt.strftime("%Y-%m-%dT%H:%M:%S")

    log.info(
        "Fetching USGS seismic events for %s (%s → %s), M >= %.1f",
        region["name"], start_str[:10], end_str[:10],
        CFG["usgs"]["min_magnitude"],
    )

    features = fetch_usgs_events(
        lat_min=region["lat_min"],
        lat_max=region["lat_max"],
        lon_min=region["lon_min"],
        lon_max=region["lon_max"],
        start_time=start_str,
        end_time=end_str,
        min_magnitude=CFG["usgs"]["min_magnitude"],
    )

    parsed = [r for r in (parse_usgs_feature(f) for f in features) if r]
    n = insert_events(conn, parsed)

    log.info(
        "  %s: %d features → %d parsed → %d inserted",
        region_name, len(features), len(parsed), n,
    )

    if parsed:
        mags = [r["magnitude"] for r in parsed]
        log.info(
            "  Magnitude range: %.1f – %.1f (median: %.1f)",
            min(mags), max(mags),
            sorted(mags)[len(mags) // 2],
        )

    return {"region": region_name, "features": len(features), "inserted": n}


def main(regions: list[str] | None = None, days: int | None = None):
    days = days or CFG["usgs"]["lookback_days"]
    all_regions = list(CFG["usgs"]["regions"].keys())
    target_regions = regions or all_regions

    log.info("=" * 60)
    log.info("DataSnake USGS Seismic Ingestion Pipeline")
    log.info("Regions: %s | Lookback: %d days", target_regions, days)
    log.info("=" * 60)

    conn = get_connection()

    results = []
    for region_name in target_regions:
        try:
            result = run_region(conn, region_name, days)
            results.append(result)
        except Exception as e:
            log.error("Region '%s' failed: %s", region_name, e)

    conn.close()

    log.info("")
    log.info("── USGS Ingestion Summary ────────────────────────────────")
    total_inserted = 0
    for r in results:
        log.info(
            "  %-25s  features=%-6d  inserted=%d",
            r["region"], r["features"], r["inserted"],
        )
        total_inserted += r["inserted"]
    log.info("  Total seismic events inserted: %d", total_inserted)
    log.info("── Done ──────────────────────────────────────────────────")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="USGS seismic event ingestion")
    parser.add_argument("--region", nargs="+", help="Region(s) from config.yaml")
    parser.add_argument("--days", type=int, help="Lookback days (default: from config)")
    args = parser.parse_args()
    main(regions=args.region, days=args.days)
