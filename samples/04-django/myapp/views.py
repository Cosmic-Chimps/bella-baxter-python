"""
Minimal Django views showing secret access.
"""

import os

from django.http import JsonResponse


def index(request):
    db = os.environ.get("DATABASE_URL", "(not set)")
    return JsonResponse({
        "message": "Hello from Bella Baxter + Django",
        "db": db[:20] + "***" if len(db) > 20 else db,
    })


def health(request):
    return JsonResponse({"ok": True})


def secrets(request):
    keys = [
        "PORT", "DATABASE_URL", "EXTERNAL_API_KEY", "GLEAP_API_KEY",
        "ENABLE_FEATURES", "APP_ID", "ConnectionStrings__Postgres", "APP_CONFIG",
    ]
    return JsonResponse({k: os.environ.get(k, "") for k in keys})
