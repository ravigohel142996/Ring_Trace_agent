#!/usr/bin/env bash
# RingTrace — start a local FalkorDB instance for development.
#
# Preferred path: Docker (works everywhere, zero native build issues).
# This script starts only FalkorDB with the default demo settings used by
# RingTrace (.env.example). For the full stack (private FalkorDB + React UI
# and FastAPI on port 8000), use `docker compose up` instead. This helper is
# for local API development with `uvicorn api.main:app`.
set -euo pipefail

CONTAINER_NAME="ringtrace-falkordb"
PORT="${FALKORDB_PORT:-6379}"

if command -v docker >/dev/null 2>&1; then
  if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "[RingTrace] FalkorDB container '${CONTAINER_NAME}' is already running on port ${PORT}."
    exit 0
  fi
  if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "[RingTrace] Starting existing FalkorDB container..."
    docker start "${CONTAINER_NAME}"
  else
    echo "[RingTrace] Pulling + starting falkordb/falkordb on local port ${PORT}..."
    docker run -d --name "${CONTAINER_NAME}" \
      -p "127.0.0.1:${PORT}:6379" \
      -v ringtrace_falkordb_data:/data \
      falkordb/falkordb:latest
  fi
  echo "[RingTrace] FalkorDB is starting. Verify with:  redis-cli -p ${PORT} PING"
  exit 0
fi

cat <<'EOF'
[RingTrace] Docker was not found on this machine.

FalkorDB has no pure-pip install — it is a Redis module (native .so) that
must be loaded by a Redis server supported by that module release (recent
FalkorDB modules require Redis 8.0+). Options:

  1. Install Docker, then re-run this script (recommended — by far the
     simplest path, and what docker-compose.yml also uses).
  2. Follow FalkorDB's native build/run instructions for your OS:
     https://docs.falkordb.com/

NOTE: on some constrained sandboxes (older glibc, no Docker), you may need
to build a Redis version supported by the FalkorDB module from source and run it with:
    redis-server --loadmodule /path/to/falkordb.so --port 6379
See the README's Setup section for the supported Docker and local-development
paths. Container images remain the recommended option for a local demo.
EOF
exit 1
