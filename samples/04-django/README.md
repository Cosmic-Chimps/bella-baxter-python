# Sample 04: Django

**Pattern:** `AppConfig.ready()` — secrets loaded once per Python process before any Django code uses them.

---

## Setup

```bash
pip install -r requirements.txt

bella login --api-key bax-xxxxxxxxxxxxxxxxxxxx

export BELLA_BAXTER_URL=http://localhost:5522   # your Bella Baxter instance

bella exec -- python manage.py runserver
# or production:
gunicorn myproject.wsgi
```

---

## How it works

**`AppConfig.ready()`** is Django's official startup hook — called exactly **once** per process after all models are loaded. This mirrors Laravel's `ServiceProvider::boot()` and Spring's `@PostConstruct`.

```
Django starts
  → loads INSTALLED_APPS
  → calls AppConfig.ready() for each app
  → BaxterConfig.ready() → get_all_secrets() → os.environ
  → runserver / Gunicorn workers are ready
```

---

## Register in INSTALLED_APPS

```python
# settings.py — replace 'myapp' with the AppConfig path
INSTALLED_APPS = [
    # ...
    "myapp.apps.BaxterConfig",  # ← use AppConfig class path, not just app name
]
```

---

## File layout

```
myapp/
    apps.py        ← BaxterConfig with ready() hook
    views.py       ← example views using os.environ
settings.py        ← shows DATABASE, REDIS read from os.environ
requirements.txt
README.md
```

---

## Using secrets in settings.py

Because `ready()` runs **after** settings are loaded, you cannot use Bella secrets as settings values directly. The recommended pattern is:

```python
# settings.py — provide defaults, Bella overwrites at ready() time
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        # These come from os.environ, which Bella populates in ready()
        "NAME":     os.environ.get("DB_NAME",     "fallback"),
        "USER":     os.environ.get("DB_USER",     "fallback"),
        "PASSWORD": os.environ.get("DB_PASSWORD", ""),
        "HOST":     os.environ.get("DB_HOST",     "localhost"),
    }
}
```

Django evaluates `os.environ.get()` lazily via `DATABASES` dict — by the time the first DB connection is made, `ready()` has already populated `os.environ`. ✅

---

## Management commands & Celery

```bash
# Migrations — secrets loaded before any DB access
BELLA_API_KEY=bax-xxxxxxxxxxxxxxxxxxxx python manage.py migrate

# Celery workers — same AppConfig.ready() mechanism
bella run -- celery -A myproject worker

# Shell
bella run -- python manage.py shell
```

---

## Django 4.2 vs 5.x

Works on both — `AppConfig.ready()` has been stable since Django 1.7.

## Secret rotation

❌ **Not supported automatically.** Secrets are fetched once in `AppConfig.ready()` per worker process. Django's `settings` module is loaded once at startup — `os.environ` values are static after that.

**To pick up rotated secrets:** restart workers:

```bash
kubectl rollout restart deployment/myapp
```

**For automatic rotation without restarts:** add a daemon thread in `AppConfig.ready()` that re-calls `_load_secrets()` periodically. Only code that reads `os.environ` directly (not `django.conf.settings`) will see the updated values.

⚠️ Django's `settings` object is **not** live-updated by `os.environ.update()` after startup.
