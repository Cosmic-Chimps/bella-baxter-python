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


def load_bella_secrets(app: Flask) -> None:
    """
    Fetch all secrets from Bella Baxter and inject them into os.environ.

    Called once during app factory creation — before Flask config is read,
    so Flask's app.config['KEY'] = os.environ.get('KEY') pattern works normally.
    """
    client = BaxterClient(BaxterClientOptions(
        baxter_url=os.environ.get("BELLA_BAXTER_URL", "http://localhost:5000"),
        api_key=os.environ.get("BELLA_API_KEY", ""),
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

    # Load secrets BEFORE Flask config so os.environ is populated
    if os.environ.get("BELLA_API_KEY"):
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
