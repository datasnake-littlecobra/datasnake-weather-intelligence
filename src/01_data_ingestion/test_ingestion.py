"""
Phase 1 validation tests.

Tests both live API connectivity (integration) and database sanity checks.
Run after noaa_ingestion.py and usgs_seismic.py to verify data loaded correctly.

Usage:
    python src/01_data_ingestion/test_ingestion.py
    pytest src/01_data_ingestion/test_ingestion.py -v
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import pytest
import requests
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

with open(ROOT / "config.yaml") as f:
    CFG = yaml.safe_load(f)


# ── DB fixture ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def conn():
    url = os.getenv("DATABASE_URL")
    if url:
        c = psycopg2.connect(url)
    else:
        db = CFG["database"]
        c = psycopg2.connect(
            host=db["host"], port=db["port"], dbname=db["name"],
            user=os.getenv("DB_USER", db.get("user", "postgres")),
            password=os.getenv("DB_PASSWORD", db.get("password", "")),
        )
    yield c
    c.close()


# ── Schema tests ───────────────────────────────────────────────────────────────

def test_tables_exist(conn):
    expected = [
        "weather_observations",
        "seismic_events",
        "flood_zones",
        "seismic_stations",
        "risk_scores_cache",
        "parametric_sensor_readings",
    ]
    with conn.cursor() as cur:
        cur.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public';"
        )
        tables = {row[0] for row in cur.fetchall()}
    for t in expected:
        assert t in tables, f"Table '{t}' missing from schema"
    print(f"  PASS: All {len(expected)} tables exist")


def test_postgis_enabled(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT PostGIS_Version();")
        version = cur.fetchone()[0]
    assert version, "PostGIS not installed"
    print(f"  PASS: PostGIS version {version.strip()}")


def test_indexes_exist(conn):
    expected_indexes = [
        "idx_weather_time",
        "idx_weather_geometry",
        "idx_seismic_time",
        "idx_seismic_geometry",
    ]
    with conn.cursor() as cur:
        cur.execute(
            "SELECT indexname FROM pg_indexes WHERE schemaname = 'public';"
        )
        indexes = {row[0] for row in cur.fetchall()}
    for idx in expected_indexes:
        assert idx in indexes, f"Index '{idx}' not found"
    print(f"  PASS: All critical indexes exist")


# ── Weather observation tests ──────────────────────────────────────────────────

def test_weather_observations_loaded(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM weather_observations;")
        count = cur.fetchone()[0]
    assert count > 0, "No weather observations loaded — run noaa_ingestion.py first"
    print(f"  PASS: {count:,} weather observations in DB")


def test_weather_date_range(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT MIN(measurement_time), MAX(measurement_time) FROM weather_observations;"
        )
        min_t, max_t = cur.fetchone()
    assert min_t is not None
    # Most recent obs should be within the last 60 days
    now = datetime.now(timezone.utc)
    age_days = (now - max_t.replace(tzinfo=timezone.utc)).days
    assert age_days <= 60, f"Most recent observation is {age_days} days old (expected ≤ 60)"
    print(f"  PASS: Date range {min_t.date()} → {max_t.date()}")


def test_weather_no_bad_temperatures(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) FROM weather_observations
            WHERE temperature_celsius IS NOT NULL
              AND (temperature_celsius < -80 OR temperature_celsius > 60);
            """
        )
        bad = cur.fetchone()[0]
    assert bad == 0, f"{bad} weather observations have invalid temperature values"
    print("  PASS: No out-of-range temperature values")


def test_weather_geometry_populated(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM weather_observations WHERE geometry IS NULL;"
        )
        null_geom = cur.fetchone()[0]
    assert null_geom == 0, f"{null_geom} weather rows missing geometry"
    print("  PASS: All weather observations have geometry")


def test_weather_spatial_query(conn):
    """Verify PostGIS spatial queries work — 5km radius around Miami Beach."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) FROM weather_observations
            WHERE ST_DWithin(
                geometry,
                ST_SetSRID(ST_MakePoint(-80.13, 25.79), 4326)::geography,
                5000
            );
            """
        )
        count = cur.fetchone()[0]
    print(f"  INFO: {count} obs within 5km of Miami Beach (25.79, -80.13)")
    # Not asserting a minimum — depends on which stations were loaded


