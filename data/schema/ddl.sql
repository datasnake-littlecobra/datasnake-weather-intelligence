-- DataSnake Weather Intelligence: PostgreSQL + PostGIS Schema
-- Run: psql weather_intelligence < data/schema/ddl.sql

-- Requires PostGIS extension
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;

-- ============================================================
-- WEATHER OBSERVATIONS (NOAA Global Hourly)
-- ~15M+ rows/year; primary table for flood + wind use cases
-- ============================================================

CREATE TABLE IF NOT EXISTS weather_observations (
    id                          SERIAL PRIMARY KEY,
    station_id                  TEXT NOT NULL,
    station_name                TEXT,
    latitude                    NUMERIC(9,6) NOT NULL,
    longitude                   NUMERIC(9,6) NOT NULL,
    measurement_time            TIMESTAMP WITH TIME ZONE NOT NULL,

    -- Core measurements (all nullable — NOAA data is sparse)
    temperature_celsius         NUMERIC(6,2),
    relative_humidity_percent   NUMERIC(5,2),
    precipitation_mm            NUMERIC(8,3),
    wind_speed_ms               NUMERIC(6,2),
    wind_direction_degrees      NUMERIC(5,1),
    pressure_hpa                NUMERIC(7,2),
    solar_radiation             NUMERIC(8,2),

    -- Derived / computed fields
    dew_point_celsius           NUMERIC(6,2),

    -- Metadata
    created_at                  TIMESTAMP DEFAULT NOW(),
    data_source                 TEXT DEFAULT 'NOAA',
    raw_record                  JSONB,   -- store original API response for debugging

    -- Spatial
    geometry                    GEOMETRY(Point, 4326),

    -- Constraints
    CONSTRAINT chk_temp         CHECK (temperature_celsius > -80 AND temperature_celsius < 60),
    CONSTRAINT chk_humidity     CHECK (relative_humidity_percent >= 0 AND relative_humidity_percent <= 100),
    CONSTRAINT chk_precip       CHECK (precipitation_mm >= 0),
    CONSTRAINT chk_wind         CHECK (wind_speed_ms >= 0),
    CONSTRAINT chk_pressure     CHECK (pressure_hpa > 800 AND pressure_hpa < 1100)
);

-- Deduplicate on (station, time)
CREATE UNIQUE INDEX IF NOT EXISTS uq_weather_station_time
    ON weather_observations(station_id, measurement_time);

CREATE INDEX IF NOT EXISTS idx_weather_time
    ON weather_observations(measurement_time DESC);

CREATE INDEX IF NOT EXISTS idx_weather_station
    ON weather_observations(station_id);

CREATE INDEX IF NOT EXISTS idx_weather_geometry
    ON weather_observations USING GIST(geometry);

CREATE INDEX IF NOT EXISTS idx_weather_location_time
    ON weather_observations(station_id, measurement_time DESC);

-- ============================================================
-- SEISMIC EVENTS (USGS Earthquake Catalog)
-- Use cases: seismic precursor (UC2) + claims validation (UC5)
-- ============================================================

CREATE TABLE IF NOT EXISTS seismic_events (
    id          SERIAL PRIMARY KEY,
    event_id    TEXT UNIQUE NOT NULL,   -- USGS event ID (e.g. "us7000k4k2")
    magnitude   NUMERIC(4,2) NOT NULL,
    magnitude_type TEXT,                -- "ml", "mb", "mw", etc.
    depth_km    NUMERIC(7,2) NOT NULL,
    latitude    NUMERIC(9,6) NOT NULL,
    longitude   NUMERIC(9,6) NOT NULL,
    event_time  TIMESTAMP WITH TIME ZONE NOT NULL,

    -- Analysis fields
    region      TEXT,
    event_type  TEXT,                   -- "earthquake", "quarry blast", etc.
    felt_reports INT,                   -- number of "felt" reports from DYFI
    significance INT,                   -- USGS significance score (0-1000+)

    -- Metadata
    data_source TEXT DEFAULT 'USGS',
    created_at  TIMESTAMP DEFAULT NOW(),
    raw_record  JSONB,

    -- Spatial
    geometry    GEOMETRY(Point, 4326),

    CONSTRAINT chk_magnitude    CHECK (magnitude >= -2 AND magnitude <= 10),
    CONSTRAINT chk_depth        CHECK (depth_km >= -10 AND depth_km < 1000)
);

CREATE INDEX IF NOT EXISTS idx_seismic_time
    ON seismic_events(event_time DESC);

CREATE INDEX IF NOT EXISTS idx_seismic_magnitude
    ON seismic_events(magnitude DESC);

CREATE INDEX IF NOT EXISTS idx_seismic_geometry
    ON seismic_events USING GIST(geometry);

CREATE INDEX IF NOT EXISTS idx_seismic_region
    ON seismic_events(region);

-- ============================================================
-- FLOOD ZONES (FEMA NFHL)
-- Static reference table — updated when FEMA releases new maps
-- ============================================================

