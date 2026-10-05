# RingTrace — Fraud-Ring Detective Agent
# Streamlit dashboard + agent container. FalkorDB runs as its own service
# (see docker-compose.yml) — this image only contains the Python app.
FROM python:3.11-slim

WORKDIR /app

# System deps: none beyond build-essentials needed for scikit-learn wheels
# on most platforms; kept minimal on purpose (hackathon MVP, not over-engineered).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

EXPOSE 8501

# Entry script: wait for FalkorDB, run the ingestion+training pipeline once
# if the graph is empty, then launch the dashboard.
COPY docker/entrypoint.sh /app/docker/entrypoint.sh
RUN chmod +x /app/docker/entrypoint.sh

ENTRYPOINT ["/app/docker/entrypoint.sh"]
