# Sample 01: `.env` File Approach (Python)

**Pattern:** CLI writes secrets to a `.env` file → app reads it with `python-dotenv`.

Works with **any Python framework** — Flask, Django, FastAPI, plain scripts, etc.

---

## How it works

```
bella secrets get -o .env   →   .env file on disk   →   load_dotenv()   →   os.environ
```

## Setup

```bash
pip install -r requirements.txt

# Authenticate
bella login --api-key bax-xxxxxxxxxxxxxxxxxxxx

export BELLA_BAXTER_URL=http://localhost:5522   # your Bella Baxter instance

# Pull secrets then run
bella secrets get -o .env && python app.py
```

## Works with any framework

```bash
# Flask
bella secrets get -o .env && flask run

# Django
bella secrets get -o .env && python manage.py runserver

# FastAPI (uvicorn)
bella secrets get -o .env && uvicorn main:app --reload

# Gunicorn
bella secrets get -o .env && gunicorn app:app

# Celery workers
bella secrets get -o .env && celery -A tasks worker

# pytest (inject test secrets)
bella secrets get -o .env && pytest
```

## Django .env integration

Django doesn't auto-load `.env` by default. Add to the top of `settings.py`:

```python
from dotenv import load_dotenv
load_dotenv()  # reads .env from project root

SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
DATABASE_URL = os.environ["DATABASE_URL"]
```

## Security notes

- Add `.env` to `.gitignore` — never commit secrets
- The file is only as secure as the filesystem
- For production, prefer the SDK approach (Flask/Django/FastAPI samples) for live reload without restarts
