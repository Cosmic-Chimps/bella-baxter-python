# Sample 05: FastAPI

**Pattern:** Async lifespan context manager loads secrets at startup — fully async, no blocking, available via `app.state.secrets` and `os.environ`.

---

## Setup

```bash
pip install -r requirements.txt

bella login --api-key bax-xxxxxxxxxxxxxxxxxxxx

export BELLA_BAXTER_URL=http://localhost:5522   # your Bella Baxter instance

bella exec -- uvicorn main:app --host 0.0.0.0 --port 8000
# development:
uvicorn main:app --reload
```

---

## How it works

**`@asynccontextmanager lifespan`** is the modern FastAPI startup/shutdown hook (replaces deprecated `@app.on_event`).

```
uvicorn starts main:app
  → lifespan() called (async)
  → async with BaxterClient → get_all_secrets_async()
  → os.environ updated
  → app.state.secrets populated
  → yield  (app handles requests)
  → cleanup on shutdown
```

The async SDK call uses `httpx.AsyncClient` internally — no thread blocking.

---

## Accessing secrets in routes

**Option 1: os.environ** (simplest, works anywhere)
```python
@app.get("/")
async def root():
    db_url = os.environ.get("DATABASE_URL")
```

**Option 2: Dependency injection** (recommended, typed)
```python
def get_secrets(request: Request) -> dict[str, str]:
    return request.app.state.secrets

@app.get("/items")
async def get_items(secrets: dict[str, str] = Depends(get_secrets)):
    token = secrets.get("THIRD_PARTY_TOKEN")
```

**Option 3: Typed config via Pydantic**
```python
from pydantic_settings import BaseSettings

class AppConfig(BaseSettings):
    database_url: str
    redis_url: str = "redis://localhost:6379"
    secret_key: str

# In lifespan, after loading secrets:
app.state.config = AppConfig()  # reads from os.environ automatically
```

---

## SQLAlchemy / SQLModel

```python
# database.py — os.environ is already populated when this module is imported
# from a route handler (after lifespan runs)
from sqlalchemy.ext.asyncio import create_async_engine

def get_engine():
    url = os.environ["DATABASE_URL"]
    return create_async_engine(url)
```

Or initialise in lifespan:
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Load secrets
    await load_bella_secrets(app)
    # 2. Now safe to init DB (DATABASE_URL is in os.environ)
    engine = create_async_engine(os.environ["DATABASE_URL"])
    app.state.db = engine
    yield
    await engine.dispose()
```

---

## File layout

```
main.py            ← FastAPI app with lifespan
requirements.txt
README.md
```

## Secret rotation

✅ **Supported with a small addition.** FastAPI secrets live in `app.state.secrets` (a mutable dict). Add an `asyncio` background task in `lifespan` to poll and update it:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    async with BaxterClient(opts) as client:
        resp = await client.get_all_secrets_async(env_slug)
        app.state.secrets = resp.secrets

        async def _poll():
            while True:
                await asyncio.sleep(60)
                try:
                    fresh = await client.get_all_secrets_async(env_slug)
                    app.state.secrets.update(fresh.secrets)
                except Exception:
                    pass  # keep cached values on error

        task = asyncio.create_task(_poll())
        yield
        task.cancel()
```

Endpoints using `Depends(get_secret)` read from `app.state.secrets` on every request — they automatically see updated values after the next poll. Note: `os.environ` is **not** updated by polling; prefer the `Depends` injection pattern for secrets that need live rotation.
