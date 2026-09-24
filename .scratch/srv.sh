set -u
ROOT=/home/ia02/S9-Knowledge/.claude/worktrees/agent-a099e22c532796ef0
cd "$ROOT/viewer"
PORT=$1; STATE=$2; LABEL=$3
mkdir -p "$STATE"
export S9K_AUTH_ENABLED=true
export S9K_AUTH_DB_PATH="$STATE/auth.db"
export S9K_CSRF_SECRET="${S9K_CSRF_SECRET:-$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')}"
export S9K_SESSION_SECURE=false
export PYTHONPATH="$ROOT/viewer:$ROOT"
mkdir -p /tmp/bs
python3 -m uvicorn app.main:app --port $PORT --host 127.0.0.1 > /tmp/bs/$LABEL.log 2>&1 &
echo $! > /tmp/bs/$LABEL.pid
for i in $(seq 1 80); do
  if curl -s -o /dev/null http://127.0.0.1:$PORT/setup/admin; then break; fi
  if ! kill -0 $(cat /tmp/bs/$LABEL.pid) 2>/dev/null; then echo "MUERTO"; exit 1; fi
  python3 -c "import time;time.sleep(0.4)"
done
echo LISTO
