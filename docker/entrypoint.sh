#!/usr/bin/env bash
set -euo pipefail
cd /app

FALKORDB_HOST="${FALKORDB_HOST:-falkordb}"
FALKORDB_PORT="${FALKORDB_PORT:-6379}"

echo "[entrypoint] Waiting for FalkorDB at ${FALKORDB_HOST}:${FALKORDB_PORT}..."
for i in $(seq 1 30); do
  if python -c "
import redis, sys
try:
    r = redis.Redis(host='${FALKORDB_HOST}', port=${FALKORDB_PORT}, socket_connect_timeout=2)
    r.ping()
    sys.exit(0)
except Exception:
    sys.exit(1)
"; then
    echo "[entrypoint] FalkorDB is reachable."
    break
  fi
  sleep 2
  if [ "$i" -eq 30 ]; then
    echo "[entrypoint] FalkorDB never became reachable; continuing anyway (dashboard will show a clear error)."
  fi
done

NODE_COUNT=$(python -c "
from graph.connection import get_graph
try:
    g = get_graph()
    res = g.query('MATCH (n) RETURN count(n) AS c')
    print(res.result_set[0][0])
except Exception:
    print(0)
" 2>/dev/null || echo 0)

if [ "${NODE_COUNT}" = "0" ] || [ "${FORCE_REBUILD:-}" = "1" ]; then
  echo "[entrypoint] Graph is empty (or FORCE_REBUILD=1) — running the synthetic data + training pipeline..."
  python -m ingestion.load_to_falkordb
  python -m models.train
else
  echo "[entrypoint] Graph already has ${NODE_COUNT} node(s) — skipping pipeline (set FORCE_REBUILD=1 to force)."
fi

echo "[entrypoint] Launching dashboard..."
exec streamlit run app/dashboard.py \
  --server.address 0.0.0.0 \
  --server.port 8501 \
  --server.headless true \
  --server.enableXsrfProtection false
