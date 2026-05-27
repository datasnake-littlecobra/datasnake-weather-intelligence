"""
NOAA Global Hourly data ingestion pipeline.

Fetches weather observations from NOAA's NCEI Access API and loads them
into PostgreSQL. Covers the station regions defined in config.yaml.

Usage:
    python src/01_data_ingestion/noaa_ingestion.py
    python src/01_data_ingestion/noaa_ingestion.py --region miami_fl --days 30
"""

import argparse
import hashlib
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
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


# ── NOAA API ───────────────────────────────────────────────────────────────────

BASE_URL = CFG["noaa"]["access_api_base"]
NOAA_TOKEN = os.getenv("NOAA_API_TOKEN", "")


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=30))
def _fetch_noaa_csv(params: dict) -> list[dict]:
    """NOAA NCEI Access API — always request CSV; parse with pandas.

    The global-hourly dataset returns well-formed CSV with named columns.
    JSON format is technically supported but inconsistently shaped across
    dataset versions; CSV is the stable path.
    """
    headers = {"token": NOAA_TOKEN} if NOAA_TOKEN else {}
    params = {**params, "format": "csv"}  # force CSV regardless of caller
    resp = requests.get(
        BASE_URL,
        params=params,
        headers=headers,
        timeout=CFG["noaa"]["request_timeout_sec"],
    )
    resp.raise_for_status()

    if not resp.text.strip():
        return []

    from io import StringIO
    try:
        df = pd.read_csv(StringIO(resp.text), low_memory=False)
        return df.to_dict(orient="records")
    except Exception as e:
        log.warning("  CSV parse failed: %s", e)
        return []


def fetch_noaa_station_data(
    station_id: str,
    start_date: str,
    end_date: str,
) -> list[dict]:
    """Fetch hourly obs for one station between start_date and end_date (YYYY-MM-DD)."""
    params = {
        "dataset": CFG["noaa"]["dataset"],
        "stations": station_id,
        "startDate": start_date + "T00:00:00",
        "endDate": end_date + "T23:59:59",
        "includeAttributes": "false",
        "units": "metric",
    }
    try:
        records = _fetch_noaa_csv(params)
        log.debug("  Station %s: %d raw records", station_id, len(records))
        return records
    except requests.HTTPError as e:
        if e.response.status_code in (404, 400):
            log.warning("  Station %s: no data returned (HTTP %s)", station_id, e.response.status_code)
            return []
        raise


def parse_noaa_record(raw: dict, station_id: str) -> dict | None:
    """Extract and validate fields from a NOAA global-hourly CSV row.

    NOAA ISD CSV columns:
      STATION, DATE, SOURCE, LATITUDE, LONGITUDE, ELEVATION, NAME,
      REPORT_TYPE, CALL_SIGN, QUALITY_PROCESS, WND, CIG, VIS, TMP, DEW,
      SLP, AA1, ...

    Comma-packed fields (e.g. WND="270,1,N,0010,1") are decoded by position.
    All quality/sentinel values (9999, 999, etc.) are treated as null.
    """
    try:
        def safe_float(val: Any, sentinels: tuple = (9999, 99999, 999.9, 9999.9)) -> float | None:
            if val is None or str(val).strip() in ("", "9999", "99999", "999", "999.9"):
                return None
            try:
                f = float(val)
                return None if f in sentinels or f > 9000 else f
            except (TypeError, ValueError):
                return None

        # DATE column: "2024-05-15T14:00:00" or "2024-05-15 14:00:00"
        ts_str = str(raw.get("DATE", "")).strip()
        if not ts_str:
            return None
        ts_str = ts_str.replace(" ", "T")
        if not ts_str.endswith("Z") and "+" not in ts_str:
            ts_str += "+00:00"
        ts = datetime.fromisoformat(ts_str)

        lat = safe_float(raw.get("LATITUDE"))
        lon = safe_float(raw.get("LONGITUDE"))
        if lat is None or lon is None:
            return None

        # TMP field: "0232,1" → temp in tenths of Celsius, quality flag
        tmp = None
        tmp_raw = str(raw.get("TMP", "")).strip()
        if tmp_raw and "," in tmp_raw:
            tmp_parts = tmp_raw.split(",")
            tmp_raw_val = safe_float(tmp_parts[0])
            if tmp_raw_val is not None:
                tmp = tmp_raw_val / 10.0  # tenths of C → C
                if not (-80 < tmp < 60):
                    tmp = None

        # DEW field: "0189,1" → dew point in tenths of Celsius
        dew = None
        dew_raw = str(raw.get("DEW", "")).strip()
        if dew_raw and "," in dew_raw:
            dew_parts = dew_raw.split(",")
            dew_raw_val = safe_float(dew_parts[0])
            if dew_raw_val is not None:
                dew = dew_raw_val / 10.0

        # WND field: "270,1,N,0085,1" → direction, dir-quality, obs-type, speed(tenths m/s), speed-quality
        wind_ms = None
        wind_dir = None
        wnd_raw = str(raw.get("WND", "")).strip()
        if wnd_raw and "," in wnd_raw:
            wnd_parts = wnd_raw.split(",")
            if len(wnd_parts) >= 4:
                wind_dir = safe_float(wnd_parts[0])
                if wind_dir and wind_dir > 360:
                    wind_dir = None
                spd = safe_float(wnd_parts[3])
                if spd is not None:
                    wind_ms = spd / 10.0  # tenths m/s → m/s
                    if wind_ms > 100:
                        wind_ms = None

        # AA1 field: "01,0000,2,5" → period hours, depth(tenths mm), condition, quality
        precip_mm = None
        aa1_raw = str(raw.get("AA1", "")).strip()
        if aa1_raw and "," in aa1_raw:
            aa1_parts = aa1_raw.split(",")
            if len(aa1_parts) >= 2:
                depth = safe_float(aa1_parts[1])
                if depth is not None:
                    precip_mm = depth / 10.0  # tenths mm → mm

        # SLP field: "10132,1" → pressure in tenths of hPa
        pressure_hpa = None
        slp_raw = str(raw.get("SLP", "")).strip()
        if slp_raw and "," in slp_raw:
            slp_parts = slp_raw.split(",")
            slp_val = safe_float(slp_parts[0])
            if slp_val is not None:
                pressure_hpa = slp_val / 10.0  # tenths hPa → hPa
                if not (800 < pressure_hpa < 1100):
                    pressure_hpa = None

        station_name = str(raw.get("NAME", "")).strip()

        return {
            "station_id": station_id,
            "station_name": station_name,
            "latitude": lat,
            "longitude": lon,
            "measurement_time": ts.isoformat(),
            "temperature_celsius": tmp,
            "relative_humidity_percent": None,   # ISD doesn't carry RH directly
            "precipitation_mm": precip_mm,
            "wind_speed_ms": wind_ms,
            "wind_direction_degrees": wind_dir,
            "pressure_hpa": pressure_hpa,
            "raw_record": json.dumps({k: str(v) for k, v in raw.items()}),
        }
    except Exception as e:
        log.debug("  Failed to parse record dated %s: %s", raw.get("DATE"), e)
        return None


