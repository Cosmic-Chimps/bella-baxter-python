"""
Django AppConfig — loads Bella Baxter secrets in ready().

ready() is Django's hook for one-time startup initialization.
It runs exactly once per Python process (per Gunicorn/uWSGI worker),
making it the correct place to load secrets.

Add to settings.py INSTALLED_APPS:
    'myapp.apps.BaxterConfig',      # instead of 'myapp'
"""

import os
import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class BaxterConfig(AppConfig):
    """
    AppConfig that loads Bella Baxter secrets before Django starts.

    Replace 'myapp' in INSTALLED_APPS with 'myapp.apps.BaxterConfig'.
    """
    name = "myapp"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        """Called once per Django process after all apps are loaded."""
        self._load_bella_secrets()

    def _load_bella_secrets(self) -> None:  # noqa: PLR6301
        """Fetch secrets and inject into os.environ."""
        api_key    = os.environ.get("BELLA_API_KEY")
        secret_key = os.environ.get("BELLA_SECRET_KEY")

        if not api_key:
            logger.debug("BellaSecrets: BELLA_API_KEY not set — skipping")
            return

        # Import here to avoid circular imports / import errors during startup
        from bella_baxter import BaxterClient, BaxterClientOptions  # noqa: PLC0415

        baxter_url = os.environ.get("BELLA_BAXTER_URL", "http://localhost:5000")

        client = BaxterClient(BaxterClientOptions(
            baxter_url=baxter_url,
            api_key=api_key,
        ))

        try:
            resp = client.get_all_secrets()
            for key, value in resp.secrets.items():
                os.environ[key] = value
                # Also update django.conf.settings if it's already been loaded
                try:
                    from django.conf import settings  # noqa: PLC0415
                    if hasattr(settings, key):
                        setattr(settings, key, value)
                except Exception:  # noqa: BLE001
                    pass
            ctx = client.get_key_context()
            logger.info(
                "BellaSecrets: loaded %d secret(s) from project '%s' / environment '%s'",
                len(resp.secrets),
                ctx.get("projectSlug", ""),
                ctx.get("environmentSlug", ""),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("BellaSecrets: failed to load secrets — %s", exc)
        finally:
            client.close()
