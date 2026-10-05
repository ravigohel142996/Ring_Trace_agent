#!/usr/bin/env bash
# RingTrace — full pipeline: generate synthetic data -> load into FalkorDB
# -> train the explainable risk model -> print a sanity-check summary.
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

echo "[3/3] Done. Launch the dashboard with:"
echo "    streamlit run app/dashboard.py --server.address 0.0.0.0 --server.port 8501"
