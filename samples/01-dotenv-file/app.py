"""
Sample app — reads secrets written to .env file by the Bella CLI.

Start with:
    bella secrets get -p my-project -e production -o .env && python app.py
"""

import os
from dotenv import load_dotenv

# Load .env file into os.environ
load_dotenv()

port    = os.environ.get("PORT", "3000")
db_url  = os.environ.get("DATABASE_URL", "(not set)")
api_key = os.environ.get("EXTERNAL_API_KEY", "(not set)")

print("=== Bella Baxter: .env file sample (Python) ===")
print(f"PORT         : {port}")
print(f"DATABASE_URL : {db_url}")
print(f"API_KEY      : {api_key[:4] + '***' if len(api_key) > 6 else '(not set)'}")
print()
print("All env vars now available via os.environ / os.getenv()")
print("Loaded from .env file written by: bella secrets get -o .env")
