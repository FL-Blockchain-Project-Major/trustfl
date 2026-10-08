FROM python:3.11-slim

# Install Node.js for ZKP subprocess
RUN apt-get update && apt-get install -y curl && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml requirements.txt README.md ./
COPY packages/ ./packages/
COPY apps/api/ ./apps/api/
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir --no-deps .
ENV PYTHONPATH=/app
ENV ENVIRONMENT=production
EXPOSE 8000
CMD ["sh", "-c", "alembic -c apps/api/alembic.ini upgrade head && exec uvicorn apps.api.main:app --host 0.0.0.0 --port 8000"]