def test_weather_sample_rows(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT station_id, station_name, latitude, longitude,
                   measurement_time, temperature_celsius, wind_speed_ms
            FROM weather_observations
            ORDER BY measurement_time DESC
            LIMIT 5;
            """
        )
        rows = cur.fetchall()
    assert len(rows) > 0
    print(f"  PASS: Sample rows (most recent 5):")
    for row in rows:
        print(f"    {row[4].date()} | {row[0]} | temp={row[5]}°C | wind={row[6]}m/s")


# ── Seismic event tests ────────────────────────────────────────────────────────

def test_seismic_events_loaded(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM seismic_events;")
        count = cur.fetchone()[0]
    assert count > 0, "No seismic events loaded — run usgs_seismic.py first"
    print(f"  PASS: {count:,} seismic events in DB")


def test_seismic_magnitude_range(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT MIN(magnitude), MAX(magnitude), AVG(magnitude) FROM seismic_events;"
        )
        mn, mx, avg = cur.fetchone()
    assert mn >= -2 and mx <= 10, f"Magnitude out of bounds: {mn} – {mx}"
    print(f"  PASS: Magnitude range {mn:.1f} – {mx:.1f} (avg {float(avg):.2f})")


def test_seismic_bay_area_present(conn):
    """Verify Bay Area (37.5–37.9, -122.6–-122.1) has seismic data."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) FROM seismic_events
            WHERE ST_Within(
                geometry,
                ST_MakeEnvelope(-122.8, 37.0, -121.5, 38.5, 4326)
            );
            """
        )
        count = cur.fetchone()[0]
    assert count > 0, "No seismic events for Bay Area — check usgs config and re-run"
    print(f"  PASS: {count} seismic events in Bay Area bounding box")


def test_seismic_depth_positive(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM seismic_events WHERE depth_km < -10;"
        )
        bad = cur.fetchone()[0]
    assert bad == 0, f"{bad} seismic events have invalid depth values"
    print("  PASS: All depth values in valid range")


def test_seismic_sample_rows(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT event_id, magnitude, depth_km, region, event_time
            FROM seismic_events
            ORDER BY magnitude DESC
            LIMIT 5;
            """
        )
        rows = cur.fetchall()
    assert rows
    print("  PASS: Top 5 events by magnitude:")
    for row in rows:
        print(f"    M{row[1]} @ {row[2]}km — {row[3]} ({row[4].date()})")


# ── API connectivity tests ─────────────────────────────────────────────────────

def test_noaa_api_reachable():
    url = CFG["noaa"]["access_api_base"]
    # A minimal query just to check the endpoint is up
    resp = requests.get(
        url,
        params={
            "dataset": "global-hourly",
            "stations": "72202099999",
            "startDate": "2024-05-14T00:00:00",
            "endDate": "2024-05-14T01:00:00",
            "format": "json",
        },
        timeout=15,
    )
    assert resp.status_code in (200, 400, 404), f"NOAA API unexpected status {resp.status_code}"
    print(f"  PASS: NOAA API reachable (HTTP {resp.status_code})")


def test_usgs_api_reachable():
    url = CFG["usgs"]["fdsn_api_base"] + "/query"
    resp = requests.get(
        url,
        params={
            "format": "geojson",
            "starttime": "2025-01-01",
            "endtime": "2025-01-02",
            "minmagnitude": 2.5,
            "minlatitude": 37.0,
            "maxlatitude": 38.5,
            "minlongitude": -122.8,
            "maxlongitude": -121.5,
        },
        timeout=15,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("type") == "FeatureCollection"
    print(f"  PASS: USGS API reachable, returned FeatureCollection")


# ── Runner ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print()
    print("DataSnake Phase 1 — Ingestion Validation")
    print("=" * 55)

    load_dotenv(ROOT / ".env")
    url = os.getenv("DATABASE_URL")
    db = CFG["database"]
    conn_ = (
        psycopg2.connect(url) if url
        else psycopg2.connect(
            host=db["host"], port=db["port"], dbname=db["name"],
            user=os.getenv("DB_USER", db.get("user", "postgres")),
            password=os.getenv("DB_PASSWORD", db.get("password", "")),
        )
    )

    tests = [
        ("Schema: tables exist",          lambda: test_tables_exist(conn_)),
        ("Schema: PostGIS enabled",        lambda: test_postgis_enabled(conn_)),
        ("Schema: indexes exist",          lambda: test_indexes_exist(conn_)),
        ("Weather: rows loaded",           lambda: test_weather_observations_loaded(conn_)),
        ("Weather: date range valid",      lambda: test_weather_date_range(conn_)),
        ("Weather: no bad temps",          lambda: test_weather_no_bad_temperatures(conn_)),
        ("Weather: geometry set",          lambda: test_weather_geometry_populated(conn_)),
        ("Weather: spatial query works",   lambda: test_weather_spatial_query(conn_)),
        ("Weather: sample rows",           lambda: test_weather_sample_rows(conn_)),
        ("Seismic: rows loaded",           lambda: test_seismic_events_loaded(conn_)),
        ("Seismic: magnitude range",       lambda: test_seismic_magnitude_range(conn_)),
        ("Seismic: Bay Area present",      lambda: test_seismic_bay_area_present(conn_)),
        ("Seismic: depth valid",           lambda: test_seismic_depth_positive(conn_)),
        ("Seismic: sample rows",           lambda: test_seismic_sample_rows(conn_)),
        ("API: NOAA reachable",            test_noaa_api_reachable),
        ("API: USGS reachable",            test_usgs_api_reachable),
    ]

    passed = failed = 0
    for name, fn in tests:
        print(f"\n{name}")
        try:
            fn()
            passed += 1
        except AssertionError as e:
            print(f"  FAIL: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            failed += 1

    conn_.close()
    print()
    print("=" * 55)
    print(f"Results: {passed} passed / {failed} failed / {passed + failed} total")
    sys.exit(0 if failed == 0 else 1)
