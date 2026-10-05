"""
#1050 (b) — once this SDK has presented its E2EE public key, a secrets answer that is not a decryptable
envelope is an ERROR, never a value (apps/sdk/SDK_CONTRACT.md, "Rule: a presented key requires an
envelope").

A real local HTTP server stands in for a misbehaving Bella. It reads the X-E2E-Public-Key the transport
actually presented and answers the read with one of four things:

  valid      an envelope encrypted to THAT key, exactly as the API does it   -> the values come back
  plaintext  the secrets JSON with no envelope                                -> e2ee-plaintext-response
  tampered   a genuine envelope with one ciphertext byte flipped (GCM fails)  -> e2ee-decryption-failed
  wrong-key  a well-formed envelope encrypted to a DIFFERENT P-256 key        -> e2ee-decryption-failed

The server-side encryption is written out here rather than borrowed from the SDK, so a defect in the SDK's
own crypto cannot make the valid case agree with itself.
"""

from __future__ import annotations

import base64
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Iterator

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    load_der_public_key,
)

from bella_baxter.e2ee import (
    E2EE_DECRYPTION_FAILED,
    E2EE_PLAINTEXT_RESPONSE,
    E2EEResponseError,
    requires_envelope,
)
from bella_baxter.e2ee_httpx_transport import AsyncE2EETransport, E2EETransport

SECRETS_PATH = "/api/v1/projects/contract-project/environments/contract-env/secrets"
SENTINEL_KEY = "BELLA_KEY_CONTRACT"
SENTINEL_VALUE = "the-registered-device-key-was-used"
PLAINTEXT = {
    "environmentSlug": "contract-env",
    "environmentName": "contract-env",
    "secrets": {SENTINEL_KEY: SENTINEL_VALUE},
    "version": 1,
    "lastModified": "2026-10-04T00:00:00Z",
}


def _encrypt_for(client_spki_b64: str, plaintext: bytes) -> dict:
    """EciesAlgorithm.Encrypt — the server side of the contract (stub/server.mjs encryptFor)."""
    client_key = load_der_public_key(base64.b64decode(client_spki_b64))
    ephemeral = ec.generate_private_key(ec.SECP256R1())
    shared = ephemeral.exchange(ec.ECDH(), client_key)
    aes_key = HKDF(algorithm=SHA256(), length=32, salt=b"\x00" * 32, info=b"bella-e2ee-v1").derive(shared)
    nonce = os.urandom(12)
    sealed = AESGCM(aes_key).encrypt(nonce, plaintext, None)
    ciphertext, tag = sealed[:-16], sealed[-16:]
    server_spki = ephemeral.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    return {
        "encrypted": True,
        "algorithm": "ECDH-P256-HKDF-SHA256-AES256GCM",
        "serverPublicKey": base64.b64encode(server_spki).decode(),
        "nonce": base64.b64encode(nonce).decode(),
        "tag": base64.b64encode(tag).decode(),
        "ciphertext": base64.b64encode(ciphertext).decode(),
    }


class _Stub:
    """What the misbehaving server serves next, and what it saw."""

    def __init__(self) -> None:
        self.scenario = "valid"
        self.status = 200
        self.presented: list[str | None] = []


def _handler(stub: _Stub):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_: object) -> None:  # keep pytest output clean
            pass

        def _answer(self) -> None:
            presented = self.headers.get("X-E2E-Public-Key")
            stub.presented.append(presented)
            body: bytes
            content_type = "application/json"
            plaintext = json.dumps(PLAINTEXT).encode()

            if stub.status != 200:
                body = json.dumps({"type": "about:blank", "title": "refused by the stub"}).encode()
                content_type = "application/problem+json"
            elif stub.scenario == "valid":
                body = json.dumps(_encrypt_for(presented, plaintext)).encode()
            elif stub.scenario == "plaintext":
                body = plaintext
            elif stub.scenario == "dotenv":
                body = f"{SENTINEL_KEY}={SENTINEL_VALUE}\n".encode()
                content_type = "text/plain"
            elif stub.scenario == "tampered":
                envelope = _encrypt_for(presented, plaintext)
                raw = bytearray(base64.b64decode(envelope["ciphertext"]))
                raw[0] ^= 0x01
                envelope["ciphertext"] = base64.b64encode(bytes(raw)).decode()
                body = json.dumps(envelope).encode()
            elif stub.scenario == "wrong-key":
                other = ec.generate_private_key(ec.SECP256R1()).public_key()
                other_b64 = base64.b64encode(
                    other.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
                ).decode()
                body = json.dumps(_encrypt_for(other_b64, plaintext)).encode()
            elif stub.scenario == "missing-field":
                envelope = _encrypt_for(presented, plaintext)
                del envelope["tag"]
                body = json.dumps(envelope).encode()
            else:  # pragma: no cover
                raise AssertionError(stub.scenario)

            self.send_response(stub.status)
            self.send_header("content-type", content_type)
            self.send_header("content-length", str(len(body)))
            self.send_header("X-Bella-Wrapped-Dek", "wrapped-dek-value")
            self.end_headers()
            self.wfile.write(body)

        do_GET = _answer
        do_POST = _answer

    return Handler


