"""
Issue #730 — the E2EE transport must not carry the wire body's encoding headers onto the plaintext
body it substitutes.

THE DEFECT. A CDN in front of the API compresses the response (Cloudflare sends
`content-encoding: br` whenever httpx's default `Accept-Encoding` is present). httpx transparently
decompresses it when the transport reads `.content`, the transport decrypts that and builds a new
response with a PLAINTEXT body — but it passed `headers=response.headers` through unchanged, so the
new response still claimed to be brotli. httpx's decoder then tried to decompress plaintext and
raised `DecodingError: Error -3 while decompressing data: incorrect header check`.

It reached users because it is invisible without a compressing intermediary: against a local API, or
any server that does not compress, the header is absent and the bug cannot fire. Every Python
framework sample (Django, Flask, FastAPI) failed on it from July.

These drive the REAL transport through a real `httpx.Client` rather than calling `_decrypt_response`
directly, because the failure happened inside httpx's decoder ON READ — a test that only inspected
the returned headers would still have passed against the broken code if it never read the body.

The decryption itself is stubbed. This SDK is decrypt-only, so producing a genuine envelope would
mean reimplementing the server's ECDH here, and #730 is about how the response is REBUILT, not about
the crypto. Stubbing keeps the test pointed at its subject.
"""

from __future__ import annotations

import gzip
import json

import httpx
import pytest

from bella_baxter import e2ee_httpx_transport
from bella_baxter.e2ee_httpx_transport import AsyncE2EETransport, E2EETransport

SECRETS_URL = "https://api.example.test/api/v1/projects/p/environments/e/secrets"
PLAINTEXT = {"secrets": {"API_KEY": "s3cr3t"}, "version": 1}


@pytest.fixture(autouse=True)
def _stub_decryption(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stand in for the server's envelope; see the module docstring for why."""
    monkeypatch.setattr(e2ee_httpx_transport, "maybe_decrypt_raw", lambda data, keypair: PLAINTEXT)
    monkeypatch.setattr(
        e2ee_httpx_transport, "maybe_decrypt", lambda data, keypair: PLAINTEXT["secrets"]
    )


class _CannedTransport(httpx.BaseTransport):
    """Returns one prepared response, standing in for the network."""

    def __init__(self, response: httpx.Response) -> None:
        self._response = response

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return self._response


class _AsyncCannedTransport(httpx.AsyncBaseTransport):
    def __init__(self, response: httpx.Response) -> None:
        self._response = response

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return self._response


def _compressed_response() -> httpx.Response:
    """A compressed response, exactly as a CDN hands one back."""
    body = gzip.compress(json.dumps({"encrypted": True}).encode())
    return httpx.Response(
        200,
        headers={
            "content-encoding": "gzip",
            "content-type": "application/json",
            "content-length": str(len(body)),
            # A header the caller genuinely needs — proves the fix drops three by name, not all.
            "X-Bella-Wrapped-Dek": "wrapped-dek-value",
        },
        content=body,
    )


def test_compressed_response_can_be_read() -> None:
    """The reported failure: reading the body raised DecodingError."""
    transport = E2EETransport(_CannedTransport(_compressed_response()))
    with httpx.Client(transport=transport) as client:
        response = client.get(SECRETS_URL)
        body = json.loads(response.read())

    assert body["secrets"]["API_KEY"] == "s3cr3t"


def test_the_rebuilt_response_does_not_claim_to_be_compressed() -> None:
    upstream = _compressed_response()
    transport = E2EETransport(_CannedTransport(upstream))
    with httpx.Client(transport=transport) as client:
        response = client.get(SECRETS_URL)
        response.read()

    assert "content-encoding" not in response.headers
    # A stale length describing the ENCRYPTED body would misframe the plaintext one.
    assert response.headers.get("content-length") != upstream.headers["content-length"]


def test_headers_the_caller_needs_survive() -> None:
    transport = E2EETransport(_CannedTransport(_compressed_response()))
    with httpx.Client(transport=transport) as client:
        response = client.get(SECRETS_URL)
        response.read()

    assert response.headers["X-Bella-Wrapped-Dek"] == "wrapped-dek-value"
    assert response.headers["content-type"] == "application/json"


def test_an_uncompressed_response_is_unaffected() -> None:
    """No intermediary, no encoding header — the path that always worked must keep working."""
    upstream = httpx.Response(
        200,
        headers={"content-type": "application/json"},
        content=json.dumps({"encrypted": True}).encode(),
    )
    transport = E2EETransport(_CannedTransport(upstream))
    with httpx.Client(transport=transport) as client:
        response = client.get(SECRETS_URL)
        body = json.loads(response.read())

    assert body["secrets"]["API_KEY"] == "s3cr3t"


def test_a_plain_unencrypted_response_passes_straight_through() -> None:
    """Not every /secrets response is encrypted; that path must not be touched at all."""
    payload = json.dumps({"secrets": {"PLAIN": "value"}}).encode()
    upstream = httpx.Response(200, headers={"content-type": "application/json"}, content=payload)

    transport = E2EETransport(_CannedTransport(upstream))
    with httpx.Client(transport=transport) as client:
        response = client.get(SECRETS_URL)
        body = json.loads(response.read())

    assert body["secrets"]["PLAIN"] == "value"


@pytest.mark.asyncio
async def test_async_transport_has_the_same_behaviour() -> None:
    """
    Both transports call the same `_decrypt_response`, so this is ONE fix — but #730 described it as
    two sites, and only running the async path proves they have not drifted.
    """
    transport = AsyncE2EETransport(_AsyncCannedTransport(_compressed_response()))
    async with httpx.AsyncClient(transport=transport) as client:
        response = await client.get(SECRETS_URL)
        body = json.loads(await response.aread())

    assert body["secrets"]["API_KEY"] == "s3cr3t"
    assert "content-encoding" not in response.headers
