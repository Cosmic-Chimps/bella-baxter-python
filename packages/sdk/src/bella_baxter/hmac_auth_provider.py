"""HmacAuthProvider — Kiota AuthenticationProvider that signs requests with HMAC-SHA256."""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import os
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qsl, urlencode


class HmacAuthProvider:
    """Kiota AuthenticationProvider that adds HMAC-SHA256 signing headers to every request."""

    def __init__(self, api_key: str, bella_client: str = "bella-python-sdk", app_client: str | None = None) -> None:
        parts = api_key.split("-", 2)
        if len(parts) != 3 or parts[0] != "bax":
            raise ValueError("api_key must be in format bax-{keyId}-{signingSecret}")
        self.key_id = parts[1]
        self.signing_secret = bytes.fromhex(parts[2])
        self.bella_client = bella_client
        self.app_client = app_client or os.environ.get("BELLA_BAXTER_APP_CLIENT")

    async def authenticate_request(self, request, additional_auth_context=None) -> None:
        method = request.http_method.value if hasattr(request.http_method, "value") else str(request.http_method).upper()
        url = str(request.url)
        parsed = urlparse(url)
        path = parsed.path
        query = urlencode(sorted(parse_qsl(parsed.query or "")))
        body = b""
        if request.content:
            body = request.content if isinstance(request.content, bytes) else request.content.read()
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        body_hash = hashlib.sha256(body).hexdigest()
        string_to_sign = f"{method}\n{path}\n{query}\n{timestamp}\n{body_hash}"
        sig = hmac_mod.new(self.signing_secret, string_to_sign.encode(), hashlib.sha256).hexdigest()
        request.headers.try_add("X-Bella-Key-Id", self.key_id)
        request.headers.try_add("X-Bella-Timestamp", timestamp)
        request.headers.try_add("X-Bella-Signature", sig)
        request.headers.try_add("X-Bella-Client", self.bella_client)
        if self.app_client:
            request.headers.try_add("X-App-Client", self.app_client)
