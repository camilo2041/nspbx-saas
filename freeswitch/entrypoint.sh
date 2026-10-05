#!/bin/sh
# Arranque de FreeSWITCH.
#
# FreeSWITCH no corre como root: arranca como root y él mismo baja al
# usuario `freeswitch` (uid 10001, -u/-g en el CMD del Dockerfile) antes de
# cargar módulos y abrir puertos. Es el mismo uid que el backend, que borra
# las grabaciones que FreeSWITCH crea (retención, supresión de datos) y
# escribe la configuración que FreeSWITCH lee.
#
# Acá, todavía como root, se adueña de las carpetas MONTADAS en las que
# escribe: grabaciones, su certificado wss y conf/tls (sus claves TLS
# autogeneradas). En una instalación existente las dejó root. Las que viven
# dentro de la imagen (db, log, run) ya vienen con el dueño correcto.
set -eu

USUARIO="10001:10001"

# Solo cambia lo que no es ya del usuario: la primera vez recorre todo;
# después, casi nada. -h: un enlace simbólico se cambia a sí mismo.
aduenar() {
    find "$1" \( ! -user "${USUARIO%%:*}" -o ! -group "${USUARIO##*:}" \) -exec chown -h "$USUARIO" {} +
}

for carpeta in /var/lib/freeswitch/recordings /usr/local/freeswitch/certs /etc/freeswitch; do
    mkdir -p "$carpeta"
    aduenar "$carpeta"
done

exec "$@"
