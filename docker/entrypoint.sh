#!/usr/bin/env bash
set -euo pipefail
cd /app

FALKORDB_HOST="${FALKORDB_HOST:-falkordb}"
FALKORDB_PORT="${FALKORDB_PORT:-6379}"
export FALKORDB_HOST FALKORDB_PORT
export FALKORDB_USERNAME="${FALKORDB_USERNAME:-}"
export FALKORDB_PASSWORD="${FALKORDB_PASSWORD:-}"
FALKORDB_REACHABLE=0

echo "[entrypoint] Waiting for FalkorDB at ${FALKORDB_HOST}:${FALKORDB_PORT}..."
for i in $(seq 1 30); do
  if python -c "
import os, redis, sys
try:
    redis.Redis(
        host=os.getenv('FALKORDB_HOST', 'falkordb'),
        port=int(os.getenv('FALKORDB_PORT', '6379')),
        username=os.getenv('FALKORDB_USERNAME') or None,
        password=os.getenv('FALKORDB_PASSWORD') or None,
        socket_connect_timeout=2,
    ).ping()
    sys.exit(0)
except Exception:
    sys.exit(1)
"; then
    FALKORDB_REACHABLE=1
    echo "[entrypoint] FalkorDB is reachable."
    break
  fi
  sleep 2
done

if [ "${FALKORDB_REACHABLE}" = "1" ]; then
  NODE_COUNT=$(python -c "
from graph.connection import get_graph
try:
    result = get_graph().query('MATCH (n) RETURN count(n) AS c')
    print(result.result_set[0][0])
except Exception:
    print(0)
" 2>/dev/null || echo 0)

  if [ "${NODE_COUNT}" = "0" ] || [ "${FORCE_REBUILD:-}" = "1" ]; then
    echo "[entrypoint] Graph is empty (or FORCE_REBUILD=1) — loading the synthetic demo dataset and training the risk model..."
    python -m ingestion.load_to_falkordb
    python -m models.train
  else
    echo "[entrypoint] Graph already has ${NODE_COUNT} node(s) — skipping data rebuild (set FORCE_REBUILD=1 to force)."
  fi
else
  echo "[entrypoint] FalkorDB is still unavailable; skipping seed/training so the API can report graph health."
fi

echo "[entrypoint] Serving the React app and API together on port 8000."
exec uvicorn api.main:app --host 0.0.0.0 --port "${PORT:-8000}"
