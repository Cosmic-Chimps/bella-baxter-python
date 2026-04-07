"""E2EETransport — httpx transport wrapper that adds E2EE to GET /secrets requests."""

from __future__ import annotations

import json
from typing import Optional

import httpx

from .e2ee import E2EKeyPair, maybe_decrypt, maybe_decrypt_raw


def _add_e2ee_header(request: httpx.Request, public_key_b64: str) -> httpx.Request:
    """Return a new request with X-E2E-Public-Key header added."""
    headers = dict(request.headers)
    headers["X-E2E-Public-Key"] = public_key_b64
    return httpx.Request(
        method=request.method,
        url=request.url,
        headers=headers,
        content=request.content,
    )


def _decrypt_response(response: httpx.Response, e2ee: E2EKeyPair, raw_content: bytes) -> httpx.Response:
    """Decrypt the E2EE-encrypted response body and return a new plain response."""
    import json as _json
    data = _json.loads(raw_content)
    if data.get("encrypted"):
        decrypted = maybe_decrypt_raw(data, e2ee)
        if "secrets" in decrypted and isinstance(decrypted.get("secrets"), dict):
            new_body = _json.dumps(decrypted).encode()
        else:
            secrets = maybe_decrypt(data, e2ee)
            new_body = _json.dumps({"secrets": secrets, "version": 0, "environmentSlug": "", "environmentName": "", "lastModified": ""}).encode()
        return httpx.Response(
            status_code=response.status_code,
            headers=response.headers,
            content=new_body,
        )
    return response


def _fire_wrapped_dek_callback(request: httpx.Request, response: httpx.Response, on_wrapped_dek) -> None:
    """Extract slugs from the URL and fire the on_wrapped_dek_received callback."""
    wrapped_dek = response.headers.get("X-Bella-Wrapped-Dek")
    lease_expires = response.headers.get("X-Bella-Lease-Expires")
    if wrapped_dek and on_wrapped_dek:
        parts = str(request.url.path).split("/")
        try:
            proj_idx = parts.index("projects") + 1
            env_idx = parts.index("environments") + 1
            project_slug = parts[proj_idx]
            env_slug = parts[env_idx]
        except (ValueError, IndexError):
            project_slug = env_slug = ""
        on_wrapped_dek(project_slug, env_slug, wrapped_dek, lease_expires)


class E2EETransport(httpx.BaseTransport):
    """
    Synchronous httpx transport that transparently handles E2EE for GET /secrets requests.

    On outbound: adds X-E2E-Public-Key header so the server encrypts the response.
    On inbound:  decrypts the encrypted payload and reconstructs a normal JSON response.
    """

    def __init__(
        self,
        wrapped: httpx.BaseTransport,
        private_key: Optional[str] = None,
        on_wrapped_dek_received=None,
    ) -> None:
        self._wrapped = wrapped
        self._e2ee = E2EKeyPair.from_pem(private_key) if private_key else E2EKeyPair()
        self._on_wrapped_dek = on_wrapped_dek_received

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        is_secrets = request.url.path.rstrip("/").endswith("/secrets") and request.method == "GET"

        if is_secrets:
            request = _add_e2ee_header(request, self._e2ee.public_key_b64)

        response = self._wrapped.handle_request(request)

        if is_secrets and response.is_success:
            response.read()
            if self._on_wrapped_dek:
                _fire_wrapped_dek_callback(request, response, self._on_wrapped_dek)
            response = _decrypt_response(response, self._e2ee, response.content)

        return response


class AsyncE2EETransport(httpx.AsyncBaseTransport):
    """
    Async httpx transport that transparently handles E2EE for GET /secrets requests.

    Used by BaxterClient when building the AsyncClient for the Kiota adapter.
    """

    def __init__(
        self,
        wrapped: httpx.AsyncBaseTransport,
        private_key: Optional[str] = None,
        on_wrapped_dek_received=None,
    ) -> None:
        self._wrapped = wrapped
        self._e2ee = E2EKeyPair.from_pem(private_key) if private_key else E2EKeyPair()
        self._on_wrapped_dek = on_wrapped_dek_received

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        is_secrets = request.url.path.rstrip("/").endswith("/secrets") and request.method == "GET"

        if is_secrets:
            request = _add_e2ee_header(request, self._e2ee.public_key_b64)

        response = await self._wrapped.handle_async_request(request)

        if is_secrets and response.is_success:
            await response.aread()
            if self._on_wrapped_dek:
                _fire_wrapped_dek_callback(request, response, self._on_wrapped_dek)
            response = _decrypt_response(response, self._e2ee, response.content)

        return response
