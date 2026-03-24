# bella-baxter-django

Django integration for the [Bella Baxter](https://bella-baxter.io) secrets management platform.
Automatically loads secrets from Bella Baxter and makes them available throughout your Django app.

## Installation

```bash
pip install bella-baxter-django
```

## Quickstart

```python
# settings.py
INSTALLED_APPS = [
    ...
    'bella_baxter_django',
]

BELLA_BAXTER_API_KEY = 'bax-...'
BELLA_BAXTER_URL = 'https://api.bella-baxter.io'  # optional, this is the default
```

```python
# anywhere in your code
from bella_baxter_django import get_bella

client = get_bella()
secrets = client.get_all_secrets()
db_url = secrets.secrets['DATABASE_URL']
```

## How it works

`get_bella()` returns a shared `BaxterClient` instance, initialised lazily on first call
and cached for the lifetime of the process. Adding `'bella_baxter_django'` to `INSTALLED_APPS`
triggers eager initialisation at Django startup via `BellaBaxterConfig.ready()`,
so the first request doesn't bear the connection cost.

## Configuration

| Setting | Required | Default | Description |
|---------|----------|---------|-------------|
| `BELLA_BAXTER_API_KEY` | ✅ | — | API key (`bax-...`) |
| `BELLA_BAXTER_URL` | ❌ | `https://api.bella-baxter.io` | Base URL of the Baxter API |

## Using secrets in views

```python
from django.http import JsonResponse
from bella_baxter_django import get_bella

def health(request):
    bella = get_bella()
    secrets = bella.get_all_secrets()
    return JsonResponse({'db': secrets.secrets.get('DATABASE_URL', 'not set')})
```

## Using secrets in settings.py

```python
# settings.py — bootstrap secrets before Django fully loads
import os
from bella_baxter import BaxterClient, BaxterClientOptions

_bella = BaxterClient(BaxterClientOptions(
    baxter_url=os.environ.get('BELLA_BAXTER_URL', 'https://api.bella-baxter.io'),
    api_key=os.environ['BELLA_BAXTER_API_KEY'],
))
_secrets = _bella.get_all_secrets().secrets

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'HOST': _secrets['DB_HOST'],
        'NAME': _secrets['DB_NAME'],
        'USER': _secrets['DB_USER'],
        'PASSWORD': _secrets['DB_PASSWORD'],
    }
}
```

## Authentication

Generate an API key via the CLI or the Bella WebApp:

```bash
bella api-keys create --env production --name "Django Production"
```

Set it in your environment and reference it in `settings.py`:

```bash
export BELLA_BAXTER_API_KEY="bax-..."
```
