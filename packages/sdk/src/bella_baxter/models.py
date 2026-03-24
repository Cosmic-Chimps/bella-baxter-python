from dataclasses import dataclass, field
from typing import Dict


@dataclass
class BaxterClientOptions:
    """Options for constructing a BaxterClient."""

    #: Base URL of the Baxter API (e.g. "https://baxter.example.com")
    baxter_url: str

    #: Bella Baxter API key (bax-...). Obtain via WebApp or: bella apikeys create
    api_key: str

    #: Request timeout in seconds (default: 10)
    timeout: float = 10.0


@dataclass
class AllEnvironmentSecretsResponse:
    """Response from GET /api/v1/environments/{slug}/secrets"""

    environment_slug: str
    environment_name: str
    #: All secrets for the environment, aggregated from all providers.
    #: Served from Baxter's Redis cache — does NOT hit AWS/Azure/GCP per call.
    secrets: Dict[str, str]
    #: Monotonically increasing version counter (unix timestamp of last mutation)
    version: int
    #: ISO-8601 timestamp of last mutation
    last_modified: str


@dataclass
class EnvironmentSecretsVersionResponse:
    """Response from GET /api/v1/environments/{slug}/secrets/version"""

    environment_slug: str
    version: int
    last_modified: str
