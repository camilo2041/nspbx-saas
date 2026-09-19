#!/usr/bin/env bash
# Restaura un respaldo de Postgres (backups/nspbx-*.sql.gz) en la base del stack.
#
#   bash scripts/restore.sh backups/nspbx-20260901-183245.sql.gz
#   bash scripts/restore.sh backups/nspbx-....sql.gz.enc     # cifrado por backup-offsite.sh
#
# Para un .enc exporta antes BACKUP_PASSPHRASE_FILE=/ruta/a/la/clave.
# DESTRUYE la base actual: pide escribir "RESTAURAR" para continuar.
set -euo pipefail
cd "$(dirname "$0")/.."

archivo="${1:-}"
[ -f "$archivo" ] || { echo "Uso: $0 <respaldo.sql.gz[.enc]>"; exit 1; }
set -a; [ -f .env ] && . ./.env; set +a
usuario="${POSTGRES_USER:-nspbx}"; base="${POSTGRES_DB:-nspbx}"

leer() {
  case "$archivo" in
    *.enc)
      [ -f "${BACKUP_PASSPHRASE_FILE:-}" ] || { echo "Falta BACKUP_PASSPHRASE_FILE" >&2; exit 1; }
      openssl enc -d -aes-256-cbc -pbkdf2 -pass "file:$BACKUP_PASSPHRASE_FILE" -in "$archivo" | gunzip ;;
    *) gunzip -c "$archivo" ;;
  esac
}

# Antes de tocar nada: el archivo tiene que descomprimirse y verse como un volcado.
leer | head -c 4096 | grep -q "PostgreSQL database dump" || { echo "El archivo no parece un volcado de pg_dump"; exit 1; }

echo "Se BORRARÁ la base '$base' y se restaurará desde $archivo"
read -r -p 'Escribe RESTAURAR para continuar: ' ok
[ "$ok" = "RESTAURAR" ] || { echo "Cancelado"; exit 1; }

docker compose stop backend voicebot
docker compose exec -T postgres psql -U "$usuario" -d postgres -v ON_ERROR_STOP=1 \
  -c "DROP DATABASE IF EXISTS \"$base\" WITH (FORCE)" -c "CREATE DATABASE \"$base\" OWNER \"$usuario\""
leer | docker compose exec -T postgres psql -U "$usuario" -d "$base" -v ON_ERROR_STOP=1 -q
# El backend recrea el rol nspbx_app, sus permisos y el aislamiento por empresa al arrancar.
docker compose up -d backend voicebot
echo "Restauración lista. Revisa: docker compose logs -f backend"
