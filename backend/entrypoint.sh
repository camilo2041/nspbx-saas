#!/bin/sh
# Arranque de los contenedores backend y voicebot (misma imagen).
#
# Con NSPBX_CORRER_COMO=uid:gid el proceso NO corre como root: se arranca
# como root solo para adueñarse de las carpetas montadas en las que escribe
# (NSPBX_CARPETAS_PROPIAS, separadas por espacio) y enseguida baja a ese
# usuario. Así, si alguien lograra ejecutar código en el contenedor, no
# sería root ni podría escribir fuera de esas carpetas.
#
# Sin la variable sigue como root (el backend: ver docker-compose.yml por
# qué todavía lo necesita).
set -eu

if [ "$(id -u)" = "0" ] && [ -n "${NSPBX_CORRER_COMO:-}" ]; then
    for carpeta in ${NSPBX_CARPETAS_PROPIAS:-}; do
        mkdir -p "$carpeta"
        chown -R "$NSPBX_CORRER_COMO" "$carpeta"
    done
    exec setpriv --reuid="${NSPBX_CORRER_COMO%%:*}" --regid="${NSPBX_CORRER_COMO##*:}" --clear-groups -- "$@"
fi

exec "$@"
