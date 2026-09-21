"""
Flask sample — loads Bella Baxter secrets at app startup using the SDK.

The BaxterClient is called once in the app factory and secrets are written
to os.environ so Flask config, SQLAlchemy, and all libraries pick them up.

Start:
    BELLA_API_KEY=bella_ak_xxx BELLA_SECRET_KEY=sk_xxx flask run
    # or:
    BELLA_API_KEY=bella_ak_xxx BELLA_SECRET_KEY=sk_xxx gunicorn app:create_app()
"""

import os
import logging

from flask import Flask, jsonify
from bella_baxter import BaxterClient, BaxterClientOptions

logger = logging.getLogger(__name__)


def _bella_api_key() -> str:
    """The credential `bella sdk run` injects, canonical name first."""
    return os.environ.get("BELLA_BAXTER_API_KEY") or os.environ.get("BELLA_API_KEY", "")


def load_bella_secrets(app: Flask) -> None:
    """
    Fetch all secrets from Bella Baxter and inject them into os.environ.

    Called once during app factory creation — before Flask config is read,
    so Flask's app.config['KEY'] = os.environ.get('KEY') pattern works normally.
    """
    client = BaxterClient(BaxterClientOptions(
        baxter_url=os.environ.get("BELLA_BAXTER_URL", "http://localhost:5000"),
        # #733: BELLA_BAXTER_API_KEY is the canonical name `bella sdk run` injects;
        # BELLA_API_KEY is the deprecated alias it also sets.
        api_key=_bella_api_key(),
    ))

    try:
        resp = client.get_all_secrets()
        for key, value in resp.secrets.items():
            os.environ[key] = value
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


def create_app() -> Flask:
    """Application factory."""

    # Load secrets BEFORE Flask config so os.environ is populated.
    #
    # #733: this used to be a bare `if BELLA_API_KEY:` with no else, so with no credential the
    # app started, served the fallback values below, and said nothing. That is precisely what
    # `bella sdk run` produces under an OAuth session — it injects BELLA_BAXTER_ACCESS_TOKEN and
    # no api key — so the most likely way to run the sample was also the way it silently did
    # nothing. A sample whose subject is loading secrets must refuse to start without them.
    if not _bella_api_key():
        raise RuntimeError(
            "No Bella credential in the environment. Set BELLA_BAXTER_API_KEY, or run this under "
            "`bella sdk run -- flask run` with an API key — an OAuth session injects an access "
            "token and no api key, which this sample cannot use."
        )
    load_bella_secrets(Flask(__name__))

    app = Flask(__name__)

    # Flask config reads from os.environ (already populated by load_bella_secrets)
    app.config["DATABASE_URL"] = os.environ.get("DATABASE_URL")
    app.config["SECRET_KEY"]   = os.environ.get("FLASK_SECRET_KEY", "dev-fallback")

    # ── Routes ────────────────────────────────────────────────────────────────

    @app.get("/")
    def index():
        db = app.config.get("DATABASE_URL") or "(not set)"
        return jsonify({
            "message": "Hello from Bella Baxter + Flask",
            "db": db[:20] + "***" if len(db) > 20 else db,
        })

    @app.get("/health")
    def health():
        return jsonify({"ok": True})

    @app.get("/secrets")
    def secrets():
        keys = [
            "PORT", "DATABASE_URL", "EXTERNAL_API_KEY", "GLEAP_API_KEY",
            "ENABLE_FEATURES", "APP_ID", "ConnectionStrings__Postgres", "APP_CONFIG",
        ]
        return jsonify({k: os.environ.get(k, "") for k in keys})

    return app


# Allow running directly: python app.py
if __name__ == "__main__":
    create_app().run(port=int(os.environ.get("PORT", 5000)), debug=True)
