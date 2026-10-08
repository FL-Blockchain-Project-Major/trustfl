FROM python:3.11-slim

# Install Node.js for ZKP subprocess
RUN apt-get update && apt-get install -y curl && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml requirements.txt README.md ./
COPY packages/ ./packages/
COPY apps/coordinator/ ./apps/coordinator/
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir --no-deps .
ENV PYTHONPATH=/app
EXPOSE 8100
CMD ["python", "apps/coordinator/main.py"]
