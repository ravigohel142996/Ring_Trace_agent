#!/usr/bin/env bash
# RingTrace — start a local FalkorDB instance for development.
#
# Preferred path: Docker (works everywhere, zero native build issues).
# This script starts a single FalkorDB container with the default demo
# settings used by RingTrace (.env.example). For the full stack (FalkorDB +
# the Streamlit dashboard together) use `docker compose up` instead — this
# script is just a fast way to get *only* the database running while you
# iterate on Python code locally with `streamlit run app/dashboard.py`.
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
    echo "[RingTrace] Pulling + starting falkordb/falkordb on port ${PORT} (+3000 for the FalkorDB browser UI)..."
    docker run -d --name "${CONTAINER_NAME}" \
      -p "${PORT}:6379" -p 3000:3000 \
      -v ringtrace_falkordb_data:/data \
      falkordb/falkordb:latest
  fi
  echo "[RingTrace] FalkorDB is starting. Verify with:  redis-cli -p ${PORT} PING"
  exit 0
fi

cat <<'EOF'
[RingTrace] Docker was not found on this machine.

FalkorDB has no pure-pip install — it is a Redis module (native .so) that
must be loaded by a Redis server that is new enough (Redis >= 7.2). Options:

  1. Install Docker, then re-run this script (recommended — by far the
     simplest path, and what docker-compose.yml also uses).
  2. Follow FalkorDB's native build/run instructions for your OS:
     https://docs.falkordb.com/

NOTE: on some constrained sandboxes (older glibc, no Docker), you may need
to build Redis 7.4+ from source and run it with:
    redis-server --loadmodule /path/to/falkordb.so --port 6379
RingTrace was developed and demoed against exactly this setup; see the
"Local / sandboxed environments" section of README.md for a worked example.
EOF
exit 1
