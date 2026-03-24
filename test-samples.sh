#!/usr/bin/env bash
# test-samples.sh — run all Python SDK samples and verify outputs
# Usage: ./test-samples.sh <api-key>
set -euo pipefail

API_KEY="${1:-}"
if [[ -z "$API_KEY" ]]; then
    echo "Usage: $0 <api-key>"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SDK_DIR="$SCRIPT_DIR"
SAMPLES_DIR="$SCRIPT_DIR/samples"
DEMO_ENV="$SCRIPT_DIR/../../../demo.env"

SAMPLE_01="$SAMPLES_DIR/01-dotenv-file"
SAMPLE_02="$SAMPLES_DIR/02-process-inject"
SAMPLE_03="$SAMPLES_DIR/03-flask"
SAMPLE_04="$SAMPLES_DIR/04-django"
SAMPLE_05="$SAMPLES_DIR/05-fastapi"
SAMPLE_06="$SAMPLES_DIR/06-typed-secrets"

FLASK_PORT=8093
DJANGO_PORT=8094
FASTAPI_PORT=8095

VENV_DIR="$SCRIPT_DIR/.venv-test"
PYTHON3="$(command -v python3)"
PYTHON="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"

# ── Expected values (read from demo.env) ─────────────────────────────────────
PORT_EXPECTED="$(grep '^PORT=' "$DEMO_ENV" | cut -d= -f2-)"
DATABASE_URL_EXPECTED="$(grep '^DATABASE_URL=' "$DEMO_ENV" | cut -d= -f2-)"
EXTERNAL_API_KEY_EXPECTED="$(grep '^EXTERNAL_API_KEY=' "$DEMO_ENV" | cut -d= -f2-)"
GLEAP_API_KEY_EXPECTED="$(grep '^GLEAP_API_KEY=' "$DEMO_ENV" | cut -d= -f2-)"
ENABLE_FEATURES_EXPECTED="$(grep '^ENABLE_FEATURES=' "$DEMO_ENV" | cut -d= -f2-)"
APP_ID_EXPECTED="$(grep '^APP_ID=' "$DEMO_ENV" | cut -d= -f2-)"
CONNSTRING_EXPECTED="$(grep '^ConnectionStrings__Postgres=' "$DEMO_ENV" | cut -d= -f2-)"
APP_CONFIG_EXPECTED="$(grep '^APP_CONFIG=' "$DEMO_ENV" | cut -d= -f2- | sed 's/^"//;s/"$//' | sed 's/\\"/"/g')"

# ── Result tracking ───────────────────────────────────────────────────────────
PASS=0
FAIL=0
RESULTS=()

pass() {
    local name="$1"
    echo "  ✅ $name"
    PASS=$((PASS + 1))
    RESULTS+=("PASS: $name")
}

fail() {
    local name="$1"
    echo "  ❌ $name"
    FAIL=$((FAIL + 1))
    RESULTS+=("FAIL: $name")
}

check_val() {
    local label="$1" expected="$2" actual="$3"
    if [[ "$actual" == "$expected" ]]; then
        pass "$label"
    else
        fail "$label -- expected '$expected' got '$actual'"
    fi
}

# Check all 8 secrets from a JSON object (via jq)
check_server_secrets() {
    local prefix="$1"
    local json="$2"

    check_val "$prefix PORT"                      "$PORT_EXPECTED"           "$(echo "$json" | jq -r '.PORT')"
    check_val "$prefix DATABASE_URL"              "$DATABASE_URL_EXPECTED"   "$(echo "$json" | jq -r '.DATABASE_URL')"
    check_val "$prefix EXTERNAL_API_KEY"          "$EXTERNAL_API_KEY_EXPECTED" "$(echo "$json" | jq -r '.EXTERNAL_API_KEY')"
    check_val "$prefix GLEAP_API_KEY"             "$GLEAP_API_KEY_EXPECTED"  "$(echo "$json" | jq -r '.GLEAP_API_KEY')"
    check_val "$prefix ENABLE_FEATURES"           "$ENABLE_FEATURES_EXPECTED" "$(echo "$json" | jq -r '.ENABLE_FEATURES')"
    check_val "$prefix APP_ID"                    "$APP_ID_EXPECTED"         "$(echo "$json" | jq -r '.APP_ID')"
    check_val "$prefix ConnectionStrings__Postgres" "$CONNSTRING_EXPECTED"   "$(echo "$json" | jq -r '.["ConnectionStrings__Postgres"]')"
    check_val "$prefix APP_CONFIG"                "$APP_CONFIG_EXPECTED"     "$(echo "$json" | jq -r '.APP_CONFIG')"
}

