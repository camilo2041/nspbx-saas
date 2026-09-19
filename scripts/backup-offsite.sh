#!/usr/bin/env bash
# Copia externa CIFRADA: último volcado de Postgres + grabaciones + audios de bots.
# El respaldo diario del backend vive en el mismo disco que la base; si el
# servidor se pierde, se pierde todo. Esto lo saca de ahí.
#
# Configuración (variables de entorno o un archivo /etc/nspbx-backup.env):
#   BACKUP_PASSPHRASE_FILE  archivo con la clave de cifrado (chmod 600). GUÁRDALA
#                           también FUERA del servidor: sin ella no se restaura.
#   BACKUP_REMOTE           destino de rclone (ej. "b2:mi-bucket/nspbx") o de
#                           scp/rsync ("usuario@host:/ruta"). Vacío = solo local.
#   BACKUP_REMOTE_TOOL      rclone (por defecto) | rsync
#   BACKUP_OUT              carpeta local temporal (por defecto ./backups/offsite)
#   BACKUP_KEEP             cuántas copias locales conservar (por defecto 3)
#
# Cron (diario, 03:30):  30 3 * * *  cd /ruta/nspbx-saas && bash scripts/backup-offsite.sh >> /var/log/nspbx-offsite.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f /etc/nspbx-backup.env ] && . /etc/nspbx-backup.env

: "${BACKUP_PASSPHRASE_FILE:?Falta BACKUP_PASSPHRASE_FILE (crea la clave: openssl rand -base64 48 > archivo; chmod 600 archivo)}"
[ -f "$BACKUP_PASSPHRASE_FILE" ] || { echo "No existe $BACKUP_PASSPHRASE_FILE"; exit 1; }
salida="${BACKUP_OUT:-backups/offsite}"; mkdir -p "$salida"
conservar="${BACKUP_KEEP:-3}"

volcado=$(ls -1t backups/nspbx-*.sql.gz 2>/dev/null | head -n1 || true)
[ -n "$volcado" ] || { echo "No hay volcados en backups/"; exit 1; }
# Un volcado viejo es una copia falsa de tranquilidad: no se sube si tiene más de 26 h.
if [ -n "$(find "$volcado" -mmin +1560)" ]; then
  echo "El último volcado ($volcado) tiene más de 26 h: el respaldo diario está fallando"; exit 1
fi

sello=$(date +%Y%m%d-%H%M%S)
paquete="$salida/nspbx-$sello.tar.gz.enc"
# Sin sombras: si algo falla a medias, el archivo parcial se borra.
trap 'rm -f "$paquete.parcial"' EXIT
tar -czf - "$volcado" freeswitch/recordings $( [ -d freeswitch/sounds/bots ] && echo freeswitch/sounds/bots ) 2>/dev/null \
  | openssl enc -aes-256-cbc -pbkdf2 -salt -pass "file:$BACKUP_PASSPHRASE_FILE" -out "$paquete.parcial"
mv "$paquete.parcial" "$paquete"
sha256sum "$paquete" > "$paquete.sha256"
echo "Paquete cifrado: $paquete ($(du -h "$paquete" | cut -f1))"

if [ -n "${BACKUP_REMOTE:-}" ]; then
  case "${BACKUP_REMOTE_TOOL:-rclone}" in
    rclone) rclone copy "$paquete" "$BACKUP_REMOTE" && rclone copy "$paquete.sha256" "$BACKUP_REMOTE" ;;
    rsync)  rsync -a "$paquete" "$paquete.sha256" "$BACKUP_REMOTE/" ;;
    *) echo "BACKUP_REMOTE_TOOL desconocido"; exit 1 ;;
  esac
  echo "Copiado a $BACKUP_REMOTE"
else
  echo "AVISO: BACKUP_REMOTE vacío; la copia quedó solo en este servidor."
fi

# Rotación local (la retención remota la define el proveedor).
ls -1t "$salida"/nspbx-*.tar.gz.enc 2>/dev/null | tail -n +$((conservar + 1)) | while read -r f; do rm -f "$f" "$f.sha256"; done