@pytest.fixture
def stub() -> Iterator[tuple[_Stub, str]]:
    state = _Stub()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state, f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _client(on_wrapped_dek=None) -> httpx.Client:
    return httpx.Client(transport=E2EETransport(httpx.HTTPTransport(), on_wrapped_dek_received=on_wrapped_dek))


# ── The four contract cases ──────────────────────────────────────────────────


def test_a_valid_envelope_to_the_presented_key_is_decrypted(stub) -> None:
    state, base = stub
    state.scenario = "valid"
    with _client() as client:
        body = client.get(base + SECRETS_PATH).json()

    assert state.presented[-1], "the transport did not present its key"
    assert body["secrets"][SENTINEL_KEY] == SENTINEL_VALUE
    assert body["version"] == 1


def test_plaintext_after_presenting_the_key_is_refused(stub) -> None:
    state, base = stub
    state.scenario = "plaintext"
    with _client() as client:
        with pytest.raises(E2EEResponseError) as raised:
            client.get(base + SECRETS_PATH)

    assert state.presented[-1], "the refusal must follow a presented key"
    assert raised.value.code == E2EE_PLAINTEXT_RESPONSE
    message = str(raised.value)
    assert message == (
        f"E2EE response expected but plaintext received for {SECRETS_PATH}; refusing it (e2ee-plaintext-response)"
    )
    assert SENTINEL_VALUE not in message


def test_a_tampered_envelope_is_refused(stub) -> None:
    state, base = stub
    state.scenario = "tampered"
    with _client() as client:
        with pytest.raises(E2EEResponseError) as raised:
            client.get(base + SECRETS_PATH)

    assert raised.value.code == E2EE_DECRYPTION_FAILED
    assert str(raised.value) == (
        f"E2EE response could not be decrypted for {SECRETS_PATH}; refusing it (e2ee-decryption-failed)"
    )
    assert raised.value.__cause__ is not None  # the GCM failure, kept for whoever debugs it


def test_an_envelope_to_another_key_is_refused(stub) -> None:
    state, base = stub
    state.scenario = "wrong-key"
    with _client() as client:
        with pytest.raises(E2EEResponseError) as raised:
            client.get(base + SECRETS_PATH)

    assert raised.value.code == E2EE_DECRYPTION_FAILED


# ── The same family, other shapes ────────────────────────────────────────────


def test_a_non_json_body_after_presenting_the_key_is_plaintext(stub) -> None:
    """A dotenv file is what the export paths serve WITHOUT a key; with one, it is plaintext."""
    state, base = stub
    state.scenario = "dotenv"
    with _client() as client:
        with pytest.raises(E2EEResponseError) as raised:
            client.get(base + SECRETS_PATH)

    assert raised.value.code == E2EE_PLAINTEXT_RESPONSE
    assert SENTINEL_VALUE not in str(raised.value)


def test_an_envelope_missing_a_field_is_a_decryption_failure(stub) -> None:
    state, base = stub
    state.scenario = "missing-field"
    with _client() as client:
        with pytest.raises(E2EEResponseError) as raised:
            client.get(base + SECRETS_PATH)

    assert raised.value.code == E2EE_DECRYPTION_FAILED


