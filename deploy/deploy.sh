#!/usr/bin/env bash
# Push code to the VPS and restart the service. Run from the repo root on the
# local machine. Secrets (.env) are NOT synced here — transfer once per RUNBOOK §4.
set -euo pipefail

HOST="${KGB_HOST:?Set KGB_HOST=user@server}"
PORT="${KGB_PORT:-22}"
DEST="${KGB_DEST:-KGB_Bot}"   # path relative to the remote user's home

echo ">> Syncing code to $HOST:$DEST"
rsync -az --delete -e "ssh -p $PORT" \
  --exclude '.venv' \
  --exclude 'data' \
  --exclude '.git' \
  --exclude '.env' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  ./ "$HOST:$DEST/"

echo ">> Installing & restarting on remote"
ssh -p "$PORT" "$HOST" "bash -lc '
  set -e
  cd $DEST
  [ -d .venv ] || python3 -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -e .
  export XDG_RUNTIME_DIR=/run/user/\$(id -u)
  systemctl --user restart secretary-bot || echo \"service not installed yet — see RUNBOOK\"
  systemctl --user --no-pager status secretary-bot | head -5 || true
'"
echo ">> Done"
