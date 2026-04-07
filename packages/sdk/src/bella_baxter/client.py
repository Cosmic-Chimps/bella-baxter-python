"""BaxterClient — HTTP client for the Bella Baxter API backed by Kiota."""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import hmac as hmac_mod
import os
from datetime import datetime, timezone

import httpx

from .models import (
    BaxterClientOptions,
    AllEnvironmentSecretsResponse,
    EnvironmentSecretsVersionResponse,
)
from .hmac_auth_provider import HmacAuthProvider
from .e2ee_httpx_transport import E2EETransport, AsyncE2EETransport

try:
    from .generated.bella_client import BellaClient
    from kiota_http.httpx_request_adapter import HttpxRequestAdapter
    _KIOTA_AVAILABLE = True
except ImportError:
    _KIOTA_AVAILABLE = False


class BaxterClient:
    """
    Thread-safe Bella Baxter API client backed by the Kiota-generated BellaClient.

    Instantiate once and reuse across requests.

    Example::

        client = BaxterClient(BaxterClientOptions(
            baxter_url="https://api.bella-baxter.io",
            api_key="bax-...",
        ))
        resp = client.get_all_secrets()
        db_url = resp.secrets["DATABASE_URL"]

    Prerequisites: run ``apps/sdk/generate.sh`` to generate ``src/bella_baxter/generated/`` first.
    """

    def __init__(self, options: BaxterClientOptions) -> None:
        # Auto-read ZKE private key from env var if not set directly
        private_key = options.private_key or os.environ.get("BELLA_BAXTER_PRIVATE_KEY")
        if private_key and not options.private_key:
            options = dataclasses.replace(options, private_key=private_key)

        self._options = options
        self._key_context: dict | None = None

        if not _KIOTA_AVAILABLE:
            raise ImportError(
                "Kiota client not found. Run apps/sdk/generate.sh to generate the client first."
            )

        auth = HmacAuthProvider(options.api_key)
        async_client = httpx.AsyncClient(
            transport=AsyncE2EETransport(
                httpx.AsyncHTTPTransport(),
                private_key=options.private_key,
                on_wrapped_dek_received=options.on_wrapped_dek_received,
            ),
            headers={"User-Agent": "bella-python-sdk/1.0", "X-Bella-Client": "bella-python-sdk"},
        )
        adapter = HttpxRequestAdapter(auth, http_client=async_client)
        adapter.base_url = options.baxter_url.rstrip("/")
        self._kiota = BellaClient(adapter)

    # ── Key context (auto-discovery) ───────────────────────────────────────────

    def get_key_context(self) -> dict:
        """
        GET /api/v1/keys/me — discover project + environment from the API key.

        The result is cached; subsequent calls return the cached value.
        """
        if self._key_context is None:
            parts = self._options.api_key.split("-", 2)
            key_id = parts[1]
            signing_secret = bytes.fromhex(parts[2])

            path = "/api/v1/keys/me"
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            body_hash = hashlib.sha256(b"").hexdigest()
            string_to_sign = f"GET\n{path}\n\n{timestamp}\n{body_hash}"
            sig = hmac_mod.new(signing_secret, string_to_sign.encode(), hashlib.sha256).hexdigest()

            resp = httpx.get(
                self._options.baxter_url.rstrip("/") + path,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "bella-python-sdk/1.0",
                    "X-Bella-Client": "bella-python-sdk",
                    "X-Bella-Key-Id": key_id,
                    "X-Bella-Timestamp": timestamp,
                    "X-Bella-Signature": sig,
                },
            )
            resp.raise_for_status()
            self._key_context = resp.json()
        return self._key_context

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_all_secrets(
        self,
        project_slug: str | None = None,
        env_slug: str | None = None,
    ) -> AllEnvironmentSecretsResponse:
        """
        Fetch all secrets synchronously (for use in Flask, Django, scripts, etc.).
        E2EE decryption is handled transparently by the httpx transport.
        """
        return asyncio.run(self.get_all_secrets_async(project_slug, env_slug))

    async def get_all_secrets_async(
        self,
        project_slug: str | None = None,
        env_slug: str | None = None,
    ) -> AllEnvironmentSecretsResponse:
        """
        Fetch all secrets asynchronously (for use in FastAPI, async frameworks).
        E2EE decryption is handled transparently by the httpx transport.

        If project_slug or env_slug are not provided, they are auto-discovered
        from the API key via GET /api/v1/keys/me.
        """
        ctx = self.get_key_context()
        project_slug = project_slug or ctx["projectSlug"]
        env_slug = env_slug or ctx["environmentSlug"]

        resp = await (
            self._kiota.api.v1.projects.by_id(project_slug)
            .environments.by_env_slug(env_slug)
            .secrets.get()
        )
        secrets = {k: str(v) for k, v in (resp.secrets.additional_data or {}).items()}
        return AllEnvironmentSecretsResponse(
            environment_slug=resp.environment_slug or env_slug,
            environment_name=resp.environment_name or "",
            secrets=secrets,
            version=resp.version or 0,
            last_modified=str(resp.last_modified or ""),
        )

    def get_secrets_version(
        self,
        project_slug: str | None = None,
        env_slug: str | None = None,
    ) -> EnvironmentSecretsVersionResponse:
        """Lightweight version check — synchronous wrapper."""
        return asyncio.run(self.get_secrets_version_async(project_slug, env_slug))

    async def get_secrets_version_async(
        self,
        project_slug: str | None = None,
        env_slug: str | None = None,
    ) -> EnvironmentSecretsVersionResponse:
        """
        Lightweight version check — returns version + lastModified only.

        If project_slug or env_slug are not provided, they are auto-discovered
        from the API key via GET /api/v1/keys/me.
        """
        ctx = self.get_key_context()
        project_slug = project_slug or ctx["projectSlug"]
        env_slug = env_slug or ctx["environmentSlug"]

        resp = await (
            self._kiota.api.v1.projects.by_id(project_slug)
            .environments.by_env_slug(env_slug)
            .secrets.version.get()
        )
        return EnvironmentSecretsVersionResponse(
            environment_slug=resp.environment_slug,
            version=resp.version or 0,
            last_modified=str(resp.last_modified or ""),
        )

    @property
    def client(self) -> "BellaClient":
        """The underlying Kiota client for full API access (TOTP, projects, providers, etc.)"""
        return self._kiota

    # Context-manager support
    def __enter__(self) -> "BaxterClient":
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def close(self) -> None:
        pass

    async def __aenter__(self) -> "BaxterClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        pass
