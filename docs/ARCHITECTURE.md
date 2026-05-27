# DataSnake Weather Intelligence: System Architecture

**Version**: 1.0  
**Date**: May 2026  
**Purpose**: Complete system design + technical reference for the weather intelligence pipeline

---

## Executive Summary

The weather intelligence pipeline transforms public meteorological data (NOAA, USGS, FEMA) into **insurance-grade risk signals** that insurers use to make faster, more accurate underwriting decisions.

**Core claim**: Real-time, hyperlocal data beats historical, broad models.

**Proof points**: 5 use cases with quantified ROI (750:1 to 150:1).

---

## High-Level Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│ EXTERNAL DATA SOURCES (Public APIs)                         │
├─────────────────────────────────────────────────────────────┤
│ • NOAA: Weather observations, forecasts, reanalysis         │
│ • USGS: Earthquake catalog, seismic network data            │
│ • FEMA: Flood zone maps, disaster declarations              │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ DATA INGESTION LAYER (Python + PostgreSQL)                  │
├─────────────────────────────────────────────────────────────┤
│ • Fetch via REST APIs                                       │
│ • Validate + transform (pandas)                             │
│ • Deduplicate + store in PostgreSQL                         │
│ • Error handling + retry (tenacity)                         │
│ • Temporal + spatial indexing                               │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ POSTGRESQL + PostGIS DATABASE                               │
├─────────────────────────────────────────────────────────────┤
│ Tables:                                                      │
│ • weather_observations (15M+ rows/year)                     │
│ • seismic_events (1K+ events/year)                          │
│ • flood_zones (static, FEMA)                                │
│ • parametric_sensor_readings (daily per contract)           │
│ • risk_scores_cache (TTL-based)                             │
│                                                              │
│ Indexes:                                                     │
│ • Temporal (measurement_time DESC)                          │
│ • Spatial (geometry GiST)                                   │
│ • Composite (station_id + measurement_time)                 │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ RISK TRANSLATION LAYER (SQL Functions + Python)             │
├─────────────────────────────────────────────────────────────┤
│ SQL Functions:                                               │
│ • flash_flood_risk(lat, lon, hours) → risk_score            │
│ • seismic_precursor_risk(lat, lon, days) → signal           │
│ • coastal_wind_risk(lat, lon) → risk_score                  │
│ • ep_curve_flood(rainfall, saturation) → probability        │
│                                                              │
│ Python Classes:                                              │
│ • FloodRiskEngine                                            │
│ • SeismicPrecursorEngine                                     │
│ • CoastalRiskEngine                                          │
│ • EPCurveFactory                                             │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ USE CASE ENGINES (Proof-of-Value Simulators)                │
├─────────────────────────────────────────────────────────────┤
│ • UC1: Flash Flood Detection (Miami Beach, May 2024)        │
│ • UC2: Seismic Precursor Signals (Bay Area, Aug-Oct 2025)   │
│ • UC3: Parametric Trigger Certification (Bangladesh)        │
│ • UC4: Competitive Underwriting Moat (Coastal FL)           │
│ • UC5: Claims Validation (Hurricane Ian)                    │
│                                                              │
│ Output: ROI metrics + financial impact per use case         │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ REPORTING & BUSINESS LAYER                                  │
├─────────────────────────────────────────────────────────────┤
│ • Dashboard (Vue.js, dark theme, real-time)                 │
│ • PDF reports (Canva templates auto-filled)                 │
│ • Financial models (3-year revenue projections)             │
│ • Risk verdict API (for external customers)                 │
│ • Metrics export (CSV/JSON for investor decks)              │
└─────────────────────────────────────────────────────────────┘
```

---

## Database Schema

See [`data/schema/ddl.sql`](../data/schema/ddl.sql) for the full DDL.

### Core Tables

| Table | Rows/Year | Use Cases |
|---|---|---|
| `weather_observations` | 15M+ | UC1, UC4, UC5 |
| `seismic_events` | 1K–10K | UC2, UC5 |
| `flood_zones` | Static | UC1, UC4 |
| `parametric_sensor_readings` | 12 × 122 / season | UC3 |
| `risk_scores_cache` | Computed on demand | All |

### Key Indexes

- `idx_weather_time` — time-range queries on weather data
- `idx_weather_geometry` (GiST) — spatial radius queries (5km for flash flood)
- `idx_seismic_time` — frequency analysis over time windows
- `idx_seismic_geometry` (GiST) — spatial queries (100km for seismic precursor)

---

## Key Formulas

### Flash Flood EP Curve

```
P_flood = ((rainfall_mm - 40) / 100) × ((saturation - 0.3) / 0.2)
P_flood = clamp(P_flood, 0, 1)
```

| Range | Threat Level |
|---|---|
| P < 0.25 | LOW |
| 0.25 ≤ P < 0.50 | MEDIUM |
| 0.50 ≤ P < 0.75 | HIGH |
| P ≥ 0.75 | CRITICAL |

### Coastal Wind Risk

```
P_wind = ((wind_ms - 15) / 25)² × (1 + tidal_anomaly / 0.5)
```

### Seismic Precursor Anomaly

```
Anomaly% = ((current_freq - baseline_freq) / baseline_freq) × 100
Signal   = clamp(|Anomaly%| / 300, 0, 1)
```

---

## API Contracts

### Risk Verdict API (Tier 1)

```
GET /api/v1/risk-verdict?lat=25.79&lon=-80.13&peril=flood
```

```json
{
  "location": { "latitude": 25.79, "longitude": -80.13 },
  "timestamp": "2026-05-27T14:23:45Z",
  "verdict": {
    "risk_score": 58,
    "probability": 0.58,
    "threat_level": "HIGH",
    "confidence": 0.85
  },
  "breakdown": {
    "peril": "flood",
    "rainfall_mm": 45,
    "saturation": 0.42,
    "formula": "P = ((45-40)/100) × ((0.42-0.3)/0.2)"
  },
  "recommendation": "Consider flood rider; risk rising"
}
```

---

## Performance Requirements

| Query | Target | Data Volume |
|---|---|---|
| `flash_flood_risk()` | < 500ms | 5,000 obs in 5km radius |
| `seismic_precursor_risk()` | < 300ms | 1,000 events in 100km radius |
| `ep_curve_flood()` | < 10ms | Computed in-memory |
| Dashboard load | < 2s | 100+ properties |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Data ingestion | Python 3.10+ (requests, pandas, tenacity) |
| Database | PostgreSQL 14+ + PostGIS |
| Risk translation | Python (numpy, scipy) + PostgreSQL functions |
| Dashboard | Vue.js (dark theme) |
| Reporting | Jinja2 → HTML/PDF |
| Infrastructure | Vultr (Ubuntu 24.04, 4 CPU, 8GB RAM, 500GB SSD) |

---

## Roadmap

| Phase | Status | Deliverable |
|---|---|---|
| 1: Data ingestion | ✅ Complete | NOAA + USGS pipelines, PostgreSQL schema |
| 2: Risk translation | 🔲 Next | SQL functions, EP curves, Python engines |
| 3: Use case engines | 🔲 Planned | 5 proof simulators |
| 4: Reporting | 🔲 Planned | Dashboard, PDF, financial models |
| 5: Methodology | 🔲 Planned | White paper, blog series, thought leadership |