# Kill any process listening on a port
kill_port() {
    local port="$1"
    local pids
    pids="$(lsof -ti tcp:"$port" 2>/dev/null || true)"
    if [[ -n "$pids" ]]; then
        echo "$pids" | xargs kill -9 2>/dev/null || true
        sleep 1
    fi
}

# Wait for a server to respond on a given URL (up to 60s)
wait_for_server() {
    local url="$1"
    local max=60
    for ((i = 1; i <= max; i++)); do
        if curl -sf "$url" -o /dev/null 2>/dev/null; then
            return 0
        fi
        sleep 1
    done
    return 1
}

# ── Authentication ────────────────────────────────────────────────────────────
echo ""
echo "─── Authentication ──────────────────────────────────────────────────"
if bella login --api-key "$API_KEY" --url http://localhost:5522 --force 2>/dev/null; then
    pass "bella login --api-key"
else
    fail "bella login --api-key"
    echo "FATAL: could not log in — aborting"
    exit 1
fi

# ── Set up virtual environment ────────────────────────────────────────────────
echo ""
echo "─── Setup venv ──────────────────────────────────────────────────────"
if [[ ! -d "$VENV_DIR" ]]; then
    "$PYTHON3" -m venv "$VENV_DIR"
fi
"$PIP" install --quiet --upgrade pip
"$PIP" install --quiet -e "$SDK_DIR"
echo "  SDK installed (bella-baxter $("$PIP" show bella-baxter | grep '^Version:' | awk '{print $2}'))"

# ── Install dependencies ──────────────────────────────────────────────────────
echo ""
echo "─── Install dependencies ────────────────────────────────────────────"
for sample_name in 01-dotenv-file 03-flask 04-django 05-fastapi 06-typed-secrets; do
    req_file="$SAMPLES_DIR/$sample_name/requirements.txt"
    if [[ -f "$req_file" ]]; then
        if "$PIP" install --quiet -r "$req_file" 2>/dev/null; then
            pass "pip install $sample_name"
        else
            fail "pip install $sample_name"
        fi
    fi
done

# ── 01-dotenv-file ────────────────────────────────────────────────────────────
echo ""
echo "─── 01-dotenv-file ──────────────────────────────────────────────────"
cd "$SAMPLE_01"
DOT_ENV_FILE="$SAMPLE_01/.env"
rm -f "$DOT_ENV_FILE"

if bella secrets get -o "$DOT_ENV_FILE" 2>/dev/null; then
    pass "bella secrets get -o .env"
else
    fail "bella secrets get -o .env"
fi

