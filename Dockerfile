FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV ALLOW_HARD_RESET=0

WORKDIR /app

# System deps (for bcrypt/cryptography wheels, usually ok; keep minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    tesseract-ocr \
    tesseract-ocr-deu \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app /app/app
COPY README.md /app/README.md
COPY Dockerfile /app/Dockerfile
COPY docker-compose.yml /app/docker-compose.yml
COPY CODEX_AGENT_GUIDELINE.md /app/CODEX_AGENT_GUIDELINE.md
COPY alembic.ini /app/alembic.ini
COPY alembic /app/alembic

ENV DATA_DIR=/data \
    APP_PORT=8080 \
    DATABASE_URL=sqlite:////data/db.sqlite

EXPOSE 8080

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${APP_PORT}"]
