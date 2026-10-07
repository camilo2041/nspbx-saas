#!/usr/bin/env bash
# Ejecuta los pedidos de desbloqueo de IP que se hacen en Plataforma
# (backend/app/services/desbloqueos.py). Corre en el HOST, como root, por
# cron cada minuto:
#
#   * * * * *  cd /ruta/nspbx-saas && bash scripts/fail2ban-desbloquear.sh >> /var/log/nspbx-desbloqueos.log 2>&1
#
# Lo único que hace con fail2ban es `set <jail> unbanip <ip>`. Todo lo que
# llega del backend se vuelve a validar aquí: un backend comprometido solo
# puede pedir desbloquear, nunca bloquear, recargar ni configurar.
set -euo pipefail

cd "$(dirname "$0")/.."
command -v fail2ban-client >/dev/null || exit 0

backend() { docker compose exec -T backend python -m app.desbloqueos "$@" </dev/null; }

pendientes=$(backend pendientes) || exit 0
[ -n "$pendientes" ] || exit 0

while read -r id jail ip extra; do
  [[ "$id" =~ ^[0-9]{1,10}$ ]] || continue
  if [ -n "${extra:-}" ] || ! [[ "$jail" =~ ^[A-Za-z0-9_.-]{1,64}$ ]] || ! [[ "$ip" =~ ^[0-9A-Fa-f:.]{2,45}$ ]]; then
    backend resultado "$id" error "pedido mal formado" || true
    continue
  fi
  if ! fail2ban-client status "$jail" >/dev/null 2>&1; then
    backend resultado "$id" error "no existe el jail $jail" || true
    continue
  fi
  if salida=$(fail2ban-client set "$jail" unbanip "$ip" 2>&1); then
    # fail2ban devuelve 0 (nada que quitar) si ya no estaba bloqueada.
    if [ "$(echo "$salida" | tr -d '[:space:]')" = "0" ]; then estado=no_estaba; else estado=hecho; fi
    echo "$(date -Is) $estado $jail $ip"
    backend resultado "$id" "$estado" || true
  else
    echo "$(date -Is) error $jail $ip: $salida"
    backend resultado "$id" error "$(echo "$salida" | head -c 200)" || true
  fi
done <<< "$pendientes"
