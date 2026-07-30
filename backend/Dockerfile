# Imagen única para desarrollo y producción: cambia el comando, no la imagen.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=America/Argentina/Buenos_Aires

# Dependencias del sistema:
#   - libpq5 y build tools → psycopg2
#   - postgresql-client → psql, que el entrypoint usa para aplicar el seed
#   - libpango/libcairo/... → WeasyPrint (generación de PDF)
#   - tzdata → zona horaria UTC-03:00
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        postgresql-client \
        tzdata \
        curl \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libcairo2 \
        libgdk-pixbuf-2.0-0 \
        libffi-dev \
        shared-mime-info \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Se copia primero requirements.txt para aprovechar la cache de capas:
# cambiar código no reinstala dependencias.
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

RUN chmod +x entrypoint.sh

EXPOSE 8000

# El entrypoint aplica migraciones y seed, y escucha en ${PORT}. En
# desarrollo docker-compose sobreescribe el comando con --reload y esto no
# se ejecuta.
CMD ["./entrypoint.sh"]