CREATE TABLE IF NOT EXISTS flood_zones (
    id              SERIAL PRIMARY KEY,
    fema_zone_id    TEXT UNIQUE,
    fema_zone       TEXT NOT NULL,  -- 'A', 'AE', 'AO', 'X', 'D', 'VE', etc.
    zone_subtype    TEXT,           -- additional FEMA classification detail
    state           TEXT,
    county          TEXT,
    dfirm_id        TEXT,           -- Digital Flood Insurance Rate Map ID

    -- Spatial
    geometry        GEOMETRY(MultiPolygon, 4326),

    -- Metadata
    effective_date  DATE,
    last_updated    DATE,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_flood_geometry
    ON flood_zones USING GIST(geometry);

CREATE INDEX IF NOT EXISTS idx_flood_zone
    ON flood_zones(fema_zone);

CREATE INDEX IF NOT EXISTS idx_flood_state_county
    ON flood_zones(state, county);

-- ============================================================
-- SEISMIC STATIONS
-- Network metadata — used for proximity queries + data quality
-- ============================================================

CREATE TABLE IF NOT EXISTS seismic_stations (
    id          SERIAL PRIMARY KEY,
    station_id  TEXT UNIQUE NOT NULL,
    station_name TEXT,
    network     TEXT,               -- 'CI', 'BK', 'NC', etc. (FDSN network codes)
    latitude    NUMERIC(9,6) NOT NULL,
    longitude   NUMERIC(9,6) NOT NULL,
    elevation_m NUMERIC(7,2),

    -- Metadata
    created_at  TIMESTAMP DEFAULT NOW(),
    geometry    GEOMETRY(Point, 4326)
);

CREATE INDEX IF NOT EXISTS idx_seismic_station_geometry
    ON seismic_stations USING GIST(geometry);

-- ============================================================
-- RISK SCORES CACHE
-- Pre-computed risk verdicts for dashboard + API serving
-- TTL-based cache invalidation via valid_until
-- ============================================================

CREATE TABLE IF NOT EXISTS risk_scores_cache (
    id          SERIAL PRIMARY KEY,
    latitude    NUMERIC(9,6) NOT NULL,
    longitude   NUMERIC(9,6) NOT NULL,
    risk_type   TEXT NOT NULL,          -- 'flash_flood', 'seismic', 'wind', 'coastal'
    score       NUMERIC(5,2) NOT NULL,  -- 0-100
    probability NUMERIC(5,4) NOT NULL,  -- 0-1
    threat_level TEXT NOT NULL,         -- 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'
    reasoning   TEXT,
    computed_at TIMESTAMP DEFAULT NOW(),
    valid_until TIMESTAMP,

    CONSTRAINT chk_score    CHECK (score >= 0 AND score <= 100),
    CONSTRAINT chk_prob     CHECK (probability >= 0 AND probability <= 1),
    CONSTRAINT chk_threat   CHECK (threat_level IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL'))
);

CREATE INDEX IF NOT EXISTS idx_risk_cache_location
    ON risk_scores_cache(latitude, longitude);

CREATE INDEX IF NOT EXISTS idx_risk_cache_type
    ON risk_scores_cache(risk_type);

CREATE INDEX IF NOT EXISTS idx_risk_cache_validity
    ON risk_scores_cache(valid_until DESC);

-- ============================================================
-- PARAMETRIC SENSOR READINGS
-- Use case 3: Bangladesh monsoon trigger certification
-- Each row = one daily sensor reading, SHA-256 hashed for audit
-- ============================================================

CREATE TABLE IF NOT EXISTS parametric_sensor_readings (
    id              SERIAL PRIMARY KEY,
    sensor_id       TEXT NOT NULL,
    product_id      TEXT NOT NULL,          -- links to a parametric product/contract
    reading_date    DATE NOT NULL,
    rainfall_mm     NUMERIC(8,3) NOT NULL,
    cumulative_mm   NUMERIC(10,3),          -- running total for the season
    latitude        NUMERIC(9,6),
    longitude       NUMERIC(9,6),
    reading_hash    TEXT NOT NULL,          -- SHA-256(sensor_id + date + rainfall_mm)
    noaa_blend_mm   NUMERIC(8,3),           -- NOAA blended value for this day
    blended_mm      NUMERIC(8,3),           -- weighted blend (70% sensor + 30% NOAA)
    created_at      TIMESTAMP DEFAULT NOW(),

    CONSTRAINT uq_sensor_date UNIQUE (sensor_id, product_id, reading_date),
    CONSTRAINT chk_rainfall   CHECK (rainfall_mm >= 0)
);

CREATE INDEX IF NOT EXISTS idx_parametric_product
    ON parametric_sensor_readings(product_id, reading_date);

CREATE INDEX IF NOT EXISTS idx_parametric_sensor
    ON parametric_sensor_readings(sensor_id);

-- ============================================================
-- HELPER: schema version tracking
-- ============================================================

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT PRIMARY KEY,
    applied_at  TIMESTAMP DEFAULT NOW(),
    description TEXT
);

INSERT INTO schema_migrations (version, description)
VALUES ('1.0.0', 'Initial schema: weather_observations, seismic_events, flood_zones, risk_scores_cache, parametric_sensor_readings')
ON CONFLICT (version) DO NOTHING;
