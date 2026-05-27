# Phase 1: Data Ingestion

Pulls NOAA Global Hourly weather observations and USGS earthquake catalog events into PostgreSQL + PostGIS.

---

## What This Phase Builds

| File | Purpose |
|---|---|
| `ddl.sql` | Full PostgreSQL schema (in `data/schema/`) |
| `noaa_ingestion.py` | NOAA NCEI Access API → `weather_observations` |
| `usgs_seismic.py` | USGS FDSN API → `seismic_events` |
| `test_ingestion.py` | Validates schema + data loaded correctly |

---

## Prerequisites

1. **PostgreSQL 14+** with PostGIS extension
2. **Python 3.10+** with `pip install -r requirements.txt`
3. `.env` file with your database credentials (copy from `.env.example`)

---

## Setup

```bash
# Create the database
createdb weather_intelligence

# Load schema (PostGIS tables + indexes)
psql weather_intelligence < data/schema/ddl.sql

# Verify PostGIS is installed
psql weather_intelligence -c "SELECT PostGIS_Version();"
```

---

## Running

```bash
# Pull all regions (Miami, Bay Area, Naples) — last 30 days
python src/01_data_ingestion/noaa_ingestion.py

# Pull a specific region with custom lookback
python src/01_data_ingestion/noaa_ingestion.py --region miami_fl --days 60

# Pull all USGS seismic data (last 365 days by default)
python src/01_data_ingestion/usgs_seismic.py

# Pull Bay Area seismic data only
python src/01_data_ingestion/usgs_seismic.py --region bay_area --days 730

# Validate everything loaded correctly
python src/01_data_ingestion/test_ingestion.py
```

---

## Expected Output

```
[2026-05-27 14:23:15] INFO DataSnake NOAA Ingestion Pipeline
[2026-05-27 14:23:15] INFO Regions: ['miami_fl', 'san_francisco_ca', 'naples_fl'] | Lookback: 30 days
[2026-05-27 14:23:16] INFO Connecting to PostgreSQL ...
[2026-05-27 14:23:16] INFO Connected.
[2026-05-27 14:23:17] INFO Fetching NOAA data for Miami Beach, FL (2026-04-27 → 2026-05-27)
[2026-05-27 14:23:18] INFO   Pulling station 72202099999 ...
[2026-05-27 14:23:45] INFO   Station 72202099999: 720 raw → 714 parsed → 714 inserted
...
[2026-05-27 14:24:41] INFO ── NOAA Ingestion Summary ────────────────────────────────
[2026-05-27 14:24:41] INFO   miami_fl                   raw=1440   inserted=1428
[2026-05-27 14:24:41] INFO   san_francisco_ca            raw=1440   inserted=1440
[2026-05-27 14:24:42] INFO   Total inserted: 2868 observations
```

---

## Verification Queries

After running ingestion, check your data in psql:

```sql
-- Row counts
SELECT 'weather_observations' AS table_name, COUNT(*) FROM weather_observations
UNION ALL
SELECT 'seismic_events', COUNT(*) FROM seismic_events;

-- Recent weather near Miami Beach
SELECT station_id, measurement_time, temperature_celsius, precipitation_mm
FROM weather_observations
WHERE ST_DWithin(
    geometry,
    ST_SetSRID(ST_MakePoint(-80.13, 25.79), 4326)::geography,
    5000
)
ORDER BY measurement_time DESC
LIMIT 10;

-- Bay Area seismic activity (last 30 days)
SELECT event_id, magnitude, depth_km, region, event_time
FROM seismic_events
WHERE event_time > NOW() - INTERVAL '30 days'
  AND ST_Within(geometry, ST_MakeEnvelope(-122.8, 37.0, -121.5, 38.5, 4326))
ORDER BY magnitude DESC
LIMIT 10;

-- Magnitude distribution
SELECT
    FLOOR(magnitude) AS mag_floor,
    COUNT(*) AS event_count
FROM seismic_events
GROUP BY mag_floor
ORDER BY mag_floor DESC;
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `psycopg2.OperationalError` | Check `.env` credentials; verify PostgreSQL is running |
| `PostGIS_Version()` fails | Run `CREATE EXTENSION postgis;` in psql as superuser |
| NOAA returns 0 records | Station IDs may be wrong; check [NOAA Station Search](https://www.ncdc.noaa.gov/cdo-web/datatools/findstation) |
| USGS returns 404 | Usually means no events match the query; check lat/lon bounds and date range |
| `tenacity` not found | Run `pip install -r requirements.txt` |

---

## Data Sources

- **NOAA Global Hourly**: https://www.ncei.noaa.gov/access/services/data/v1
- **USGS FDSN Event API**: https://earthquake.usgs.gov/fdsnws/event/1/query
- Both are **free, no registration required** for standard usage
