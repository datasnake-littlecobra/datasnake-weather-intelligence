-- TerraWatch — Module 2: Seismic/Vibration Intelligence (ground-sensor classification)
--
-- PENDING — not yet applied to the live terrawatchapp Supabase project.
-- Written to follow this project's own conventions exactly (see
-- supabase/migrations/0044_ai_model_registry.sql, 0045_ai_inference_log.sql,
-- 0002_events_ingest.sql): numbered migration, RLS enabled with an explicit
-- public-select policy, writes reserved for the service role, comment on
-- table. Once applied, this file should be committed to
-- terrawatchapp-beta/supabase/migrations/0049_vibration_classified_events.sql
-- (0048_pipeline_images.sql is the current latest).
--
-- Deliberately NOT reusing model_inference_log's generic shape — this is
-- purpose-built for Module 2's governance fields (abstain,
-- requires_human_review, scenario_family_id, data lineage). It DOES also
-- register a row in model_registry so Module 2 shows up in the existing
-- /ai-models hub for free, consistent with every other model there.
--
-- Naming note: 'seismic-vibration-ground' is deliberately distinct from the
-- existing 'seismic-insar' model (satellite deformation) — different
-- modality, same lesson as the seismic_events/vibration_classified_events
-- naming collision already resolved in datasnake-weather-intelligence.

create extension if not exists "pgcrypto";
create extension if not exists "postgis";

-- 1. Classified vibration events ---------------------------------------------

create table if not exists public.vibration_classified_events (
  event_id               uuid primary key default gen_random_uuid(),
  sensor_id               text not null,                 -- free text, e.g. 'replay:stead' — NOT an FK into
                                                            -- public.sensors (that table models real physical
                                                            -- deployment/calibration history, which doesn't
                                                            -- apply to Phase 1's replayed public-dataset data)
  event_time              timestamptz not null,
  location                geography(point, 4326),
  latitude                double precision,
  longitude               double precision,
  event_type              text not null check (event_type in ('seismic','vehicle_human','environmental','unknown')),
  confidence              double precision not null check (confidence between 0 and 1),
  severity_score          double precision,
  scenario_family_id      text not null,                 -- groups e.g. all stations recording the same
                                                            -- earthquake — used to prevent train/val/test leakage
                                                            -- upstream; carried through for traceability
  raw_waveform_ref        text,                           -- pointer back to the gold-layer window_id
  human_summary           text,
  split                   text check (split in ('train','val','test')),
  source_dataset          text not null,                  -- 'STEAD' | 'INSTANCE' | future live sensor source
  data_version             text not null,                  -- manifest version this row's data came from
  model_version            text not null,                  -- models/registry/<name>/metadata.json version
  pipeline_run_id          uuid not null,                  -- one value per replay_pipeline.py invocation
  evidence                 jsonb not null default '{}'::jsonb,
  abstain                  boolean not null default false,
  requires_human_review    boolean not null default false,
  review_notes             text,
  created_at               timestamptz not null default now(),
  unique (source_dataset, raw_waveform_ref)                -- idempotent upsert key for replay_pipeline.py
);

comment on table public.vibration_classified_events is
  'Module 2: ground-sensor vibration/seismic classification output. One row per classified waveform window. Phase 1 data is replayed public STEAD/INSTANCE samples, not a live sensor feed — see sensor_id convention above.';

create index if not exists vibration_events_event_time_idx
  on public.vibration_classified_events (event_time desc);
create index if not exists vibration_events_type_review_idx
  on public.vibration_classified_events (event_type, requires_human_review);
create index if not exists vibration_events_location_gix
  on public.vibration_classified_events using gist (location) where location is not null;
create index if not exists vibration_events_scenario_family_idx
  on public.vibration_classified_events (scenario_family_id);

alter table public.vibration_classified_events enable row level security;

drop policy if exists "vibration_events_select_public" on public.vibration_classified_events;
create policy "vibration_events_select_public"
  on public.vibration_classified_events for select
  using (true);

-- No insert/update/delete policies for anon/authenticated — writes happen
-- via replay_pipeline.py / the FastAPI service using the service role,
-- same convention as public.events' ingest-events edge function.

-- 2. Catalog entry, so this shows up in the existing /ai-models hub ----------

-- NOTE on tier/score: model_registry.score is NOT NULL (unlike accuracy_pct),
-- so a placeholder is required here. 2/10 is a deliberately conservative
-- placeholder — NOT derived from the same rubric used for the other 7
-- seeded models (that scoring doc isn't available in this session) — and
-- should be revisited by whoever owns that ranking once this model has a
-- real eval run against this project's own data. Said so explicitly in the
-- description text too, so it doesn't read as a considered ranking.
insert into public.model_registry
  (slug, name, tier, score, status, architecture, dataset_name, dataset_url, accuracy_pct, description)
values
  (
    'seismic-vibration-ground',
    'Ground Sensor Seismic/Vibration Classification',
    3, 2, 'demo',
    'PhaseNet (SeisBench pretrained)',
    'STEAD + INSTANCE',
    'https://github.com/smousavi05/STEAD',
    null,
    'Classifies ground-sensor vibration windows into seismic, vehicle/human, environmental, or unknown. Phase 1 replays public earthquake-catalog data (STEAD/INSTANCE, both CC BY 4.0) through a pretrained PhaseNet model rather than a live sensor feed. vehicle_human has no labeled training data yet — see src/02_ml_pipeline/gold_label_split.py in datasnake-weather-intelligence for the full caveat. tier/score are placeholders (see migration comment), not a considered ranking; accuracy_pct intentionally left null until a real eval run against this project''s data exists.'
  )
on conflict (slug) do nothing;
