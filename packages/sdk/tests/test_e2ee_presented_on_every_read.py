"""
#1162 — the key is presented on EVERY envelope-required read (apps/sdk/SDK_CONTRACT.md, "Rule: the key is
presented on every envelope-required read"), not only on GETs ending in ``/secrets``.

Before the fix the transport presented its key on ``getAllEnvironmentSecrets``, ``listSecrets`` and
``listGlobalSecrets`` only, so ``getSecret``, ``getSecretVersion`` and both exports reached the caller over
TLS alone. It also re-wrapped every decrypted body that was not an AllEnvironmentSecretsResponse into a
``{"secrets": …}`` object, so a single secret item or a ListGlobalSecretsResponse decrypted correctly and
still arrived as the wrong thing. The stub here answers each read with an envelope of that read's own
plaintext (the shapes the API encrypts), to whatever key was presented.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Iterator

import httpx
import pytest

from bella_baxter.e2ee_httpx_transport import AsyncE2EETransport, E2EETransport

from test_e2ee_refuses_plaintext import SENTINEL_KEY, SENTINEL_VALUE, _encrypt_for

ITEM = {
    "key": SENTINEL_KEY,
    "value": SENTINEL_VALUE,
    "description": None,
    "createdAt": "2026-01-01T00:00:00Z",
    "updatedAt": "2026-01-01T00:00:00Z",
    "type": None,
}
BASE = "/api/v1/projects/p"
ENV = f"{BASE}/environments/e"

# (operationId, path incl. query, the plaintext the server encrypts for it)
READS = [
    (
        "getAllEnvironmentSecrets",
        f"{ENV}/secrets",
        {"environmentSlug": "e", "environmentName": "e", "secrets": {SENTINEL_KEY: SENTINEL_VALUE},
         "version": 7, "lastModified": "2026-10-04T00:00:00Z"},
    ),
    ("exportEnvironmentSecrets", f"{ENV}/secrets/export?format=json", {SENTINEL_KEY: SENTINEL_VALUE}),
    ("listSecrets", f"{ENV}/providers/v/secrets", [ITEM]),
    ("exportSecrets", f"{ENV}/providers/v/secrets/export?format=dotenv", {SENTINEL_KEY: SENTINEL_VALUE}),
    ("getSecret", f"{ENV}/providers/v/secrets/{SENTINEL_KEY}", ITEM),
    ("getSecretVersion", f"{ENV}/providers/v/secrets/{SENTINEL_KEY}/versions/1", ITEM),
    (
        "listGlobalSecrets",
        f"{BASE}/secrets",
        {"projectRef": "p", "projectSlug": "p", "globalSecretProviderId": None,
         "secrets": [{**ITEM, "tags": {}, "ignoreInScan": False}]},
    ),
]

# Calls that carry no value: the key is not presented, and the plain answer passes through.
VALUE_LESS = [
    ("GET", f"{ENV}/secrets/version"),
    ("GET", f"{ENV}/providers/v/secrets/hash"),
    ("GET", f"{ENV}/providers/v/secrets/{SENTINEL_KEY}/metadata"),
    ("GET", f"{ENV}/providers/v/secrets/{SENTINEL_KEY}/versions"),
    ("POST", f"{ENV}/providers/v/secrets"),
]

PLAINTEXT_BY_PATH = {path.split("?")[0]: plaintext for _, path, plaintext in READS}
PLAIN_ANSWER = {"version": 7}


class _Seen:
    def __init__(self) -> None:
        self.presented: dict[str, str | None] = {}


def _handler(seen: _Seen):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_: object) -> None:
            pass

        def _answer(self) -> None:
            path = self.path.split("?")[0]
            presented = self.headers.get("X-E2E-Public-Key")
            seen.presented[path] = presented
            plaintext = PLAINTEXT_BY_PATH.get(path)
            if plaintext is not None and presented:
                body = json.dumps(_encrypt_for(presented, json.dumps(plaintext).encode())).encode()
            else:
                body = json.dumps(PLAIN_ANSWER).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_GET = _answer
        do_POST = _answer

    return Handler


@pytest.fixture
def server() -> Iterator[tuple[_Seen, str]]:
    seen = _Seen()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _handler(seen))
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield seen, f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.mark.parametrize(("operation", "path", "plaintext"), READS, ids=[r[0] for r in READS])
def test_the_key_is_presented_and_the_plaintext_arrives_unchanged(server, operation, path, plaintext) -> None:
    seen, base = server
    with httpx.Client(transport=E2EETransport(httpx.HTTPTransport())) as client:
        body = client.get(base + path).json()

    assert seen.presented[path.split("?")[0]], f"{operation}: the transport did not present its key"
    assert body == plaintext, f"{operation}: the decrypted body was reshaped"


@pytest.mark.asyncio
@pytest.mark.parametrize(("operation", "path", "plaintext"), READS, ids=[r[0] for r in READS])
async def test_the_async_transport_presents_on_the_same_reads(server, operation, path, plaintext) -> None:
    """BaxterClient's Kiota adapter runs on the async transport."""
    seen, base = server
    async with httpx.AsyncClient(transport=AsyncE2EETransport(httpx.AsyncHTTPTransport())) as client:
        body = (await client.get(base + path)).json()

    assert seen.presented[path.split("?")[0]], f"{operation}: the transport did not present its key"
    assert body == plaintext


@pytest.mark.parametrize(("method", "path"), VALUE_LESS)
def test_the_key_is_not_presented_where_nothing_is_encrypted(server, method, path) -> None:
    seen, base = server
    with httpx.Client(transport=E2EETransport(httpx.HTTPTransport())) as client:
        response = client.request(method, base + path)

    assert seen.presented[path] is None
    assert response.json() == PLAIN_ANSWER


def test_a_legacy_flat_dict_on_get_all_environment_secrets_is_still_wrapped(server) -> None:
    """The one reshaping that stays: an old server that encrypted only the flat dict on the bulk read."""
    seen, base = server
    path = f"{ENV}/secrets"
    PLAINTEXT_BY_PATH[path], original = {SENTINEL_KEY: SENTINEL_VALUE}, PLAINTEXT_BY_PATH[path]
    try:
        with httpx.Client(transport=E2EETransport(httpx.HTTPTransport())) as client:
            body = client.get(base + path).json()
    finally:
        PLAINTEXT_BY_PATH[path] = original

    assert body["secrets"] == {SENTINEL_KEY: SENTINEL_VALUE}
