#!/usr/bin/env bash
# Instala (o actualiza) la defensa de fail2ban de la central en el servidor.
# Se puede correr las veces que haga falta. Desde la raíz del repositorio:
#
#   sudo bash deploy/fail2ban/instalar.sh
#
# 1. Filtros y jails de deploy/fail2ban/ en /etc/fail2ban/.
# 2. El vigía que recarga los jails cuando se recrea el contenedor de
#    FreeSWITCH (vigia/; sin él, tras una actualización fail2ban deja de
#    bloquear hasta que alguien lo reinicie).
# 3. Permiso de lectura de la base de fail2ban para el backend (uid 10001),
#    que la muestra en la pantalla Seguridad del panel.
#
# Si /etc/fail2ban/jail.d/nspbx-*.local ya existe y tiene cambios propios
# (por ejemplo la IP de la oficina en ignoreip), NO se pisa: se deja la
# versión nueva al lado como .nuevo para compararla.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Correlo con sudo." >&2
  exit 1
fi
cd "$(dirname "$0")"

if ! command -v fail2ban-client >/dev/null; then
  apt-get install -y fail2ban acl
fi
command -v setfacl >/dev/null || apt-get install -y acl

install -m 644 filter.d/nspbx-*.conf /etc/fail2ban/filter.d/
for jail in jail.d/nspbx-*.local; do
  destino="/etc/fail2ban/jail.d/$(basename "$jail")"
  if [ -f "$destino" ] && ! cmp -s "$jail" "$destino"; then
    install -m 644 "$jail" "${destino}.nuevo"
    echo "  $destino tiene cambios propios: se dejó la versión nueva en ${destino}.nuevo"
  else
    install -m 644 "$jail" "$destino"
  fi
done

install -m 755 vigia/nspbx-fail2ban-vigia.sh /usr/local/sbin/nspbx-fail2ban-vigia.sh
install -m 644 vigia/nspbx-fail2ban-vigia.service /etc/systemd/system/nspbx-fail2ban-vigia.service
systemctl daemon-reload
systemctl enable --now fail2ban
systemctl restart fail2ban
systemctl enable nspbx-fail2ban-vigia.service
systemctl restart nspbx-fail2ban-vigia.service

# fail2ban crea su base al arrancar.
for _ in $(seq 1 15); do
  [ -f /var/lib/fail2ban/fail2ban.sqlite3 ] && break
  sleep 1
done
if [ -f /var/lib/fail2ban/fail2ban.sqlite3 ]; then
  setfacl -m u:10001:r /var/lib/fail2ban/fail2ban.sqlite3
else
  echo "AVISO: no apareció /var/lib/fail2ban/fail2ban.sqlite3; la pantalla Seguridad no podrá leerla." >&2
fi

sleep 3
fail2ban-client status
systemctl --no-pager --lines=5 status nspbx-fail2ban-vigia.service || true
echo
echo "Listo. Si el backend ya estaba corriendo antes de que existiera la base de fail2ban,"
echo "recrealo para que la monte: docker compose up -d --force-recreate backend"
