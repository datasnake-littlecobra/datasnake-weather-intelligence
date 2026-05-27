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
def _fetch_noaa_page(params: dict) -> list[dict]:
    headers = {"token": NOAA_TOKEN} if NOAA_TOKEN else {}
    resp = requests.get(
        BASE_URL,
        params=params,
        headers=headers,
        timeout=CFG["noaa"]["request_timeout_sec"],
    )
    resp.raise_for_status()

    # NOAA Access API returns CSV or JSON depending on format param
    if params.get("format", "json") == "json":
        data = resp.json()
        return data if isinstance(data, list) else []

    # CSV path: parse with pandas
    from io import StringIO
    df = pd.read_csv(StringIO(resp.text), low_memory=False)
    return df.to_dict(orient="records")


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
        "format": "json",
        "includeAttributes": "false",
        "units": "metric",
    }
    try:
        records = _fetch_noaa_page(params)
        log.debug("  Station %s: %d raw records", station_id, len(records))
        return records
    except requests.HTTPError as e:
        if e.response.status_code == 404:
            log.warning("  Station %s: no data for this period", station_id)
            return []
        raise


def parse_noaa_record(raw: dict, station_id: str) -> dict | None:
    """Extract and validate fields from a NOAA global-hourly JSON record."""
    try:
        # NOAA global-hourly uses named fields; nulls come as "" or "9999"
        def safe_float(val: Any, sentinel: float = 9999.9) -> float | None:
            if val is None or val == "" or val == "9999" or val == "99999":
                return None
            try:
                f = float(val)
                return None if f >= sentinel else f
            except (TypeError, ValueError):
                return None

        ts_str = raw.get("DATE") or raw.get("date")
        if not ts_str:
            return None

        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))

        lat = safe_float(raw.get("LATITUDE") or raw.get("latitude"))
        lon = safe_float(raw.get("LONGITUDE") or raw.get("longitude"))
        if lat is None or lon is None:
            return None

        # Temperature: NOAA reports in tenths of C, or direct Celsius
        tmp = safe_float(raw.get("TMP") or raw.get("tmp") or raw.get("HourlyDryBulbTemperature"))
        if tmp and abs(tmp) > 100:  # tenths of a degree
            tmp = tmp / 10.0

        # Wind speed: NOAA in m/s or tenths of m/s
        wnd_raw = raw.get("WND") or raw.get("HourlyWindSpeed")
        wind_ms = None
        wind_dir = None
        if wnd_raw:
            if isinstance(wnd_raw, str) and "," in wnd_raw:
                parts = wnd_raw.split(",")
                wind_dir = safe_float(parts[0])
                wind_ms = safe_float(parts[3])
                if wind_ms and wind_ms > 100:
                    wind_ms = wind_ms / 10.0
            else:
                wind_ms = safe_float(wnd_raw)

        # Precipitation: NOAA in tenths of mm
        aa1_raw = raw.get("AA1") or raw.get("HourlyPrecipitation")
        precip_mm = None
        if aa1_raw:
            if isinstance(aa1_raw, str) and "," in aa1_raw:
                parts = aa1_raw.split(",")
                precip_raw = safe_float(parts[1])
                if precip_raw is not None:
                    precip_mm = precip_raw / 10.0
            else:
                precip_mm = safe_float(aa1_raw)

        # Pressure: NOAA SLP in tenths of hPa
        slp_raw = raw.get("SLP") or raw.get("HourlySeaLevelPressure")
        pressure_hpa = None
        if slp_raw:
            pressure_hpa = safe_float(slp_raw)
            if pressure_hpa and pressure_hpa > 1100:
                pressure_hpa = pressure_hpa / 10.0

        # Relative humidity
        rh = safe_float(raw.get("RH") or raw.get("HourlyRelativeHumidity"))

        station_name = (
            raw.get("NAME") or raw.get("name") or raw.get("STATION_NAME") or ""
        )

        return {
            "station_id": station_id,
            "station_name": station_name,
            "latitude": lat,
            "longitude": lon,
            "measurement_time": ts.isoformat(),
            "temperature_celsius": tmp,
            "relative_humidity_percent": rh,
            "precipitation_mm": precip_mm,
            "wind_speed_ms": wind_ms,
            "wind_direction_degrees": wind_dir,
            "pressure_hpa": pressure_hpa,
            "raw_record": json.dumps(raw),
        }
    except Exception as e:
        log.debug("  Failed to parse record: %s — %s", raw.get("DATE"), e)
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
