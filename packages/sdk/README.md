# bella-baxter

Python SDK for the [Bella Baxter](https://bella-baxter.io) secrets management platform.
Includes built-in end-to-end encryption and webhook signature verification.

## When to use bella-baxter directly

Most applications should use a framework integration instead:

| Framework | Package |
|-----------|---------|
| Django | [`bella-baxter-django`](../django/) |
| FastAPI | [`bella-baxter-fastapi`](../fastapi/) |
| Flask | [`bella-baxter-flask`](../flask/) |
| Scripts, tools, custom integrations | **bella-baxter** (this package) |

## Installation

```bash
pip install bella-baxter
```

## Quickstart

```python
from bella_baxter import BaxterClient, BaxterClientOptions

client = BaxterClient(BaxterClientOptions(
    baxter_url="https://api.bella-baxter.io",
    api_key="bax-...",
))

# Fetch all secrets (sync — works in Django, Flask, scripts)
secrets = client.get_all_secrets()
db_url = secrets.secrets["DATABASE_URL"]

# Async (FastAPI, asyncio)
secrets = await client.get_all_secrets_async()
```

## Authentication

### API key (recommended for apps and CI/CD)

```bash
# Generate a key via the CLI
bella api-keys create --env production --name "MyApp Production"
# Returns: bax-<keyId>-<secret>
```

```python
import os
from bella_baxter import BaxterClient, BaxterClientOptions

client = BaxterClient(BaxterClientOptions(
    baxter_url=os.environ["BELLA_BAXTER_URL"],
    api_key=os.environ["BELLA_BAXTER_API_KEY"],
))
```

API keys encode the project and environment slug — no config file needed.
Generate via `bella api-keys create` or the Bella WebApp.

### OAuth (local dev)

```bash
bella login           # opens browser, stores token in .bella file
bella exec -- python app.py   # injects BELLA_BAXTER_API_KEY + BELLA_BAXTER_URL automatically
```

## End-to-end encryption

Secret values are encrypted client-side using **ECIES** (Elliptic Curve Integrated Encryption Scheme)
before being sent to the Baxter API. Decryption happens transparently in the SDK.

E2EE is included — no extra install needed (`cryptography>=41` is a core dependency).

## Lightweight version polling

For long-running processes that need to detect secret rotations:

```python
# Check if secrets have changed without fetching values
version = client.get_secrets_version()
if version.version != last_known_version:
    secrets = client.get_all_secrets()
    last_known_version = version.version
```

## Webhook signature verification

```python
from bella_baxter import verify_webhook_signature

is_valid = verify_webhook_signature(
    payload=request.body,
    signature_header=request.headers["X-Bella-Signature"],
    secret="whsec-...",
)
```

## Full API access (Kiota client)

```python
# Access the underlying Kiota client for full API coverage
kiota = client.client

# List projects
projects = await kiota.api.v1.projects.get()

# Manage environments, providers, users, API keys, etc.
```

## Regenerating the generated client

`bella-baxter` embeds a Kiota-generated HTTP client. To regenerate after an API change:

```bash
cd apps/sdk
./generate.sh
```