def test_a_refused_answer_does_not_fire_the_wrapped_dek_callback(stub) -> None:
    state, base = stub
    state.scenario = "plaintext"
    seen: list[tuple] = []
    with _client(on_wrapped_dek=lambda *args: seen.append(args)) as client:
        with pytest.raises(E2EEResponseError):
            client.get(base + SECRETS_PATH)

    assert seen == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scenario", "code"),
    [("plaintext", E2EE_PLAINTEXT_RESPONSE), ("tampered", E2EE_DECRYPTION_FAILED), ("wrong-key", E2EE_DECRYPTION_FAILED)],
)
async def test_the_async_transport_refuses_the_same_way(stub, scenario: str, code: str) -> None:
    """BaxterClient's Kiota adapter runs on the ASYNC transport — the one `get_all_secrets` uses."""
    state, base = stub
    state.scenario = scenario
    async with httpx.AsyncClient(transport=AsyncE2EETransport(httpx.AsyncHTTPTransport())) as client:
        with pytest.raises(E2EEResponseError) as raised:
            await client.get(base + SECRETS_PATH)

    assert raised.value.code == code


@pytest.mark.asyncio
async def test_the_async_transport_decrypts_a_valid_envelope(stub) -> None:
    state, base = stub
    state.scenario = "valid"
    async with httpx.AsyncClient(transport=AsyncE2EETransport(httpx.AsyncHTTPTransport())) as client:
        body = (await client.get(base + SECRETS_PATH)).json()

    assert body["secrets"][SENTINEL_KEY] == SENTINEL_VALUE


# ── What the rule must NOT touch ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/projects/p/environments/e/secrets/version"),
        ("POST", "/api/v1/projects/p/environments/e/providers/v/secrets"),
    ],
)
def test_plaintext_on_a_read_the_server_does_not_encrypt_passes(stub, method: str, path: str) -> None:
    state, base = stub
    state.scenario = "plaintext"
    with _client() as client:
        response = client.request(method, base + path)

    assert response.status_code == 200
    assert response.json()["secrets"][SENTINEL_KEY] == SENTINEL_VALUE


def test_a_non_2xx_answer_is_not_turned_into_an_e2ee_error(stub) -> None:
    state, base = stub
    state.status = 403
    with _client() as client:
        response = client.get(base + SECRETS_PATH)

    assert response.status_code == 403
    assert response.json()["title"] == "refused by the stub"


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("GET", "/api/v1/projects/p/secrets", True),  # listGlobalSecrets
        ("GET", "/api/v1/projects/p/environments/e/secrets", True),  # getAllEnvironmentSecrets
        ("GET", "/api/v1/projects/p/environments/e/secrets/export", True),  # exportEnvironmentSecrets
        ("GET", "/api/v1/projects/p/environments/e/providers/v/secrets", True),  # listSecrets
        ("GET", "/api/v1/projects/p/environments/e/providers/v/secrets/export", True),  # exportSecrets
        ("GET", "/api/v1/projects/p/environments/e/providers/v/secrets/DB_URL", True),  # getSecret
        ("GET", "/api/v1/projects/p/environments/e/providers/v/secrets/DB_URL/versions/3", True),  # getSecretVersion
        ("get", "/gateway/api/v1/projects/p/environments/e/secrets", True),  # a base path in front
        ("GET", "/api/v1/projects/p/environments/e/secrets/", True),  # trailing slash
        ("GET", "/api/v1/projects/p/environments/e/secrets/version", False),
        ("GET", "/api/v1/projects/p/environments/e/secrets/manifest", False),
        ("GET", "/api/v1/projects/p/environments/e/secrets/certificates", False),
        ("GET", "/api/v1/projects/p/environments/e/providers/v/secrets/hash", False),
        ("GET", "/api/v1/projects/p/environments/e/providers/v/secrets/K/metadata", False),
        ("GET", "/api/v1/projects/p/environments/e/providers/v/secrets/K/versions", False),
        ("GET", "/api/v1/projects/p/environments/e/providers/v/secrets/K/versions/latest", False),
        ("GET", "/api/v1/projects/p/environments/e/providers/v/secrets/K/rotation-policy", False),
        ("GET", "/api/v1/projects/p/environments/e/providers/v/secrets/import/preview", False),
        ("POST", "/api/v1/projects/p/environments/e/secrets", False),
        ("PUT", "/api/v1/projects/p/environments/e/providers/v/secrets/K", False),
        ("DELETE", "/api/v1/projects/p/environments/e/providers/v/secrets/K", False),
        ("GET", "/api/v1/tenants/me/zke", False),
        ("GET", "/api/v1/projects/p", False),
    ],
)
def test_requires_envelope_is_the_contract_table(method: str, path: str, expected: bool) -> None:
    assert requires_envelope(method, path) is expected
