"""
bella-baxter-django — Django integration for the Bella Baxter secret management SDK.

Usage::

    # settings.py
    INSTALLED_APPS = [
        ...
        'bella_baxter_django',
    ]
    BELLA_BAXTER_API_KEY = 'bax-...'
    BELLA_BAXTER_URL = 'https://api.bella-baxter.io'  # optional

    # Anywhere in your code:
    from bella_baxter_django import get_bella

    client = get_bella()
    secrets = client.get_all_secrets()
    db_url = secrets.secrets['DATABASE_URL']
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bella_baxter import BaxterClient

_lock = threading.Lock()
_client: "BaxterClient | None" = None


def get_bella() -> "BaxterClient":
    """
    Return the shared BaxterClient instance, initialising it on first call.

    Reads configuration from Django settings:
    - ``BELLA_BAXTER_API_KEY`` (required)
    - ``BELLA_BAXTER_URL`` (optional, defaults to https://api.bella-baxter.io)
    """
    global _client

    if _client is None:
        with _lock:
            if _client is None:
                from django.conf import settings
                from bella_baxter import BaxterClient, BaxterClientOptions

                api_key: str = settings.BELLA_BAXTER_API_KEY
                baxter_url: str = getattr(
                    settings,
                    "BELLA_BAXTER_URL",
                    "https://api.bella-baxter.io",
                )

                _client = BaxterClient(
                    BaxterClientOptions(baxter_url=baxter_url, api_key=api_key)
                )

    return _client


class BellaBaxterConfig:
    """
    Django AppConfig for Bella Baxter.

    Add ``'bella_baxter_django'`` to ``INSTALLED_APPS`` to enable automatic
    client initialisation on Django startup.

    Example::

        # settings.py
        INSTALLED_APPS = [
            ...
            'bella_baxter_django',
        ]
        BELLA_BAXTER_API_KEY = 'bax-...'
    """

    name = "bella_baxter_django"
    verbose_name = "Bella Baxter"

    def ready(self) -> None:
        # Eagerly initialise the client on startup so the first request
        # doesn't bear the cold-start cost.
        try:
            get_bella()
        except Exception:
            pass  # Don't crash Django startup if Bella is misconfigured


default_app_config = "bella_baxter_django.BellaBaxterConfig"

__all__ = ["get_bella", "BellaBaxterConfig"]
