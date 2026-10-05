#!/bin/sh
# Arranque de los contenedores backend y voicebot (misma imagen).
#
# Con NSPBX_CORRER_COMO=uid:gid el proceso NO corre como root: se arranca
# como root solo para adueñarse de las carpetas montadas en las que escribe
# (NSPBX_CARPETAS_PROPIAS, separadas por espacio) y enseguida baja a ese
# usuario. Así, si alguien lograra ejecutar código en el contenedor, no
# sería root ni podría escribir fuera de esas carpetas.
#
# Usuarios (ver docker-compose.yml):
#   10001  backend y FreeSWITCH: comparten grabaciones y configuración.
#   10002  voicebot: solo sus carpetas de audio.
set -eu

# Solo cambia lo que no es ya del usuario: en una instalación existente la
# primera vez recorre todo (archivos que dejó root); después, casi nada.
# -h: un enlace simbólico se cambia a sí mismo, nunca a lo que apunta.
aduenar() {
    find "$1" \( ! -user "${2%%:*}" -o ! -group "${2##*:}" \) -exec chown -h "$2" {} +
}

if [ "$(id -u)" = "0" ] && [ -n "${NSPBX_CORRER_COMO:-}" ]; then
    for carpeta in ${NSPBX_CARPETAS_PROPIAS:-}; do
        mkdir -p "$carpeta"
        aduenar "$carpeta" "$NSPBX_CORRER_COMO"
    done
    # Archivos montados de solo lectura (no se les puede cambiar el dueño
    # desde acá). Uno de root en 600 —lo normal para una clave— ya no se
    # puede leer: el push a la app móvil (secrets/) dejaría de andar con solo
    # un error en el log al enviar, y la pantalla de Seguridad diría que no
    # hay fail2ban. Se avisa al arrancar, con el arreglo.
    usuario="${NSPBX_CORRER_COMO%%:*}"
    for montado in /run/secrets/* /var/lib/fail2ban/fail2ban.sqlite3; do
        [ -f "$montado" ] || continue
        if ! setpriv --reuid="$usuario" --regid="${NSPBX_CORRER_COMO##*:}" --clear-groups -- test -r "$montado"; then
            echo "AVISO: el backend (uid $usuario) no puede leer $montado." >&2
            case "$montado" in
                /run/secrets/*) echo "       En el servidor: sudo chown ${NSPBX_CORRER_COMO} secrets/$(basename "$montado") && sudo chmod 600 secrets/$(basename "$montado")" >&2 ;;
                *) echo "       En el servidor: sudo setfacl -m u:${usuario}:r $montado" >&2 ;;
            esac
        fi
    done
    # HOME seguía apuntando a /root, que el usuario no puede ni mirar: asyncpg
    # busca ~/.postgresql/postgresql.key al conectar y el arranque fallaba
    # con "Permission denied". /tmp es suyo (tmpfs) y no guarda nada.
    export HOME=/tmp
    exec setpriv --reuid="${NSPBX_CORRER_COMO%%:*}" --regid="${NSPBX_CORRER_COMO##*:}" --clear-groups -- "$@"
fi

exec "$@"
