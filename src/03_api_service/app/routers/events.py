"""Module-agnostic event routes.

GET /events and GET /events/{id} read from vibration_classified_events today,
but nothing here is seismic-specific — no event-type enums, no classifier
calls, no waveform handling. Per CLAUDE.md's pluggable-module principle,
Modules 3/4 (coastal visual, infrastructure condition) should be able to add
their own event tables and reuse these same routes without touching this
file, as long as their output conforms to the shared governance shape
(evidence, confidence, abstain, requires_human_review, scenario_family_id).

Seismic-specific logic lives in app/modules/seismic/, not here.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..core.auth import require_api_token
from ..core.db import get_db

router = APIRouter(dependencies=[Depends(require_api_token)])

EVENTS_QUERY = """
    SELECT event_id, sensor_id, event_time, latitude, longitude, event_type,
           confidence, severity_score, scenario_family_id, human_summary,
           source_dataset, evidence, abstain, requires_human_review, created_at
    FROM vibration_classified_events
    WHERE (:event_type IS NULL OR event_type = :event_type)
      AND (:requires_review IS NULL OR requires_human_review = :requires_review)
    ORDER BY event_time DESC
    LIMIT :limit OFFSET :offset
"""

EVENT_BY_ID_QUERY = """
    SELECT event_id, sensor_id, event_time, latitude, longitude, event_type,
           confidence, severity_score, scenario_family_id, human_summary,
           source_dataset, evidence, abstain, requires_human_review, created_at
    FROM vibration_classified_events
    WHERE event_id = :event_id
"""


@router.get("/events")
def list_events(
    event_type: Optional[str] = None,
    requires_review: Optional[bool] = None,
    limit: int = Query(default=50, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        text(EVENTS_QUERY),
        {"event_type": event_type, "requires_review": requires_review, "limit": limit, "offset": offset},
    ).mappings().all()
    return {"rows": [dict(r) for r in rows], "total": len(rows), "offset": offset, "limit": limit}


@router.get("/events/{event_id}")
def get_event(event_id: str, db: Session = Depends(get_db)):
    row = db.execute(text(EVENT_BY_ID_QUERY), {"event_id": event_id}).mappings().first()
    if row is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Event not found")
    return dict(row)
