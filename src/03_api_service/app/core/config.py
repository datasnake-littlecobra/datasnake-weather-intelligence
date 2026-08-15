"""Loads config_vibration.yaml the same way the rest of this repo loads
config.yaml — same pattern, separate file (see that file's header comment
for why it's kept separate from the existing config.yaml)."""

import os
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[4]
load_dotenv(ROOT / ".env")


@lru_cache
def get_config() -> dict:
    with open(ROOT / "config_vibration.yaml") as f:
        return yaml.safe_load(f)


def get_database_url() -> str:
    """Prefers the pgbouncer pooler URL — this is the first long-lived
    process in this repo holding a connection pool open, unlike the
    short-lived ingestion scripts, which use DATABASE_URL directly."""
    url = os.getenv("DATABASE_POOLER_URL") or os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_POOLER_URL or DATABASE_URL must be set — see .env.example")
    return url
