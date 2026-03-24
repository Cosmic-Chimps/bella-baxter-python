# Sample 06: Typed Secrets (`bella secrets generate python`)

**Pattern:** `bella secrets generate python` → typed accessor class → no more `os.environ["TYPO"]`

---

## How it works

```
bella secrets generate python -o secrets.py
↓
secrets.py  (generated, safe to commit — contains NO secret values)
↓
from secrets import AppSecrets
↓
AppSecrets().database_url  (typed, IDE-autocomplete, runtime validation)
```

## Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Authenticate
bella login --api-key bax-xxxxxxxxxxxxxxxxxxxx

export BELLA_BAXTER_URL=http://localhost:5522   # your Bella Baxter instance

# Generate the typed class (re-run whenever secrets change)
bella secrets generate python -o secrets.py

# Pull actual secret values into environment
bella secrets get -o .env

# Run the app
bella run -- python app.py
```

## Why use typed secrets?

- **Type safety** — `PORT` is an `int`, not a string you forget to parse
- **IDE autocomplete** — `AppSecrets().` shows all available secrets
- **Fail-fast validation** — missing secrets throw at startup, not in production
- **Safe to commit** — generated file contains NO secret values, just key names and types

## What's generated

`bella secrets generate python` reads your project's secret manifest and emits `secrets.py`:

| Secret               | Type    | Accessor                          |
|----------------------|---------|-----------------------------------|
| `PORT`               | `int`   | `s.port`                          |
| `DATABASE_URL`       | `str`   | `s.database_url`                  |
| `EXTERNAL_API_KEY`   | `str`   | `s.external_api_key`              |
| `ENABLE_FEATURE_FLAGS` | `bool` | `s.enable_feature_flags`         |
| `SIGNING_KEY`        | `bytes` | `s.signing_key`                   |

## Regenerate after adding secrets

```bash
bella secrets generate python -o secrets.py
git add secrets.py  # safe — no values
```
