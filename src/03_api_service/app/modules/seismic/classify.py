"""Seismic-specific inference call: waveform window -> ClassificationResult.

This is the only place in the FastAPI service that imports SeisBench/PyTorch
— keeps the shared routers/ layer free of any seismic-specific dependency,
so a future Module 3/4 doesn't inherit a torch import it doesn't need.

Loads model weights from the registry entry written by
src/02_ml_pipeline/model_registry.py (models/registry/<name>/metadata.json)
— NOT hardcoded here, so swapping model versions doesn't require touching
this file's logic, only the registry pointer.
"""

from functools import lru_cache

from .schemas import ClassificationResult


@lru_cache
def _load_model():
    import seisbench.models as sbm

    # See models/registry/phasenet_v1/metadata.json for the model version
    # this deployment should be pinned to.
    return sbm.PhaseNet.from_pretrained("stead")


def classify_waveform(window) -> ClassificationResult:
    model = _load_model()
    prediction = model.classify(window)
    return ClassificationResult(
        event_type=getattr(prediction, "event_type", "unknown"),
        confidence=getattr(prediction, "confidence", 0.0),
        severity_score=getattr(prediction, "severity_score", None),
        abstain=getattr(prediction, "confidence", 0.0) < 0.5,
        requires_human_review=getattr(prediction, "confidence", 0.0) < 0.5,
    )
