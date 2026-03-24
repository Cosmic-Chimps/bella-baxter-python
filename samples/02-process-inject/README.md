# Sample 02: Process Inject (bella run) — Python

**Pattern:** `bella run -- python app.py` — secrets injected as env vars, no file written.

## Setup

```bash
# Authenticate
bella login --api-key bax-xxxxxxxxxxxxxxxxxxxx

export BELLA_BAXTER_URL=http://localhost:5522   # your Bella Baxter instance

# Run with secrets injected
bella run -- python app.py
```

## Works with any Python command

```bash
# Flask
bella run -- flask run

# Django
bella run -- python manage.py runserver

# FastAPI (uvicorn)
bella run -- uvicorn main:app

# Gunicorn (production)
bella run -- gunicorn -w 4 -b 0.0.0.0:8000 app:app

# Celery
bella run -- celery -A tasks worker --loglevel=info

# Database migrations
bella run -- python manage.py migrate --noinput
bella run -- alembic upgrade head

# pytest
bella run -- pytest tests/
```

## vs. `.env` file approach

| | `bella secrets get -o .env` | `bella run --` |
|---|---|---|
| File on disk | ✅ Yes | ❌ No |
| Needs python-dotenv | ✅ Yes | ❌ No |
| Secret security | File system | Memory only |
| Any command | ✅ Yes | ✅ Yes |

## Secret rotation

❌ **Not supported automatically.** Environment variables injected by `bella run` are set once at Python interpreter startup and are immutable for the lifetime of the process.

**To pick up rotated secrets:** restart via `bella run`:

```bash
bella run -- python app.py
```

For long-running daemons (Gunicorn, uWSGI), send a graceful restart signal to the master process after re-fetching secrets. New workers will inherit the updated environment.
