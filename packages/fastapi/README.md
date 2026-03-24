# bella-baxter-fastapi

FastAPI integration for the [Bella Baxter](https://bella-baxter.io) secrets management platform.
Provides a `BellaDepends` dependency annotation for injecting a `BaxterClient` into route handlers.

## Installation

```bash
pip install bella-baxter-fastapi
```

## Quickstart

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from bella_baxter_fastapi import init_bella, BellaDepends

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_bella(api_key="bax-...")
    yield

app = FastAPI(lifespan=lifespan)

@app.get("/health")
async def health(bella: BellaDepends):
    secrets = await bella.get_all_secrets_async()
    return {"database": secrets.secrets.get("DATABASE_URL")}
```

## `init_bella()`

Call once at startup (inside a lifespan handler or module level) to initialise the shared client:

```python
from bella_baxter_fastapi import init_bella

init_bella(
    api_key="bax-...",
    baxter_url="https://api.bella-baxter.io",  # optional
)
```

## `BellaDepends`

A typed `Annotated` dependency that injects the shared `BaxterClient`:

```python
from bella_baxter_fastapi import BellaDepends

@app.get("/secrets")
async def get_secrets(bella: BellaDepends):
    resp = await bella.get_all_secrets_async()
    return resp.secrets
```

## Configuration via environment variables

```python
import os
from bella_baxter_fastapi import init_bella

init_bella(
    api_key=os.environ["BELLA_BAXTER_API_KEY"],
    baxter_url=os.environ.get("BELLA_BAXTER_URL", "https://api.bella-baxter.io"),
)
```

## Authentication

Generate an API key via the CLI or the Bella WebApp:

```bash
bella api-keys create --env production --name "FastAPI Production"
```

## Using secrets at startup (before first request)

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_bella(api_key=os.environ["BELLA_BAXTER_API_KEY"])

    # Pre-fetch secrets to warm the cache
    from bella_baxter_fastapi import _get_bella_client
    client = _get_bella_client()
    secrets = await client.get_all_secrets_async()
    app.state.db_url = secrets.secrets["DATABASE_URL"]
    yield
```
