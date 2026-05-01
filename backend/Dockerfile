# Backend Dockerfile

FROM python:3.12-slim

WORKDIR /app

# Install dependencies first so Docker can cache this layer independently of
# source code changes. Rebuilding after a code-only change will skip this step.

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY /app ./app/

# Copy Alembic config and migrations so the entrypoint can run migrations
COPY alembic.ini .
COPY alembic/ ./alembic/

EXPOSE 8000

# Run Alembic migrations before starting the server so the schema is always 
# up-to-date.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1"]