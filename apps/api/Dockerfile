FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml requirements.txt README.md ./
COPY packages/ ./packages/
COPY apps/api/ ./apps/api/
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir --no-deps .
# PYTHONPATH must include each package subdirectory so sub-packages are
# importable as top-level modules.  See apps/client/Dockerfile for details.
ENV PYTHONPATH=/app/packages/crypto:/app/packages/ml_core:/app/packages/schemas:/app/packages/storage:/app/packages/fl_core:/app/packages/blockchain:/app
ENV ENVIRONMENT=production
ENV API_PORT=8000
EXPOSE 8000
RUN useradd --create-home --uid 10001 trustfl && chown -R trustfl:trustfl /app
USER trustfl
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/', timeout=3)"
CMD ["sh", "-c", "alembic -c apps/api/alembic.ini upgrade head && exec uvicorn apps.api.main:app --host 0.0.0.0 --port ${API_PORT}"]
