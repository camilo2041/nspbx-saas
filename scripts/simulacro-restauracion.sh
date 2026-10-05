#!/usr/bin/env bash
# Simulacro de restauración: prueba que un respaldo se puede restaurar y
# mide cuánto se tarda (RTO de la base) y cuánto dato se perdería (RPO).
#
# Un respaldo que nunca se restauró no es un respaldo. Esto NO toca la base
# de producción: restaura en un Postgres descartable y lo borra al final.
#
#   bash scripts/simulacro-restauracion.sh                     # el último backups/nspbx-*.sql.gz
#   bash scripts/simulacro-restauracion.sh backups/x.sql.gz
#   BACKUP_PASSPHRASE_FILE=/ruta/clave bash scripts/simulacro-restauracion.sh paquete.tar.gz.enc
#
# Dónde restaura:
#   - Por omisión, un contenedor postgres:16-alpine sin red, que se borra solo.
#   - Con SIMULACRO_PG_URL=postgresql://usuario:clave@host:puerto, en ese
#     servidor (crea y borra una base nspbx_simulacro_<fecha>). Para un
#     servidor de pruebas, nunca el de producción.
#
# Cada corrida agrega una línea a backups/simulacros.log. Frecuencia
# recomendada: mensual (ver docs/runbooks/recuperacion-total.md).
set -euo pipefail
cd "$(dirname "$0")/.."

archivo="${1:-$(ls -1t backups/nspbx-*.sql.gz 2>/dev/null | head -n1 || true)}"
[ -n "$archivo" ] && [ -f "$archivo" ] || { echo "No hay respaldo para probar (backups/nspbx-*.sql.gz)"; exit 1; }
registro="${SIMULACRO_LOG:-backups/simulacros.log}"
mkdir -p "$(dirname "$registro")"
trabajo="$(mktemp -d)"
contenedor=""
base=""

limpiar() {
  [ -n "$contenedor" ] && docker rm -f "$contenedor" >/dev/null 2>&1 || true
  if [ -n "$base" ] && [ -n "${SIMULACRO_PG_URL:-}" ]; then
    psql "$SIMULACRO_PG_URL/postgres" -qc "DROP DATABASE IF EXISTS \"$base\" WITH (FORCE)" >/dev/null 2>&1 || true
  fi
  rm -rf "$trabajo"
}
trap limpiar EXIT

fallar() {
  echo "FALLO: $1"
  echo "$(date -Iseconds) FALLO archivo=$archivo motivo=\"$1\"" >> "$registro"
  exit 1
}

# --- 1. Obtener el volcado SQL ------------------------------------------
# El paquete off-site (.tar.gz.enc) trae adentro el .sql.gz más grabaciones.
inicio=$(date +%s)
volcado="$trabajo/volcado.sql.gz"
case "$archivo" in
  *.tar.gz.enc)
    [ -f "${BACKUP_PASSPHRASE_FILE:-}" ] || fallar "falta BACKUP_PASSPHRASE_FILE para descifrar"
    openssl enc -d -aes-256-cbc -pbkdf2 -pass "file:$BACKUP_PASSPHRASE_FILE" -in "$archivo" \
      | tar -xzf - -C "$trabajo" --wildcards 'backups/nspbx-*.sql.gz' || fallar "no se pudo descifrar o abrir el paquete"
    mv "$(ls -1 "$trabajo"/backups/nspbx-*.sql.gz | head -n1)" "$volcado"
    ;;
  *.enc)
    [ -f "${BACKUP_PASSPHRASE_FILE:-}" ] || fallar "falta BACKUP_PASSPHRASE_FILE para descifrar"
    openssl enc -d -aes-256-cbc -pbkdf2 -pass "file:$BACKUP_PASSPHRASE_FILE" -in "$archivo" -out "$volcado" \
      || fallar "no se pudo descifrar"
    ;;
  *) cp "$archivo" "$volcado" ;;
esac
# Sin pipefail: `head` corta la lectura y gunzip termina por SIGPIPE.
( set +o pipefail; gunzip -c "$volcado" 2>/dev/null | head -c 4096 ) | grep -q "PostgreSQL database dump" \
  || fallar "el archivo no es un volcado de pg_dump"

