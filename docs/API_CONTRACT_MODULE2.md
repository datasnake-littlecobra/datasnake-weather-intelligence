# Module 2 (Seismic/Vibration Intelligence) — API Contract

**Status:** v1, Phase 1 (DataSnake sole user/admin — no multi-tenancy yet)
**Audience:** the `terrawatchapp-beta` frontend session, building the Module 2
dashboard section targeting `hyperlocalwatch.com`.

This is the handoff artifact between the two sessions working on this
feature: this repo (`datasnake-weather-intelligence`) owns the pipeline and
API; `terrawatchapp-beta` owns the dashboard UI. Neither session should need
to read the other's source to integrate — this doc plus the live
`openapi.json` should be enough.

---

## 1. Not the same thing as `risk_scores_cache`

This repo already has a different, older concept: `risk_scores_cache` /
`GET /api/v1/risk-verdict` (aggregated risk scores per location/peril, see
`docs/ARCHITECTURE.md`). **`/events` is unrelated** — it returns individual
classified sensor events, not aggregated risk scores. Don't conflate the two
when wiring up the frontend.

---

## 2. Base URL

```
https://<railway-app>.up.railway.app
```

(Exact subdomain assigned once deployed to Railway — see
`src/03_api_service/README.md` for the deploy steps. Independent of Vultr
and of `datasnake-fastapi-router` entirely — a deliberately separate stack.)

---

## 3. Auth

Phase 1 uses a single static API token (DataSnake is the sole user/admin —
see CLAUDE.md's phased scope). Send it as a header:

```
x-api-token: <MODULE2_API_TOKEN>
```

A per-client auth system is explicitly Phase 2 scope — not built yet.

---

## 4. CORS

Configured in `config_vibration.yaml` → `api.cors_origins`. Currently:

```
https://hyperlocalwatch.com
```

Add `terrawatchapp.com` here (new PR against `config_vibration.yaml`, a file
this repo owns) if/when the frontend cuts over to that domain — see
`terrawatchapp-beta/DEPLOY.md`'s note about the `hyperlocalwatch.com` →
`terrawatchapp.com` migration already being tracked there.

---

## 5. Endpoints

### `GET /events`

Query params (all optional):

| Param | Type | Notes |
|---|---|---|
| `event_type` | string | `seismic` \| `vehicle_human` \| `environmental` \| `unknown` |
| `requires_review` | boolean | filter to events flagged for human review |
| `limit` | int | default 50, max 500 |
| `offset` | int | default 0 |

Response:

```json
{
  "rows": [
    {
      "event_id": "uuid",
      "sensor_id": "string",
      "event_time": "2026-08-10T14:23:45Z",
      "latitude": 37.77,
      "longitude": -122.42,
      "event_type": "seismic",
      "confidence": 0.87,
      "severity_score": 42.5,
      "scenario_family_id": "stead_1234",
      "human_summary": "string, nullable",
      "source_dataset": "STEAD",
      "evidence": { "window_id": "stead_1234_0", "source_idx": 1234 },
      "abstain": false,
      "requires_human_review": false,
      "created_at": "2026-08-10T14:24:01Z"
    }
  ],
  "total": 50,
  "offset": 0,
  "limit": 50
}
```

### `GET /events/{event_id}`

Same row shape as above, single object. `404` if not found.

### `GET /health`

`{"status": "ok"}` — no auth required, for uptime checks.

---

## 6. Known Phase 1 limitations to design the UI around

- **`vehicle_human` classification is not yet trained.** STEAD/INSTANCE don't
  supply labeled examples for it (see `src/02_ml_pipeline/gold_label_split.py`
  docstring). Events of this type won't appear with real confidence yet —
  don't build a UI that assumes all 4 classes are equally populated.
- **Data is replayed public data, not a live sensor feed.** `sensor_id`
  values look like `replay:stead` / `replay:instance` in Phase 1, not real
  hardware sensor IDs — a simple tabular view (matching the existing
  `datasnake.io/datapreview` style) is the right fidelity level for now, not
  a "live" real-time indicator.
- **`abstain: true` rows currently dominate** until a real model is wired
  into `src/02_ml_pipeline/replay_pipeline.py`'s `classify_window()` — treat
  these as "pipeline ran, no confident classification yet," not an error
  state, when designing empty/low-confidence UI states.

---

## 7. Machine-readable contract

Once deployed, the live OpenAPI schema is available at:

```
GET /openapi.json
```

Prefer this over hand-parsing this doc for anything client-generation-adjacent
(TypeScript types, etc.) — this doc is the narrative context, `/openapi.json`
is the source of truth for exact field types.

---

## 8. Versioning

- **v1** (this doc) — initial contract, Phase 1 scope only.
- Future revisions are PRs against this file, same convention as
  `terrawatchapp-beta/docs/DATASNAKE_SENSOR_DATA_CONTRACT.md`.
