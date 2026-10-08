#!/usr/bin/env bash
# RingTrace — generate the synthetic graph and train the explainable risk model.
#
# Usage:
#   ./scripts/run_pipeline.sh
#
# Requires FalkorDB to already be reachable (see scripts/setup_falkordb_local.sh
# for a local/no-Docker option, or `docker compose up falkordb` otherwise).
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .env ]; then
  set -a; source .env; set +a
fi

echo "[1/3] Generating synthetic fraud-ring dataset + loading into FalkorDB..."
python -m ingestion.load_to_falkordb

echo "[2/3] Training the explainable risk model on graph-derived features..."
python -m models.train

echo "[3/3] Done. Build the frontend, then launch the single-port app with:"
echo "    npm --prefix frontend ci && npm --prefix frontend run build"
if [ -f .env ]; then
  echo "    uvicorn api.main:app --env-file .env --host 0.0.0.0 --port 8000"
else
  echo "    uvicorn api.main:app --host 0.0.0.0 --port 8000"
fi
