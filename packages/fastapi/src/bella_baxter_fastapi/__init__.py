"""
bella-baxter-fastapi — FastAPI integration for the Bella Baxter secret management SDK.

Usage::

    from fastapi import FastAPI, Depends
    from bella_baxter_fastapi import init_bella, BellaDepends

    app = FastAPI()

    # Call once at startup (e.g. in a lifespan handler)
    init_bella(api_key='bax-...', baxter_url='https://api.bella-baxter.io')

    @app.get('/health')
    async def health(bella = BellaDepends):
        secrets = await bella.get_all_secrets_async()
        return {'database': secrets.secrets.get('DATABASE_URL')}

Or use the lifespan pattern::

    from contextlib import asynccontextmanager
    from bella_baxter_fastapi import init_bella, BellaDepends

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_bella(api_key=os.environ['BELLA_BAXTER_API_KEY'])
        yield

    app = FastAPI(lifespan=lifespan)
"""

from __future__ import annotations

import threading
from typing import Annotated, TYPE_CHECKING

if TYPE_CHECKING:
    from bella_baxter import BaxterClient

_lock = threading.Lock()
_client: "BaxterClient | None" = None


def init_bella(
    api_key: str,
    baxter_url: str = "https://api.bella-baxter.io",
) -> "BaxterClient":
    """
    Initialise the shared BaxterClient. Call once at application startup.

    Args:
        api_key: Bella Baxter API key (``bax-...``).
        baxter_url: Base URL of the Baxter API.

    Returns:
        The initialised BaxterClient instance.
    """
    global _client

    with _lock:
        from bella_baxter import BaxterClient, BaxterClientOptions

        _client = BaxterClient(
            BaxterClientOptions(baxter_url=baxter_url, api_key=api_key)
        )

    return _client


def _get_bella_client() -> "BaxterClient":
    if _client is None:
        raise RuntimeError(
            "Bella Baxter client is not initialised. "
            "Call `init_bella(api_key=...)` at application startup."
        )
    return _client


try:
    from fastapi import Depends

    BellaDepends = Annotated["BaxterClient", Depends(_get_bella_client)]
    """
    FastAPI dependency — inject a BaxterClient into a route handler.

    Example::

        @app.get('/secrets')
        async def get_secrets(bella: BellaDepends):
            resp = await bella.get_all_secrets_async()
            return resp.secrets
    """
except ImportError:
    BellaDepends = None  # type: ignore[assignment]


__all__ = ["init_bella", "BellaDepends"]
