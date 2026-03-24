"""
FastAPI sample — loads Bella Baxter secrets at startup using the async SDK.

Uses FastAPI's `lifespan` context manager (the modern pattern, replaces on_event).
Secrets are available in os.environ AND as app.state.secrets for dependency injection.

Start:
    BELLA_API_KEY=bella_ak_xxx BELLA_SECRET_KEY=sk_xxx uvicorn main:app --reload
"""

import os
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Depends, Request
from bella_baxter import BaxterClient, BaxterClientOptions

logger = logging.getLogger(__name__)


# ── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    FastAPI lifespan — runs at startup and shutdown.

    Bella Baxter secrets are loaded once here and stored in:
    - os.environ          → for libraries that read env vars (SQLAlchemy, etc.)
    - app.state.secrets   → for route-level dependency injection
    """
    api_key    = os.environ.get("BELLA_API_KEY", "")
    baxter_url = os.environ.get("BELLA_BAXTER_URL", "http://localhost:5000")

    secrets: dict[str, str] = {}

    if api_key:
        async with BaxterClient(BaxterClientOptions(
            baxter_url=baxter_url,
            api_key=api_key,
        )) as client:
            try:
                resp = await client.get_all_secrets_async()
                secrets = resp.secrets
                os.environ.update(secrets)
                ctx = client.get_key_context()
                logger.info(
                    "BellaSecrets: loaded %d secret(s) from project '%s' / environment '%s'",
                    len(secrets),
                    ctx.get("projectSlug", ""),
                    ctx.get("environmentSlug", ""),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("BellaSecrets: failed to load secrets — %s", exc)
                # Continue without secrets — app may have fallback values
    else:
        logger.debug("BellaSecrets: BELLA_API_KEY not set — skipping")

    # Store in app.state for dependency injection
    app.state.secrets = secrets

    yield  # ← app is running; requests are handled here

    # Cleanup (if needed)
    logger.info("BellaSecrets: shutting down")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Bella Baxter + FastAPI Sample",
    lifespan=lifespan,
)


# ── Dependency: typed secret access ──────────────────────────────────────────

def get_secrets(request: Request) -> dict[str, str]:
    """FastAPI dependency — returns the loaded secrets dict."""
    return request.app.state.secrets


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/")
async def root(secrets: dict[str, str] = Depends(get_secrets)):
    db = secrets.get("DATABASE_URL") or os.environ.get("DATABASE_URL", "(not set)")
    return {
        "message": "Hello from Bella Baxter + FastAPI",
        "db": db[:20] + "***" if len(db) > 20 else db,
        "secrets_count": len(secrets),
    }


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/secrets")
async def get_all_secrets(secrets: dict[str, str] = Depends(get_secrets)):
    keys = [
        "PORT", "DATABASE_URL", "EXTERNAL_API_KEY", "GLEAP_API_KEY",
        "ENABLE_FEATURES", "APP_ID", "ConnectionStrings__Postgres", "APP_CONFIG",
    ]
    return {k: secrets.get(k) or os.environ.get(k, "") for k in keys}


@app.get("/config/{key}")
async def get_config(key: str, secrets: dict[str, str] = Depends(get_secrets)):
    """Demo: look up a specific secret by key."""
    value = secrets.get(key) or os.environ.get(key)
    if value is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Secret '{key}' not found")
    # Mask value in response
    masked = value[:4] + "***" if len(value) > 6 else "***"
    return {"key": key, "value": masked}
