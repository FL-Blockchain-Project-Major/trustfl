FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml requirements.txt README.md ./
COPY packages/ ./packages/
COPY apps/client/ ./apps/client/
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir --no-deps . && \
    apt-get update && apt-get install -y --no-install-recommends nodejs npm && \
    cd packages/zkp && npm ci --omit=dev && \
    rm -rf /var/lib/apt/lists/*
# PYTHONPATH must include each package subdirectory so sub-packages (e.g.
# trustfl_crypto, trustfl_ml) are importable as top-level modules.
# The repo layout is packages/<name>/trustfl_<name>/, so each packages/<name>/
# directory must appear on the path.  The repo root alone is insufficient.
ENV PYTHONPATH=/app/packages/crypto:/app/packages/ml_core:/app/packages/schemas:/app/packages/storage:/app/packages/fl_core:/app/packages/blockchain:/app/packages/zkp:/app
RUN useradd --create-home --uid 10001 trustfl && \
    mkdir -p /var/lib/trustfl/keys && \
    chown -R trustfl:trustfl /app /var/lib/trustfl
USER trustfl
CMD ["python", "apps/client/main.py"]
