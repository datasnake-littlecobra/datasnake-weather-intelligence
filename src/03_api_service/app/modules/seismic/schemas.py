"""Seismic-specific Pydantic models. Isolated here rather than in the
shared routers/ layer, per the module-agnostic route principle."""

from typing import Optional

from pydantic import BaseModel


class ClassificationResult(BaseModel):
    event_type: str  # 'seismic' | 'vehicle_human' | 'environmental' | 'unknown'
    confidence: float
    severity_score: Optional[float] = None
    abstain: bool = False
    requires_human_review: bool = False
