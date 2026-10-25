FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml requirements.txt README.md ./
COPY packages/ ./packages/
COPY apps/api/ ./apps/api/
COPY apps/coordinator/ ./apps/coordinator/
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir --no-deps .
# PYTHONPATH must include each package subdirectory so sub-packages are
# importable as top-level modules.  See apps/client/Dockerfile for details.
ENV PYTHONPATH=/app/packages/crypto:/app/packages/ml_core:/app/packages/schemas:/app/packages/storage:/app/packages/fl_core:/app/packages/blockchain:/app
EXPOSE 8100
RUN useradd --create-home --uid 10001 trustfl && chown -R trustfl:trustfl /app
USER trustfl
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8100/health', timeout=3)"
CMD ["python", "apps/coordinator/main.py"]
