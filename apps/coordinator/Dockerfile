FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY packages/ ./packages/
COPY apps/coordinator/ ./apps/coordinator/
RUN pip install --no-cache-dir .
ENV PYTHONPATH=/app
EXPOSE 8100
CMD ["python", "apps/coordinator/main.py"]
