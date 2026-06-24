FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps for faster-whisper (ctranslate2) and aiosqlite
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libgomp1 \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Trust the Минцифры "Russian Trusted" CA chain required by platform-api2.max.ru.
# httpx verifies via certifi and ignores the OS store unless SSL_CERT_FILE is set,
# so we add the RSA certs to the system bundle and point SSL_CERT_FILE at the merged file.
# (GOST variants are omitted — stock OpenSSL/Python cannot validate them.)
COPY certs/russian_trusted_root_ca_pem.crt \
     certs/russian_trusted_sub_ca_pem.crt \
     certs/russian_trusted_sub_ca_2024_pem.crt \
     /usr/local/share/ca-certificates/
RUN update-ca-certificates
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    SSL_CERT_DIR=/etc/ssl/certs

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