if [[ -f "$DOT_ENV_FILE" ]]; then
    # Read .env values (handle quoted values)
    _port="$(grep '^PORT=' "$DOT_ENV_FILE" | cut -d= -f2-)"
    _db_url="$(grep '^DATABASE_URL=' "$DOT_ENV_FILE" | cut -d= -f2-)"
    _api_key="$(grep '^EXTERNAL_API_KEY=' "$DOT_ENV_FILE" | cut -d= -f2-)"
    _gleap="$(grep '^GLEAP_API_KEY=' "$DOT_ENV_FILE" | cut -d= -f2-)"
    _enable="$(grep '^ENABLE_FEATURES=' "$DOT_ENV_FILE" | cut -d= -f2-)"
    _app_id="$(grep '^APP_ID=' "$DOT_ENV_FILE" | cut -d= -f2-)"
    _connstr="$(grep '^ConnectionStrings__Postgres=' "$DOT_ENV_FILE" | cut -d= -f2-)"
    _app_cfg="$(grep '^APP_CONFIG=' "$DOT_ENV_FILE" | cut -d= -f2- | sed 's/^"//;s/"$//' | sed 's/\\"/"/g')"
    check_val "01: PORT"                      "$PORT_EXPECTED"             "$_port"
    check_val "01: DATABASE_URL"              "$DATABASE_URL_EXPECTED"     "$_db_url"
    check_val "01: EXTERNAL_API_KEY"          "$EXTERNAL_API_KEY_EXPECTED" "$_api_key"
    check_val "01: GLEAP_API_KEY"             "$GLEAP_API_KEY_EXPECTED"    "$_gleap"
    check_val "01: ENABLE_FEATURES"           "$ENABLE_FEATURES_EXPECTED"  "$_enable"
    check_val "01: APP_ID"                    "$APP_ID_EXPECTED"           "$_app_id"
    check_val "01: ConnectionStrings__Postgres" "$CONNSTRING_EXPECTED"     "$_connstr"
    check_val "01: APP_CONFIG"                "$APP_CONFIG_EXPECTED"       "$_app_cfg"
fi

# Run the app to ensure it works with the .env file
if "$PYTHON" "$SAMPLE_01/app.py" 2>/dev/null | grep -q "PORT"; then
    pass "01: app.py runs ok"
else
    fail "01: app.py runs ok"
fi
rm -f "$DOT_ENV_FILE"

# ── 02-process-inject ─────────────────────────────────────────────────────────
echo ""
echo "─── 02-process-inject ───────────────────────────────────────────────"
cd "$SAMPLE_02"
OUTPUT_02="$(bella run --app python-02-process-inject -- "$PYTHON" app.py 2>/dev/null)"

check_val "02: PORT"         "$PORT_EXPECTED"         "$(echo "$OUTPUT_02" | grep '^PORT' | awk '{print $3}')"
check_val "02: DATABASE_URL" "$DATABASE_URL_EXPECTED" "$(echo "$OUTPUT_02" | grep '^DATABASE_URL' | awk '{print $3}')"

# ── 06-typed-secrets ─────────────────────────────────────────────────────────
echo ""
echo "─── 06-typed-secrets ────────────────────────────────────────────────"
cd "$SAMPLE_06"
OUTPUT_06="$(bella run --app python-06-typed-secrets -- "$PYTHON" app.py 2>/dev/null)"

# Check a selection of typed values visible in stdout
check_val "06: PORT (int)"           "$PORT_EXPECTED"             "$(echo "$OUTPUT_06" | grep '^Int.*PORT' | grep -oE '[0-9]+'  | head -1)"
check_val "06: ENABLE_FEATURES (bool)" "True"                     "$(echo "$OUTPUT_06" | grep '^Bool' | grep -oE '(True|False)' | head -1)"
check_val "06: APP_ID (uuid)"        "$APP_ID_EXPECTED"           "$(echo "$OUTPUT_06" | grep '^GUID.*APP_ID' | grep -oE '[0-9a-f-]{36}')"

# ── 03-flask ──────────────────────────────────────────────────────────────────
echo ""
echo "─── 03-flask ────────────────────────────────────────────────────────"
kill_port $FLASK_PORT

cd "$SAMPLE_03"
FLASK_PID_FILE="/tmp/bella-flask-test.pid"
FLASK_LOG="/tmp/bella-flask-test.log"

FLASK_APP=app:create_app bella exec --app python-03-flask -- "$VENV_DIR/bin/flask" run --host 127.0.0.1 --port "$FLASK_PORT" \
    > "$FLASK_LOG" 2>&1 &
echo $! > "$FLASK_PID_FILE"

