"""
bella-baxter — Python SDK

Minimal client for the Bella Baxter secret management API.
Supports both synchronous and async usage via httpx.

Sync usage:
    from bella_baxter import BaxterClient, BaxterClientOptions

    client = BaxterClient(BaxterClientOptions(
        baxter_url="https://api.bella-baxter.io",
        api_key="bax-abc123",
    ))
    secrets = client.get_all_secrets("production")

Async usage:
    async with BaxterClient.async_client(options) as client:
        secrets = await client.get_all_secrets_async("production")
"""

from .client import BaxterClient
from .models import (
    BaxterClientOptions,
    AllEnvironmentSecretsResponse,
    EnvironmentSecretsVersionResponse,
    PkiCaInfo,
    PkiIssuedCertificate,
    SshCaInfo,
    SshSignedCert,
)
from .generated.models.pki_create_role_request import PkiCreateRoleRequest
from .generated.models.pki_issue_certificate_request import PkiIssueCertificateRequest
from .generated.models.pki_role_response import PkiRoleResponse
from .generated.models.ssh_sign_request import SshSignRequest
from .webhook_signature import verify_webhook_signature

__all__ = [
    # Client
    "BaxterClient",
    "BaxterClientOptions",
    # Secrets
    "AllEnvironmentSecretsResponse",
    "EnvironmentSecretsVersionResponse",
    # PKI
    "PkiCaInfo",
    "PkiIssuedCertificate",
    "PkiCreateRoleRequest",
    "PkiIssueCertificateRequest",
    "PkiRoleResponse",
    # SSH
    "SshCaInfo",
    "SshSignedCert",
    "SshSignRequest",
    # Utilities
    "verify_webhook_signature",
]
