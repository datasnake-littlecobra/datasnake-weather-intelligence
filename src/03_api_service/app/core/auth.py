"""Phase 1 auth stub: a single static API token, read from the environment.

DataSnake is the sole user/admin in Phase 1 (see CLAUDE.md's phased scope —
no multi-tenancy, no client sign-up). This is intentionally minimal: a
per-client auth system is explicitly Phase 2 scope, not built here.
"""

import os

from fastapi import Header, HTTPException


def require_api_token(x_api_token: str = Header(...)) -> None:
    expected = os.getenv("MODULE2_API_TOKEN")
    if not expected:
        raise RuntimeError("MODULE2_API_TOKEN must be set — see .env.example")
    if x_api_token != expected:
        raise HTTPException(status_code=401, detail="Invalid API token")
