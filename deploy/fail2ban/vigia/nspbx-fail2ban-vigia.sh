#!/usr/bin/env bash
# Mantiene a fail2ban mirando el log ACTUAL de FreeSWITCH.
#
# Los jails de deploy/fail2ban/jail.d leen el log JSON que Docker guarda de
# cada contenedor (/var/lib/docker/containers/<id>/<id>-json.log). fail2ban
# expande ese comodín SOLO al cargar el jail: cuando el contenedor de
# FreeSWITCH se recrea (docker compose up --build, una actualización) tiene
# otro id y otro log, y fail2ban sigue mirando el viejo. Desde ahí no
# bloquea nada, sin avisar, hasta que alguien lo reinicie.
#
# Este vigía escucha los eventos de Docker y, cada vez que arranca el
# contenedor de FreeSWITCH, recarga los dos jails para que tomen el log
# nuevo. Las IPs ya bloqueadas siguen bloqueadas (recargar no las suelta).
# Lo corre systemd (nspbx-fail2ban-vigia.service); se instala con
# deploy/fail2ban/instalar.sh.
set -u

CONTENEDOR="${NSPBX_CONTENEDOR_FS:-nspbx_freeswitch}"
JAILS="${NSPBX_JAILS:-nspbx-freeswitch nspbx-sip-scan}"

recargar() {
  # Docker crea el archivo de log al arrancar el contenedor: se le da un
  # momento para que exista antes de expandir el comodín.
  sleep 3
  local jail fallo=0
  for jail in $JAILS; do
    if ! fail2ban-client reload "$jail" >/dev/null 2>&1; then
      fallo=1
    fi
  done
  if [ "$fallo" -eq 1 ]; then
    # Un jail que no recarga (fail2ban recién reiniciado, config cambiada):
    # reiniciar el servicio entero también vuelve a leer los logs.
    echo "No se pudo recargar algún jail; se reinicia fail2ban."
    systemctl restart fail2ban || echo "ERROR: tampoco se pudo reiniciar fail2ban." >&2
  else
    echo "Jails recargados con el log nuevo de ${CONTENEDOR}: ${JAILS}"
  fi
}

# Al arrancar el vigía: el contenedor pudo recrearse mientras estaba caído.
recargar

# Un evento por línea mientras Docker esté vivo; si Docker se reinicia, el
# comando termina y systemd vuelve a lanzar el vigía (Restart=always).
docker events --filter "type=container" --filter "event=start" --filter "container=${CONTENEDOR}" --format '{{.Actor.Attributes.name}}' |
  while read -r nombre; do
    echo "Arrancó ${nombre}: se recargan los jails."
    recargar
  done
