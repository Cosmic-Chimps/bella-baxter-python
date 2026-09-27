"""
The device key rules every SDK shares. The same rules hold in JS, Java, .NET, Swift, Dart and Go:

* the key must be P-256. The platform's ECIES is P-256 only; another curve used to load here and then
  fail on the server with an unclear error;
* a BLANK ``BELLA_BAXTER_PRIVATE_KEY`` (empty or whitespace) means "no device key", never an error.

Keys are generated per test, so no key material is committed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("cryptography")

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from bella_baxter.e2ee import E2EKeyPair, resolve_device_key


def _pem(key) -> str:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def test_a_p256_key_loads() -> None:
    pair = E2EKeyPair.from_pem(_pem(ec.generate_private_key(ec.SECP256R1())))
    assert pair.public_key_b64


def test_a_p384_key_is_refused_naming_the_curve() -> None:
    with pytest.raises(ValueError, match=r"P-256.*secp384r1"):
        E2EKeyPair.from_pem(_pem(ec.generate_private_key(ec.SECP384R1())))


def test_an_rsa_key_is_refused() -> None:
    with pytest.raises(ValueError, match="EC"):
        E2EKeyPair.from_pem(_pem(rsa.generate_private_key(public_exponent=65537, key_size=2048)))


@pytest.mark.parametrize("blank", ["", "   ", "\n\t "])
def test_a_blank_variable_means_no_device_key(monkeypatch: pytest.MonkeyPatch, blank: str) -> None:
    monkeypatch.setenv("BELLA_BAXTER_PRIVATE_KEY", blank)
    assert resolve_device_key(None) is None
    assert resolve_device_key(blank) is None


def test_an_explicit_key_wins_over_the_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BELLA_BAXTER_PRIVATE_KEY", "from-env")
    assert resolve_device_key("explicit") == "explicit"
    assert resolve_device_key("  ") == "from-env"
    assert resolve_device_key(None) == "from-env"


def test_no_key_anywhere_means_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BELLA_BAXTER_PRIVATE_KEY", raising=False)
    assert resolve_device_key(None) is None
