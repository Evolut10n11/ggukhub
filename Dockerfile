FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps for faster-whisper (ctranslate2) and aiosqlite
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt requirements-speech.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-speech.txt

# Copy application
COPY app/ ./app/
COPY data/ ./data/

# Data volume for sqlite DB
RUN mkdir -p /app/var
VOLUME ["/app/var"]

EXPOSE 8000

CMD ["python", "-m", "app.run_stack"]
