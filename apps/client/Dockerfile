FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir .
COPY packages/ ./packages/
COPY apps/client/ ./apps/client/
ENV PYTHONPATH=/app
CMD ["python", "apps/client/main.py"]
