FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir . slowapi bandit pip-audit sqlalchemy alembic
COPY packages/ ./packages/
COPY apps/api/ ./apps/api/
ENV PYTHONPATH=/app
EXPOSE 8000
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
