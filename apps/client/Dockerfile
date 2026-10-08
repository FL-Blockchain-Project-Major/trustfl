FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml requirements.txt README.md ./
COPY packages/ ./packages/
COPY apps/client/ ./apps/client/
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir --no-deps .
ENV PYTHONPATH=/app
RUN useradd --create-home --uid 10001 trustfl && chown -R trustfl:trustfl /app
USER trustfl
CMD ["python", "apps/client/main.py"]