# Fecha del respaldo: la del nombre (nspbx-AAAAMMDD-HHMMSS, en UTC); si no,
# la del archivo.
sello=$(basename "$volcado")
nombre_original=$(basename "$archivo")
if [[ "$nombre_original" =~ nspbx-([0-9]{8})-([0-9]{6}) ]]; then
  f="${BASH_REMATCH[1]}"; h="${BASH_REMATCH[2]}"
  epoch_respaldo=$(date -u -d "${f:0:4}-${f:4:2}-${f:6:2} ${h:0:2}:${h:2:2}:${h:4:2}" +%s)
else
  epoch_respaldo=$(stat -c %Y "$archivo")
fi
edad_h=$(( ($(date +%s) - epoch_respaldo) / 3600 ))

# --- 2. Restaurar en un Postgres descartable ----------------------------
if [ -n "${SIMULACRO_PG_URL:-}" ]; then
  base="nspbx_simulacro_$(date +%Y%m%d%H%M%S)"
  psql "$SIMULACRO_PG_URL/postgres" -v ON_ERROR_STOP=1 -qc "CREATE DATABASE \"$base\"" || fallar "no se pudo crear la base de prueba"
  sql() { psql "$SIMULACRO_PG_URL/$base" -v ON_ERROR_STOP=1 -qAt "$@"; }
else
  command -v docker >/dev/null || fallar "sin docker: definí SIMULACRO_PG_URL"
  contenedor="nspbx-simulacro-$$"
  docker run -d --rm --name "$contenedor" --network none \
    -e POSTGRES_PASSWORD="$(openssl rand -hex 16)" -e POSTGRES_DB=nspbx postgres:16-alpine >/dev/null \
    || fallar "no se pudo levantar el contenedor de prueba"
  for _ in $(seq 1 60); do
    docker exec "$contenedor" pg_isready -U postgres -q 2>/dev/null && break
    sleep 1
  done
  sql() { docker exec -i "$contenedor" psql -U postgres -d nspbx -v ON_ERROR_STOP=1 -qAt "$@"; }
fi

gunzip -c "$volcado" | sql >/dev/null || fallar "la restauración dio error"
fin_restauracion=$(date +%s)
duracion=$((fin_restauracion - inicio))

# --- 3. Comprobar que lo restaurado sirve --------------------------------
contar() { sql -c "SELECT count(*) FROM $1" 2>/dev/null || echo "?"; }
empresas=$(contar tenants)
usuarios=$(contar users)
extensiones=$(contar extensions)
llamadas=$(contar call_logs)
politicas=$(sql -c "SELECT count(*) FROM pg_policy WHERE polname = 'p_tenant'")
ultima_llamada=$(sql -c "SELECT coalesce(to_char(max(started_at), 'YYYY-MM-DD HH24:MI'), '-') FROM call_logs" 2>/dev/null || echo "-")

[ "$empresas" != "?" ] && [ "$empresas" -ge 1 ] || fallar "la base restaurada no tiene empresas"
[ "$usuarios" != "?" ] && [ "$usuarios" -ge 1 ] || fallar "la base restaurada no tiene usuarios"
[ "$politicas" -ge 1 ] || fallar "la base restaurada no tiene las políticas de aislamiento (RLS)"

resumen="restauracion=${duracion}s edad_respaldo=${edad_h}h empresas=$empresas usuarios=$usuarios extensiones=$extensiones llamadas=$llamadas politicas_rls=$politicas ultima_llamada=\"$ultima_llamada\""
echo "$(date -Iseconds) OK archivo=$archivo $resumen" >> "$registro"

cat <<EOF
Simulacro OK
  Respaldo:            $archivo
  Edad del respaldo:   ${edad_h} h  (lo que se perdería si el servidor muriera ahora: el RPO real)
  Restaurar la base:   ${duracion} s (parte del RTO; falta levantar el resto)
  Contenido:           $empresas empresas, $usuarios usuarios, $extensiones extensiones, $llamadas llamadas
  Aislamiento (RLS):   $politicas políticas
  Última llamada:      $ultima_llamada (UTC)

Para completar el simulacro en un servidor de pruebas (ver
docs/runbooks/recuperacion-total.md): levantar el stack con esta base, que
el backend arranque, que una extensión registre y que una llamada de
prueba se complete. Anotar el tiempo total: ese es el RTO.
Registro: $registro
EOF
