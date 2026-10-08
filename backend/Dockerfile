FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# postgresql-client-16 (no el "postgresql-client" genérico de Debian, que
# en esta base trae la v15): pg_dump contra un servidor MÁS NUEVO que el
# cliente no tiene soporte garantizado, y el servicio "postgres" del
# docker-compose es 16. Se instala desde el repositorio oficial de
# PostgreSQL (PGDG) para tener el cliente exacto — ver app/workers/maintenance.py.
# El codename NO se hardcodea ("bookworm", etc.): python:3.12-slim cambió
# de base (Debian trixie) sin avisar y un codename fijo aquí mezcla
# paquetes de dos releases distintas — exactamente el lío de dependencias
# que rompió el build la primera vez. Se detecta el real con os-release.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates gnupg \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
    && . /etc/os-release \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update && apt-get install -y --no-install-recommends postgresql-client-16 \
    && apt-get purge -y curl gnupg && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Clave pública con la que una instalación local verifica su licencia
# (docs/plan-fase-k.md). La pone el workflow que publica las imágenes; en
# un build normal queda vacía y no se usa (MODO_INSTALACION=nube).
ARG LICENCIA_CLAVE_PUBLICA=""
ARG NSPBX_VERSION="dev"
ENV LICENCIA_CLAVE_PUBLICA=${LICENCIA_CLAVE_PUBLICA} \
    NSPBX_VERSION=${NSPBX_VERSION}

# Usuario sin privilegios para el voicebot (ver entrypoint.sh). Sin shell
# ni home: no hace falta para correr Python.
RUN groupadd --system --gid 10001 nspbx \
    && useradd --system --uid 10001 --gid nspbx --no-create-home --shell /usr/sbin/nologin nspbx
COPY entrypoint.sh /entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
