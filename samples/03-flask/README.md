# Sample 03: Flask

**Pattern:** SDK called in the app factory before `Flask()` config is read — secrets available via `os.environ` everywhere.

---

## Setup

```bash
pip install -r requirements.txt

bella login --api-key bax-xxxxxxxxxxxxxxxxxxxx

export BELLA_BAXTER_URL=http://localhost:5522   # your Bella Baxter instance

bella exec -- flask run
# or production:
gunicorn "app:create_app()"
```

---

## How it works

**App factory sequence:**
1. `create_app()` is called (per-worker in Gunicorn)
2. `load_bella_secrets()` calls `BaxterClient.get_all_secrets(env_slug)`
3. All secrets written to `os.environ` — available immediately
4. Flask reads `os.environ` for config keys normally

**Why app factory?**
Flask's app factory pattern (`create_app()`) is the standard way to configure Flask. Each Gunicorn worker calls it once on startup, so secrets are loaded once per worker — zero per-request overhead.

---

## Using secrets in routes

```python
# app/config.py
import os

class Config:
    DATABASE_URL  = os.environ["DATABASE_URL"]      # Available after load_bella_secrets()
    REDIS_URL     = os.environ.get("REDIS_URL")
    SECRET_KEY    = os.environ["FLASK_SECRET_KEY"]

# app/__init__.py
def create_app():
    load_bella_secrets(...)
    app = Flask(__name__)
    app.config.from_object(Config)
    # ...
```

```python
# Any route — secrets are in os.environ / app.config
@app.get("/api/data")
def get_data():
    token = os.environ.get("THIRD_PARTY_TOKEN")
    # use token...
```

---

## SQLAlchemy integration

```python
# The DATABASE_URL secret becomes available before SQLAlchemy is configured
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ["DATABASE_URL"]
db = SQLAlchemy(app)
```

---

## Celery workers

```bash
# Workers share the same app factory pattern
bella run -- celery -A app.celery worker
# or .env approach:
bella secrets get -o .env && celery -A app.celery worker
```

## Secret rotation

❌ **Not supported automatically.** Secrets are fetched once inside `create_app()` when a Gunicorn worker starts. They are written into `app.config` and `os.environ` — both are mutable, but nothing updates them after startup.

**To pick up rotated secrets:** restart Gunicorn workers (graceful, zero-downtime):

```bash
# Kubernetes rolling restart
kubectl rollout restart deployment/myapp
```

**For automatic rotation without restarts:** add a background daemon thread in `create_app()` that periodically calls `client.get_all_secrets()` and calls `os.environ.update()` + `app.config.update()`. Only code reading from `os.environ` at call time will see updated values; module-level captured variables won't.
