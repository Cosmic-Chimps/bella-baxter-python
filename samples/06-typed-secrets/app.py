"""
Typed Secrets sample — one secret per Bella type:
  String → external_api_key
  Int    → port
  Bool   → enable_features
  Uri    → database_url
  JSON   → app_config  ← parsed into AppConfigShape dataclass
  GUID   → app_id      ← parsed into uuid.UUID

Workflow:
  bella secrets generate python -p my-project -e production -o secrets.py
  bella exec -- python app.py
"""

from dotenv import load_dotenv
from secrets import AppSecrets

load_dotenv()

s = AppSecrets()

print("=== Bella Baxter: Typed Secrets (Python) ===")
print()
print(f"String  EXTERNAL_API_KEY : {s.external_api_key[:4]}***")
print(f"Int     PORT             : {s.port!r}  ← type: {type(s.port).__name__}")
print(f"Bool    ENABLE_FEATURES  : {s.enable_features!r}  ← type: {type(s.enable_features).__name__}")
print(f"Uri     DATABASE_URL     : host={s.database_url.hostname}  ← scheme: {s.database_url.scheme}")
print(f"JSON    APP_CONFIG       : {s.app_config}")
print(f"           .setting1     : {s.app_config.setting1!r}  ← str")
print(f"           .setting2     : {s.app_config.setting2!r}  ← int")
print(f"GUID    APP_ID           : {s.app_id}  ← type: {type(s.app_id).__name__}")
print()
print("No raw os.environ calls — secrets are typed, validated, and structured.")
