-- DataSnake Weather Intelligence: Module 2 (Seismic/Vibration Intelligence) Schema
-- Additive to ddl.sql — does NOT modify or touch any existing table.
-- Run after ddl.sql: psql weather_intelligence < data/schema/02_vibration_intelligence.sql

-- ============================================================
-- NAMING NOTE
-- ============================================================
-- The existing `seismic_events` table (see ddl.sql) is the RAW USGS
-- earthquake catalog — magnitude/depth/event_time per USGS event ID.
-- It is untouched by this file.
--
-- This table, `vibration_classified_events`, is a DIFFERENT concept:
-- ML-classified sensor waveform events (seismic | vehicle_human |
-- environmental | unknown), the output of Module 2's SeisBench-based
-- classifier. Named "vibration" (not "seismic") deliberately, because
-- most detected events are not earthquakes at all, and to avoid
-- colliding with the existing "seismic precursor" (catalog-frequency)
-- concept already used elsewhere in this repo's risk-translation layer.
-- ============================================================

CREATE TABLE IF NOT EXISTS vibration_classified_events (
    id                      SERIAL PRIMARY KEY,
    event_id                TEXT UNIQUE NOT NULL,   -- generated (uuid or sensor_id+timestamp hash)
    sensor_id               TEXT NOT NULL,
    event_time              TIMESTAMP WITH TIME ZONE NOT NULL,
    latitude                NUMERIC(9,6),
    longitude               NUMERIC(9,6),

    -- Classification output
    event_type              TEXT NOT NULL,           -- 'seismic' | 'vehicle_human' | 'environmental' | 'unknown'
    confidence               NUMERIC(5,4) NOT NULL,
    severity_score            NUMERIC(5,2),

    -- Lineage / governance (mirrors the sibling text-diagnostics product's governance pattern)
    scenario_family_id        TEXT,                   -- required for family-grouped leakage checks
    raw_waveform_ref            TEXT,                  -- path/URI back to the raw source file
    human_summary                TEXT,                 -- Claude-generated plain-language summary
    split                        TEXT,                 -- 'train' | 'val' | 'test' | NULL (live/replay rows)
    source_dataset                TEXT NOT NULL,        -- 'STEAD' | 'INSTANCE' | 'own_sensor'
    data_version                  TEXT,                 -- points at a manifest version (see data/module2_vibration/manifests/)
    model_version                  TEXT,                -- points at a models/registry/<name>/metadata.json entry
    pipeline_run_id                 TEXT,               -- ties this row to one reproducible pipeline execution

    evidence                         JSONB,
    abstain                          BOOLEAN DEFAULT FALSE,
    requires_human_review            BOOLEAN DEFAULT FALSE,
    review_notes                      TEXT,

    created_at                        TIMESTAMP DEFAULT NOW(),
    geometry                          GEOMETRY(Point, 4326),

    CONSTRAINT chk_vibration_event_type CHECK (event_type IN ('seismic', 'vehicle_human', 'environmental', 'unknown')),
    CONSTRAINT chk_vibration_confidence CHECK (confidence >= 0 AND confidence <= 1),
    CONSTRAINT chk_vibration_split      CHECK (split IN ('train', 'val', 'test') OR split IS NULL)
);

CREATE INDEX IF NOT EXISTS idx_vibration_time
    ON vibration_classified_events(event_time DESC);

CREATE INDEX IF NOT EXISTS idx_vibration_sensor
    ON vibration_classified_events(sensor_id, event_time DESC);

CREATE INDEX IF NOT EXISTS idx_vibration_family
    ON vibration_classified_events(scenario_family_id);

CREATE INDEX IF NOT EXISTS idx_vibration_geometry
    ON vibration_classified_events USING GIST(geometry);

CREATE INDEX IF NOT EXISTS idx_vibration_review
    ON vibration_classified_events(requires_human_review)
    WHERE requires_human_review = TRUE;

INSERT INTO schema_migrations (version, description)
VALUES ('1.1.0', 'Module 2: vibration_classified_events (ML-classified waveform events, additive)')
ON CONFLICT (version) DO NOTHING;
