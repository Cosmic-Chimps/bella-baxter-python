"""webhook_signature — Verify X-Bella-Signature header on incoming Bella Baxter webhooks."""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import time
from typing import Union


def verify_webhook_signature(
    secret: str,
    signature_header: str,
    raw_body: Union[str, bytes],
    tolerance_seconds: int = 300,
) -> bool:
    """Verify the X-Bella-Signature header on a received Bella Baxter webhook.

    Args:
        secret: The webhook signing secret (whsec-xxx value).
        signature_header: Value of the X-Bella-Signature header,
            e.g. ``"t=1714000000,v1=abc123..."``.
        raw_body: The raw request body as str or bytes.
        tolerance_seconds: Maximum age of the timestamp in seconds. Default 300 (5 min).

    Returns:
        ``True`` if the signature is valid and the timestamp is within the
        replay-protection window; ``False`` otherwise.
    """
    # Parse t= and v1= from header
    timestamp: int | None = None
    expected_sig: str | None = None

    for part in signature_header.split(","):
        if "=" not in part:
            continue
        key, _, value = part.partition("=")
        key = key.strip()
        value = value.strip()
        if key == "t":
            try:
                timestamp = int(value)
            except ValueError:
                return False
        elif key == "v1":
            expected_sig = value

    if timestamp is None or expected_sig is None:
        return False

    # Check timestamp tolerance (replay-attack protection)
    if abs(int(time.time()) - timestamp) > tolerance_seconds:
        return False

    # Normalise body to str; webhook payloads are always UTF-8 JSON
    body_str = raw_body if isinstance(raw_body, str) else raw_body.decode("utf-8")
    signing_input = f"{timestamp}.{body_str}"

    # HMAC-SHA256: key=UTF8(secret), data=UTF8(signing_input)
    computed_sig = hmac_mod.new(
        secret.encode("utf-8"),
        signing_input.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    # Timing-safe compare
    return hmac_mod.compare_digest(computed_sig, expected_sig)
