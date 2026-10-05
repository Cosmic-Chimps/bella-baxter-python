"""E2EETransport — httpx transport wrapper that adds E2EE to the envelope-required secret reads."""

from __future__ import annotations

import json
from typing import Optional

import httpx

from .e2ee import (
    E2EE_DECRYPTION_FAILED,
    E2EE_PLAINTEXT_RESPONSE,
    E2EEncryptedPayload,
    E2EEResponseError,
    E2EKeyPair,
    requires_envelope,
)


def _decrypt_plaintext(envelope: dict, e2ee: E2EKeyPair) -> bytes:
    """The envelope's plaintext bytes, exactly as the server serialized them."""
    return e2ee.decrypt_raw(E2EEncryptedPayload.from_dict(envelope))


def _is_all_environment_secrets(path: str) -> bool:
    """``…/api/v1/projects/{p}/environments/{e}/secrets`` — getAllEnvironmentSecrets."""
    marker = "/api/v1/projects/"
    i = path.find(marker)
    if i < 0:
        return False
    segs = path[i + len(marker):].rstrip("/").split("/")
    return len(segs) == 4 and segs[1] == "environments" and segs[3] == "secrets"


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


# Headers that describe the body that came off the WIRE, not the plaintext one we substitute.
#
# `content-encoding` is the one that breaks callers: a CDN in front of the API compresses the
# response (Cloudflare sends `content-encoding: br` whenever httpx's default `Accept-Encoding` is
# present), httpx transparently decompresses it when we read `.content`, and we then hand back a
# PLAINTEXT body. Carrying the original header forward tells httpx's decoder to decompress it a
# second time, which fails with "Error -3 while decompressing data: incorrect header check".
#
# `content-length` and `transfer-encoding` describe the wire body's framing for the same reason.
# httpx recomputes the length from the content we pass.
_WIRE_BODY_HEADERS = frozenset({"content-encoding", "content-length", "transfer-encoding"})


def _headers_for_decrypted_body(headers: httpx.Headers) -> httpx.Headers:
    """
    Drop the headers that describe the encrypted wire body, keep everything else.

    Everything else matters: `X-Bella-Wrapped-Dek` and `X-Bella-Lease-Expires` are read by callers,
    and `multi_items()` is used rather than `dict()` so repeated headers survive.
    """
    return httpx.Headers(
        [(name, value) for name, value in headers.multi_items() if name.lower() not in _WIRE_BODY_HEADERS]
    )


def _decrypt_response(
    response: httpx.Response,
    e2ee: E2EKeyPair,
    raw_content: bytes,
    path: str,
    envelope_required: bool,
) -> httpx.Response:
    """Decrypt the E2EE-encrypted response body and return a new plain response.

    #1050 — when ``envelope_required`` (the key was presented on a read the server encrypts), anything
    but a decryptable envelope raises :class:`E2EEResponseError`: plain JSON or a non-JSON body is
    ``e2ee-plaintext-response``; an envelope that will not decrypt (tampered, another key, a missing
    field) is ``e2ee-decryption-failed``. The plaintext is never returned in its place.
    """
    try:
        data = json.loads(raw_content)
    except (ValueError, UnicodeDecodeError) as err:
        if envelope_required:
            raise E2EEResponseError(E2EE_PLAINTEXT_RESPONSE, path) from err
        return response

    if not isinstance(data, dict) or data.get("encrypted") is not True:
        if envelope_required:
            raise E2EEResponseError(E2EE_PLAINTEXT_RESPONSE, path)
        return response

    try:
        plaintext = _decrypt_plaintext(data, e2ee)
        decrypted = json.loads(plaintext.decode("utf-8"))
    except Exception as err:  # noqa: BLE001 — every decryption failure is the same refusal
        raise E2EEResponseError(E2EE_DECRYPTION_FAILED, path) from err

    # #1162 — the plaintext of every envelope-required read is the JSON the server would have sent
    # without a key (a secret item, an array of them, a {key: value} export, ListGlobalSecretsResponse),
    # so it is handed on byte for byte. Only getAllEnvironmentSecrets keeps its legacy rescue: a server
    # that encrypted just the flat {key: value} dict is re-wrapped as an AllEnvironmentSecretsResponse.
    # Wrapping anything else would decrypt correctly and still return the wrong thing.
    if _is_all_environment_secrets(path) and not (
        isinstance(decrypted, dict) and isinstance(decrypted.get("secrets"), dict)
    ):
        if not isinstance(decrypted, dict):
            raise E2EEResponseError(E2EE_DECRYPTION_FAILED, path)
        new_body = json.dumps(
            {"secrets": decrypted, "version": 0, "environmentSlug": "", "environmentName": "", "lastModified": ""}
        ).encode()
    else:
        new_body = plaintext

    return httpx.Response(
        status_code=response.status_code,
        headers=_headers_for_decrypted_body(response.headers),
        content=new_body,
    )


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
    Synchronous httpx transport that transparently handles E2EE for the envelope-required secret reads.

    On outbound: adds X-E2E-Public-Key header so the server encrypts the response.
    On inbound:  decrypts the encrypted payload and reconstructs a normal JSON response. Having
                 presented the key, a 2xx answer to an envelope-required read that is plaintext, or an
                 envelope that will not decrypt, raises :class:`E2EEResponseError` (#1050).
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
        # #1162 — the key is presented on every envelope-required read (SDK_CONTRACT.md, "Rule: the key
        # is presented on every envelope-required read"), decided here by the one matcher, never per method.
        presented = requires_envelope(request.method, request.url.path)

        if presented:
            request = _add_e2ee_header(request, self._e2ee.public_key_b64)

        response = self._wrapped.handle_request(request)

        if presented and response.is_success:
            response.read()
            decrypted = _decrypt_response(
                response,
                self._e2ee,
                response.content,
                request.url.path,
                envelope_required=True,
            )
            # Only after the body was accepted: a refused answer's wrapped DEK is not cached.
            if self._on_wrapped_dek:
                _fire_wrapped_dek_callback(request, response, self._on_wrapped_dek)
            response = decrypted

        return response


class AsyncE2EETransport(httpx.AsyncBaseTransport):
    """
    Async httpx transport that transparently handles E2EE for the envelope-required secret reads.

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
        # #1162 — the key is presented on every envelope-required read (SDK_CONTRACT.md, "Rule: the key
        # is presented on every envelope-required read"), decided here by the one matcher, never per method.
        presented = requires_envelope(request.method, request.url.path)

        if presented:
            request = _add_e2ee_header(request, self._e2ee.public_key_b64)

        response = await self._wrapped.handle_async_request(request)

        if presented and response.is_success:
            await response.aread()
            decrypted = _decrypt_response(
                response,
                self._e2ee,
                response.content,
                request.url.path,
                envelope_required=True,
            )
            # Only after the body was accepted: a refused answer's wrapped DEK is not cached.
            if self._on_wrapped_dek:
                _fire_wrapped_dek_callback(request, response, self._on_wrapped_dek)
            response = decrypted

        return response
