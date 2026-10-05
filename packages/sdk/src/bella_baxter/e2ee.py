"""End-to-end encryption helpers for the Bella Baxter SDK.

Algorithm: ECDH-P256-HKDF-SHA256-AES256GCM

Usage::

    # With e2ee enabled, getAllSecrets/getSecretsVersion automatically
    # send ``X-E2E-Public-Key`` and decrypt the response.
    options = BaxterClientOptions(
        baxter_url="https://api.bella-baxter.io",
        api_key="bax-...",
        enable_e2ee=True,   # ← opt-in
    )

Requires: ``pip install 'bella-baxter[e2ee]'`` (adds ``cryptography>=41``).
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, Dict


def _require_cryptography() -> None:
    try:
        import cryptography  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "E2EE requires the 'cryptography' package. "
            "Install it with:  pip install 'bella-baxter[e2ee]'"
        ) from exc


# ── #1050: a presented key requires an envelope ──────────────────────────────
#
# apps/sdk/SDK_CONTRACT.md, "Rule: a presented key requires an envelope". Once this SDK has sent its
# X-E2E-Public-Key on a read the server encrypts, a 2xx answer that is not a decryptable envelope is an
# ERROR, never a value: a header-stripping intermediary, a terminating proxy or a server regression would
# otherwise hand the caller unencrypted secrets it believes were end-to-end encrypted, and a tampered or
# mis-keyed envelope would be read as if it were its secrets. There is no plaintext fallback and no opt-out.

E2EE_PLAINTEXT_RESPONSE = "e2ee-plaintext-response"
"""The key was presented on an envelope-required read and the 2xx answer was not an envelope."""

E2EE_DECRYPTION_FAILED = "e2ee-decryption-failed"
"""The answer was an envelope that did not decrypt: a missing/undecodable field, a failed GCM tag
(tampered), or encrypted to a key other than the one presented."""


class E2EEResponseError(Exception):
    """A secrets response this client presented its E2EE key for was refused (#1050).

    ``code`` is one of :data:`E2EE_PLAINTEXT_RESPONSE` or :data:`E2EE_DECRYPTION_FAILED` — the same
    strings in every Bella SDK. The message names the request path and the code, never the body,
    ciphertext or key material; the underlying failure, if any, is the ``__cause__``.
    """

    def __init__(self, code: str, path: str) -> None:
        self.code = code
        self.path = path
        if code == E2EE_PLAINTEXT_RESPONSE:
            message = f"E2EE response expected but plaintext received for {path}; refusing it ({code})"
        else:
            message = f"E2EE response could not be decrypted for {path}; refusing it ({code})"
        super().__init__(message)


_API_PROJECTS = "/api/v1/projects/"


def requires_envelope(method: str, path: str) -> bool:
    """Whether the server encrypts this read's 2xx body to a presented key (SDK_CONTRACT.md).

    The envelope-required reads are the GETs that carry secret VALUES; everything else under
    ``/secrets`` (``…/secrets/version``, ``…/hash``, ``…/{key}/metadata``, writes, …) is plain JSON
    even when the key is presented, and must not be refused.
    """
    if method.upper() != "GET":
        return False
    i = path.find(_API_PROJECTS)
    if i < 0:
        return False
    segs = path[i + len(_API_PROJECTS):].rstrip("/").split("/")
    if len(segs) < 2 or not segs[0]:
        return False
    rest = segs[1:]
    if rest == ["secrets"]:  # listGlobalSecrets
        return True
    if len(rest) < 3 or rest[0] != "environments" or not rest[1]:
        return False
    tail = rest[2:]
    if tail in (["secrets"], ["secrets", "export"]):  # getAllEnvironmentSecrets, exportEnvironmentSecrets
        return True
    if len(tail) < 3 or tail[0] != "providers" or not tail[1] or tail[2] != "secrets":
        return False
    after = tail[3:]
    if not after:  # listSecrets
        return True
    if len(after) == 1:  # exportSecrets / getSecret
        return bool(after[0]) and after[0] != "hash"
    # getSecretVersion
    return len(after) == 3 and bool(after[0]) and after[1] == "versions" and after[2].isdigit() and after[2].isascii()


# ── Wire format ───────────────────────────────────────────────────────────────

@dataclass
class E2EEncryptedPayload:
    encrypted: bool
    algorithm: str
    server_public_key: str  # base64-encoded SPKI
    nonce: str              # base64-encoded 12 bytes
    tag: str                # base64-encoded 16 bytes
    ciphertext: str         # base64-encoded

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "E2EEncryptedPayload":
        return E2EEncryptedPayload(
            encrypted=d.get("encrypted", False),
            algorithm=d.get("algorithm", ""),
            server_public_key=d.get("serverPublicKey", ""),
            nonce=d.get("nonce", ""),
            tag=d.get("tag", ""),
            ciphertext=d.get("ciphertext", ""),
        )


# ── Key pair ──────────────────────────────────────────────────────────────────

def resolve_device_key(explicit: str | None) -> str | None:
    """The device key a client should use: ``explicit``, else ``BELLA_BAXTER_PRIVATE_KEY``.

    A blank value (empty or whitespace, from either source) means "no device key", as in every other
    SDK. Anything else is returned as-is and must then load as a P-256 key, or construction fails
    loudly (``E2EKeyPair.from_pem``).
    """
    import os

    def _clean(v: str | None) -> str | None:
        return v if v is not None and v.strip() else None

    return _clean(explicit) or _clean(os.environ.get("BELLA_BAXTER_PRIVATE_KEY"))


class E2EKeyPair:
    """P-256 key pair used for one-time E2EE handshake with the Bella Baxter API.

    Generate once per client instance; the public key is sent as the
    ``X-E2E-Public-Key`` request header.  The private key is used to decrypt
    the server's response (perfect forward secrecy — server generates a fresh
    ephemeral keypair per request).
    """

    def __init__(self) -> None:
        _require_cryptography()
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1, generate_private_key

        self._private_key = generate_private_key(SECP256R1(), default_backend())
        self._public_key_b64 = self._export_spki_b64()

    @classmethod
    def from_pem(cls, pem: str) -> "E2EKeyPair":
        """
        Create an E2EKeyPair from a PKCS#8 PEM private key (persistent device key).
        Use this for ZKE mode instead of the default ephemeral key generation.

        Obtain a key with: bella auth setup  (exports ~/.bella/device-key.pem)
        """
        _require_cryptography()
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

        pem_bytes = pem.encode() if isinstance(pem, str) else pem
        private_key = load_pem_private_key(pem_bytes, password=None)

        if not isinstance(private_key, EllipticCurvePrivateKey):
            raise ValueError("ZKE private key must be an EC (P-256) key")
        # The platform's ECIES is P-256 only. Any other curve used to load here and then fail on the
        # server with an unclear error; refuse it where the cause is still visible. The same rule as
        # the JS, Java, .NET, Swift, Dart and Go SDKs.
        from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1
        if not isinstance(private_key.curve, SECP256R1):
            raise ValueError(
                f"ZKE private key must be a P-256 (secp256r1) key, not {private_key.curve.name}"
            )

        spki = private_key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
        public_key_b64 = base64.b64encode(spki).decode()

        instance = cls.__new__(cls)
        instance._private_key = private_key
        instance._public_key_b64 = public_key_b64
        return instance

    def _export_spki_b64(self) -> str:
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        spki = self._private_key.public_key().public_bytes(
            Encoding.DER, PublicFormat.SubjectPublicKeyInfo
        )
        return base64.b64encode(spki).decode()

    @property
    def public_key_b64(self) -> str:
        """Base64-encoded SPKI public key — send as ``X-E2E-Public-Key`` header."""
        return self._public_key_b64

    def decrypt(self, payload: E2EEncryptedPayload) -> Dict[str, str]:
        """Decrypt an encrypted secrets response, returning a ``{key: value}`` dict."""
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives.asymmetric.ec import ECDH
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.hashes import SHA256
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        from cryptography.hazmat.primitives.serialization import load_der_public_key

        server_pub_bytes = base64.b64decode(payload.server_public_key)
        nonce = base64.b64decode(payload.nonce)
        tag = base64.b64decode(payload.tag)
        ciphertext = base64.b64decode(payload.ciphertext)

        # 1. ECDH → raw shared secret
        server_pub_key = load_der_public_key(server_pub_bytes, default_backend())
        shared_secret = self._private_key.exchange(ECDH(), server_pub_key)

        # 2. HKDF-SHA256 → 32-byte AES key  (salt=None → 32-zero salt per RFC 5869)
        aes_key = HKDF(
            algorithm=SHA256(),
            length=32,
            salt=None,
            info=b"bella-e2ee-v1",
            backend=default_backend(),
        ).derive(shared_secret)

        # 3. AES-256-GCM decrypt (cryptography lib expects ciphertext || tag)
        plaintext = AESGCM(aes_key).decrypt(nonce, ciphertext + tag, None)

        parsed = json.loads(plaintext.decode("utf-8"))

        # Three possible server response shapes:
        #   1. Full AllEnvironmentSecretsResponse: {"environmentSlug":..., "secrets":{...}, ...}
        #   2. Array of SecretItem:                [{"key":"K", "value":"V"}, ...]
        #   3. Legacy flat dict:                   {"K": "V", ...}
        if isinstance(parsed, dict) and "secrets" in parsed and isinstance(parsed["secrets"], dict):
            return {k: str(v) for k, v in parsed["secrets"].items()}

        if isinstance(parsed, list):
            return {item["key"]: item.get("value", "") for item in parsed if "key" in item}

        # Legacy flat dict.
        return parsed

    def decrypt_raw(self, payload: E2EEncryptedPayload) -> bytes:
        """Decrypt an encrypted response, returning the raw plaintext bytes.

        Unlike :meth:`decrypt`, this preserves the full server JSON (including
        ``environmentSlug``, ``version``, ``lastModified``, etc.) without any
        transformation.
        """
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives.asymmetric.ec import ECDH
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.hashes import SHA256
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        from cryptography.hazmat.primitives.serialization import load_der_public_key

        server_pub_bytes = base64.b64decode(payload.server_public_key)
        nonce = base64.b64decode(payload.nonce)
        tag = base64.b64decode(payload.tag)
        ciphertext = base64.b64decode(payload.ciphertext)

        server_pub_key = load_der_public_key(server_pub_bytes, default_backend())
        shared_secret = self._private_key.exchange(ECDH(), server_pub_key)

        aes_key = HKDF(
            algorithm=SHA256(),
            length=32,
            salt=None,
            info=b"bella-e2ee-v1",
            backend=default_backend(),
        ).derive(shared_secret)

        return AESGCM(aes_key).decrypt(nonce, ciphertext + tag, None)


# ── Helper ────────────────────────────────────────────────────────────────────

def maybe_decrypt(raw: Dict[str, Any], keypair: E2EKeyPair | None) -> Dict[str, str]:
    """Return the decrypted secrets dict if the response is encrypted, otherwise return as-is."""
    if keypair is not None and raw.get("encrypted"):
        return keypair.decrypt(E2EEncryptedPayload.from_dict(raw))
    return raw  # plain dict


def maybe_decrypt_raw(raw: Dict[str, Any], keypair: E2EKeyPair | None) -> Dict[str, Any]:
    """Decrypt and return the full parsed response dict (preserving all metadata fields).

    If encrypted, decrypts and parses the full JSON.  If not encrypted, returns *raw* as-is.
    """
    if keypair is not None and raw.get("encrypted"):
        plaintext = keypair.decrypt_raw(E2EEncryptedPayload.from_dict(raw))
        return json.loads(plaintext.decode("utf-8"))
    return raw
