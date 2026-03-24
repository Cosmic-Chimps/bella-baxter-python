"""
Minimal Django settings — shows how Bella secrets integrate.

Secrets are loaded by BaxterConfig.ready() before these values are used.
os.environ is populated by the time any database or cache is accessed.
"""

import os

# SECURITY
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-change-me")
DEBUG = os.environ.get("DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

# APPS — use BaxterConfig so ready() is called
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "myapp.apps.BaxterConfig",   # ← replaces plain 'myapp'
]

MIDDLEWARE = [
    "django.middleware.common.CommonMiddleware",
]

# DATABASE — use SQLite for portability; swap to postgresql in production
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("DB_NAME", ":memory:"),
    }
}

# CACHE — in-memory for simplicity
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

ROOT_URLCONF = "urls"
