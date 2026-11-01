FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend_py

WORKDIR /app
COPY pyproject.toml README.md /app/backend_py/
COPY app /app/backend_py/app
COPY migrations /app/backend_py/migrations
COPY scripts /app/backend_py/scripts
COPY alembic.ini /app/backend_py/alembic.ini
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir "/app/backend_py"

WORKDIR /app/backend_py
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/v1/health', timeout=3)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]

