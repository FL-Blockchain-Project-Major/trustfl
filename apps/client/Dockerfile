FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY packages/ ./packages/
COPY apps/client/ ./apps/client/
RUN pip install --no-cache-dir .
ENV PYTHONPATH=/app
CMD ["python", "apps/client/main.py"]