if wait_for_server "http://127.0.0.1:$FLASK_PORT/health"; then
    pass "03-flask: server started"
    FLASK_JSON="$(curl -sf "http://127.0.0.1:$FLASK_PORT/secrets")"
    check_server_secrets "03 /" "$FLASK_JSON"
else
    fail "03-flask: server started -- did not respond within 60s"
    echo ""
    echo "  Flask log:"
    cat "$FLASK_LOG" | head -40
fi

# Cleanup
if [[ -f "$FLASK_PID_FILE" ]]; then
    kill "$(cat "$FLASK_PID_FILE")" 2>/dev/null || true
    rm -f "$FLASK_PID_FILE"
fi
kill_port $FLASK_PORT

# ── 04-django ─────────────────────────────────────────────────────────────────
echo ""
echo "─── 04-django ───────────────────────────────────────────────────────"
kill_port $DJANGO_PORT

cd "$SAMPLE_04"
DJANGO_LOG="/tmp/bella-django-test.log"
DJANGO_PID_FILE="/tmp/bella-django-test.pid"

DJANGO_SETTINGS_MODULE=settings bella exec --app python-04-django -- \
    "$PYTHON" "$SAMPLE_04/manage.py" runserver "127.0.0.1:$DJANGO_PORT" --noreload \
    > "$DJANGO_LOG" 2>&1 &
echo $! > "$DJANGO_PID_FILE"

if wait_for_server "http://127.0.0.1:$DJANGO_PORT/health"; then
    pass "04-django: server started"
    DJANGO_JSON="$(curl -sf "http://127.0.0.1:$DJANGO_PORT/secrets")"
    check_server_secrets "04 /" "$DJANGO_JSON"
else
    fail "04-django: server started -- did not respond within 60s"
    echo ""
    echo "  Django log:"
    cat "$DJANGO_LOG" | head -40
fi

# Cleanup
if [[ -f "$DJANGO_PID_FILE" ]]; then
    kill "$(cat "$DJANGO_PID_FILE")" 2>/dev/null || true
    rm -f "$DJANGO_PID_FILE"
fi
kill_port $DJANGO_PORT

# ── 05-fastapi ────────────────────────────────────────────────────────────────
echo ""
echo "─── 05-fastapi ──────────────────────────────────────────────────────"
kill_port $FASTAPI_PORT

cd "$SAMPLE_05"
FASTAPI_LOG="/tmp/bella-fastapi-test.log"
FASTAPI_PID_FILE="/tmp/bella-fastapi-test.pid"

bella exec --app python-05-fastapi -- "$VENV_DIR/bin/uvicorn" main:app --host 127.0.0.1 --port "$FASTAPI_PORT" \
    > "$FASTAPI_LOG" 2>&1 &
echo $! > "$FASTAPI_PID_FILE"

if wait_for_server "http://127.0.0.1:$FASTAPI_PORT/health"; then
    pass "05-fastapi: server started"
    FASTAPI_JSON="$(curl -sf "http://127.0.0.1:$FASTAPI_PORT/secrets")"
    check_server_secrets "05 /" "$FASTAPI_JSON"
else
    fail "05-fastapi: server started -- did not respond within 60s"
    echo ""
    echo "  FastAPI log:"
    cat "$FASTAPI_LOG" | head -40
fi

# Cleanup
if [[ -f "$FASTAPI_PID_FILE" ]]; then
    kill "$(cat "$FASTAPI_PID_FILE")" 2>/dev/null || true
    rm -f "$FASTAPI_PID_FILE"
fi
kill_port $FASTAPI_PORT

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "─── Summary ──────────────────────────────────────────────────────────"
for r in "${RESULTS[@]}"; do
    echo "  $r"
done
echo ""
TOTAL=$((PASS + FAIL))
echo "PASS: $PASS  FAIL: $FAIL  TOTAL: $TOTAL"
echo ""

[[ $FAIL -eq 0 ]]
