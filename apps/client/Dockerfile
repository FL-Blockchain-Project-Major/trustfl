FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml requirements.txt README.md ./
COPY packages/ ./packages/
COPY apps/client/ ./apps/client/
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir --no-deps .
ENV PYTHONPATH=/app
RUN useradd --create-home --uid 10001 trustfl && \
    mkdir -p /var/lib/trustfl/keys && \
    chown -R trustfl:trustfl /app /var/lib/trustfl
USER trustfl
CMD ["python", "apps/client/main.py"]
