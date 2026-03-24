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