# ── Insert ─────────────────────────────────────────────────────────────────────

INSERT_SQL = """
INSERT INTO weather_observations (
    station_id, station_name, latitude, longitude,
    measurement_time, temperature_celsius, relative_humidity_percent,
    precipitation_mm, wind_speed_ms, wind_direction_degrees,
    pressure_hpa, data_source, raw_record,
    geometry
) VALUES (
    %(station_id)s, %(station_name)s, %(latitude)s, %(longitude)s,
    %(measurement_time)s, %(temperature_celsius)s, %(relative_humidity_percent)s,
    %(precipitation_mm)s, %(wind_speed_ms)s, %(wind_direction_degrees)s,
    %(pressure_hpa)s, 'NOAA', %(raw_record)s,
    ST_SetSRID(ST_MakePoint(%(longitude)s, %(latitude)s), 4326)
)
ON CONFLICT (station_id, measurement_time) DO NOTHING;
"""


def insert_observations(conn, records: list[dict]) -> int:
    """Bulk insert parsed records; return count of rows actually inserted."""
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
    region = CFG["noaa"]["regions"].get(region_name)
    if not region:
        raise ValueError(f"Region '{region_name}' not found in config.yaml")

    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=days)
    start_str = start_dt.strftime("%Y-%m-%d")
    end_str = end_dt.strftime("%Y-%m-%d")

    log.info(
        "Fetching NOAA data for %s (%s → %s)",
        region["name"], start_str, end_str,
    )

    total_raw = 0
    total_inserted = 0
    station_ids = region.get("station_ids", [])

    if not station_ids:
        log.warning("No station_ids configured for region '%s'", region_name)
        return {"region": region_name, "raw": 0, "inserted": 0}

    for sid in station_ids:
        log.info("  Pulling station %s ...", sid)
        raw_records = fetch_noaa_station_data(sid, start_str, end_str)
        total_raw += len(raw_records)

        parsed = [r for r in (parse_noaa_record(raw, sid) for raw in raw_records) if r]
        n = insert_observations(conn, parsed)
        total_inserted += n
        log.info("  Station %s: %d raw → %d parsed → %d inserted", sid, len(raw_records), len(parsed), n)

    return {"region": region_name, "raw": total_raw, "inserted": total_inserted}


def main(regions: list[str] | None = None, days: int | None = None):
    days = days or CFG["noaa"]["lookback_days"]
    all_regions = list(CFG["noaa"]["regions"].keys())
    target_regions = regions or all_regions

    log.info("=" * 60)
    log.info("DataSnake NOAA Ingestion Pipeline")
    log.info("Regions: %s | Lookback: %d days", target_regions, days)
    log.info("=" * 60)

    log.info("Connecting to PostgreSQL ...")
    conn = get_connection()
    log.info("Connected.")

    results = []
    for region_name in target_regions:
        try:
            result = run_region(conn, region_name, days)
            results.append(result)
        except Exception as e:
            log.error("Region '%s' failed: %s", region_name, e)

    conn.close()

    log.info("")
    log.info("── NOAA Ingestion Summary ────────────────────────────────")
    total_inserted = 0
    for r in results:
        log.info(
            "  %-25s  raw=%-6d  inserted=%d",
            r["region"], r["raw"], r["inserted"],
        )
        total_inserted += r["inserted"]
    log.info("  Total inserted: %d observations", total_inserted)
    log.info("── Done ──────────────────────────────────────────────────")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NOAA Global Hourly ingestion")
    parser.add_argument("--region", nargs="+", help="Region(s) from config.yaml")
    parser.add_argument("--days", type=int, help="Lookback days (default: from config)")
    args = parser.parse_args()
    main(regions=args.region, days=args.days)
