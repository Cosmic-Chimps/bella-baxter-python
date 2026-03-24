# bella-baxter-flask

Flask extension for the [Bella Baxter](https://bella-baxter.io) secrets management platform.
Attaches a `BaxterClient` to your Flask app as `app.bella`.

## Installation

```bash
pip install bella-baxter-flask
```

## Quickstart

```python
from flask import Flask
from bella_baxter_flask import BellaBaxter

app = Flask(__name__)
bella = BellaBaxter(app, api_key="bax-...")

@app.route("/health")
def health():
    secrets = app.bella.get_all_secrets()
    return {"database": secrets.secrets.get("DATABASE_URL")}
```

## Application factory pattern

```python
# extensions.py
from bella_baxter_flask import BellaBaxter

bella = BellaBaxter()  # not bound to an app yet

# app.py
from flask import Flask
from extensions import bella

def create_app():
    app = Flask(__name__)
    app.config["BELLA_BAXTER_API_KEY"] = "bax-..."
    bella.init_app(app)
    return app
```

```python
# routes.py
from extensions import bella

@app.route("/secrets")
def get_secrets():
    resp = bella.get_all_secrets()
    return resp.secrets
```

## Configuration

Pass `api_key=` directly to the constructor, or set it in `app.config`:

| Config key | Required | Default | Description |
|------------|----------|---------|-------------|
| `BELLA_BAXTER_API_KEY` | ✅ | — | API key (`bax-...`) |
| `BELLA_BAXTER_URL` | ❌ | `https://api.bella-baxter.io` | Base URL of the Baxter API |

```python
app.config["BELLA_BAXTER_API_KEY"] = os.environ["BELLA_BAXTER_API_KEY"]
app.config["BELLA_BAXTER_URL"] = os.environ.get("BELLA_BAXTER_URL", "https://api.bella-baxter.io")

bella = BellaBaxter()
bella.init_app(app)
```

## Accessing the underlying client

```python
# Full BaxterClient API available via .client
kiota = app.bella.client.client  # Kiota-generated HTTP client

# Or via the extension directly
resp = bella.get_all_secrets()
version = bella.get_secrets_version()
```

## Authentication

Generate an API key via the CLI or the Bella WebApp:

```bash
bella api-keys create --env production --name "Flask Production"
```
