"""Module 2 FastAPI service entrypoint.

Deployed to Railway (git-push deploy), independent of the Vultr-hosted
datasnake-fastapi-router — a deliberately separate stack per the current
plan, not a competing/duplicate deployment of that service.

Run locally:
    uvicorn app.main:app --reload --port 8000
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.config import get_config
from .routers import events

cfg = get_config()

app = FastAPI(title="DataSnake Module 2 — Vibration Intelligence API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=cfg["api"]["cors_origins"],
    allow_methods=["GET"],
    allow_headers=["x-api-token"],
)

app.include_router(events.router)


@app.get("/health")
def health():
    return {"status": "ok"}
