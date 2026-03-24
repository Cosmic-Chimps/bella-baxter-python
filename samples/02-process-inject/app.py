"""
Sample app — reads secrets injected directly into the process by bella run.

Start with:
    bella run -p my-project -e production -- python app.py

No .env file is written. Secrets are already in os.environ from the parent process.
"""

import os

port    = os.environ.get("PORT", "3000")
db_url  = os.environ.get("DATABASE_URL", "(not set)")
api_key = os.environ.get("EXTERNAL_API_KEY", "(not set)")

print("=== Bella Baxter: process inject sample (Python) ===")
print(f"PORT         : {port}")
print(f"DATABASE_URL : {db_url}")
print(f"API_KEY      : {api_key[:4] + '***' if len(api_key) > 6 else '(not set)'}")
print()
print("Secrets injected directly into process by: bella run -- python app.py")
print("No .env file was written.")
