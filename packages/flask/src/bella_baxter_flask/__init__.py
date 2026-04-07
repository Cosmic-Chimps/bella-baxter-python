"""
bella-baxter-flask — Flask extension for the Bella Baxter secret management SDK.

Usage::

    from flask import Flask
    from bella_baxter_flask import BellaBaxter

    app = Flask(__name__)
    bella = BellaBaxter(app, api_key='bax-...')

    @app.route('/health')
    def health():
        secrets = app.bella.get_all_secrets()
        return {'database': secrets.secrets.get('DATABASE_URL')}

Or use the application factory pattern::

    # extensions.py
    from bella_baxter_flask import BellaBaxter
    bella = BellaBaxter()

    # app.py
    from extensions import bella

    def create_app():
        app = Flask(__name__)
        app.config['BELLA_BAXTER_API_KEY'] = 'bax-...'
        bella.init_app(app)
        return app

    # Then in routes:
    from extensions import bella
    secrets = bella.get_all_secrets()
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask import Flask
    from bella_baxter import BaxterClient, AllEnvironmentSecretsResponse


class BellaBaxter:
    """
    Flask extension that attaches a BaxterClient to the Flask application.

    Supports both direct initialisation and the application factory pattern.
    The client is available as ``app.bella`` after initialisation.
    """

    def __init__(
        self,
        app: "Flask | None" = None,
        api_key: str | None = None,
        baxter_url: str = "https://api.bella-baxter.io",
    ) -> None:
        self._api_key = api_key
        self._baxter_url = baxter_url
        self._client: "BaxterClient | None" = None

        if app is not None:
            self.init_app(app)

    def init_app(self, app: "Flask") -> None:
        """
        Attach the extension to a Flask application.

        Reads from ``app.config`` if ``api_key`` was not provided to the constructor:
        - ``BELLA_BAXTER_API_KEY`` (required)
        - ``BELLA_BAXTER_URL`` (optional)
        - ``BELLA_BAXTER_PRIVATE_KEY`` (optional, ZKE — also read from env var)
        """
        import os
        from bella_baxter import BaxterClient, BaxterClientOptions

        api_key = self._api_key or app.config.get("BELLA_BAXTER_API_KEY")
        if not api_key:
            raise RuntimeError(
                "Bella Baxter API key not set. "
                "Pass api_key= to BellaBaxter() or set BELLA_BAXTER_API_KEY in app.config."
            )

        baxter_url = self._baxter_url or app.config.get(
            "BELLA_BAXTER_URL", "https://api.bella-baxter.io"
        )

        private_key: str | None = (
            os.environ.get("BELLA_BAXTER_PRIVATE_KEY")
            or app.config.get("BELLA_BAXTER_PRIVATE_KEY")
        )

        self._client = BaxterClient(
            BaxterClientOptions(
                baxter_url=baxter_url,
                api_key=api_key,
                private_key=private_key,
            )
        )

        app.bella = self  # type: ignore[attr-defined]
        app.extensions["bella_baxter"] = self

    def get_all_secrets(
        self,
        project_slug: str | None = None,
        env_slug: str | None = None,
    ) -> "AllEnvironmentSecretsResponse":
        """Fetch all secrets synchronously."""
        return self._require_client().get_all_secrets(project_slug, env_slug)

    @property
    def client(self) -> "BaxterClient":
        """The underlying BaxterClient for direct API access."""
        return self._require_client()

    def _require_client(self) -> "BaxterClient":
        if self._client is None:
            raise RuntimeError(
                "BellaBaxter extension is not initialised. "
                "Call init_app(app) before using the extension."
            )
        return self._client

    def __getattr__(self, name: str):
        # Proxy unknown attributes to the underlying client
        return getattr(self._require_client(), name)


__all__ = ["BellaBaxter"]
