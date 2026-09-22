#!/usr/bin/env bash
# Copia al wss.pem de FreeSWITCH el certificado que Traefik ya renueva solo.
#
# El softphone del navegador NO entra por Traefik (ver el comentario del
# puerto 8443 en docker-compose.yml): abre el WebSocket directo contra
# FreeSWITCH, así que el certificado lo presenta FreeSWITCH y no el proxy.
# Pero quien lo emite y lo renueva sigue siendo Traefik, en su acme.json.
#
# Sin este guion el certificado se copia UNA vez a mano y queda congelado:
# Traefik renueva a los ~60 días, FreeSWITCH sigue sirviendo el vencido, y
# el softphone deja de conectar con error de certificado sin ningún aviso
# previo. El registro por SIP común y las troncales siguen andando, así que
# el síntoma aparece solo en el navegador y desconcierta.
#
# Configuración (variables de entorno):
#   WSS_DOMAIN   nombre para el que el navegador abre el wss. Obligatorio.
#                Tiene que coincidir con el host de sip_ws_url en Ajustes.
#   ACME_JSON    almacén de Traefik (por defecto /root/traefik/acme.json)
#
# Cron (diario, 04:15):
#   15 4 * * *  WSS_DOMAIN=sip.ejemplo.com bash /ruta/nspbx-saas/scripts/renovar-cert-wss.sh >> /var/log/nspbx-cert-wss.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/.."

: "${WSS_DOMAIN:?Falta WSS_DOMAIN (el nombre con el que el navegador abre el wss, ej. sip.ejemplo.com)}"
ACME_JSON="${ACME_JSON:-/root/traefik/acme.json}"
DESTINO="freeswitch/certs/wss.pem"

[ -r "$ACME_JSON" ] || { echo "No puedo leer $ACME_JSON (¿se corre como root?)"; exit 1; }

NUEVO="$(mktemp)"
trap 'rm -f "$NUEVO"' EXIT

# El orden es clave privada + cadena: es lo que espera mod_sofia en un
# archivo "combinado".
ACME_JSON="$ACME_JSON" WSS_DOMAIN="$WSS_DOMAIN" python3 - "$NUEVO" <<'PY'
import base64, json, os, sys

almacen = json.load(open(os.environ["ACME_JSON"]))
dominio = os.environ["WSS_DOMAIN"]
for resolver in almacen.values():
    for cert in resolver.get("Certificates") or []:
        if cert["domain"]["main"] == dominio:
            pem = base64.b64decode(cert["key"]).decode() + base64.b64decode(cert["certificate"]).decode()
            open(sys.argv[1], "w").write(pem)
            sys.exit(0)
sys.exit(f"Traefik no tiene certificado para {dominio}. Hace falta un router con ese Host para que ACME lo emita.")
PY

if [ -f "$DESTINO" ] && cmp -s "$NUEVO" "$DESTINO"; then
  echo "$(date -Is) sin cambios para $WSS_DOMAIN"
  exit 0
fi

cp "$NUEVO" "$DESTINO"
chmod 600 "$DESTINO"
echo "$(date -Is) wss.pem actualizado: $(openssl x509 -in "$DESTINO" -noout -enddate)"

# Reiniciar el perfil y no el contenedor: mod_sofia lee wss.pem solo al
# arrancar el perfil. Los softphones se reconectan solos en segundos.
docker exec nspbx_freeswitch sh -c '
  for ip in $(hostname -i); do
    fs_cli -H "$ip" -P 8021 -p "$FS_ESL_PASSWORD" -x "sofia profile internal restart" 2>/dev/null && exit 0
  done
  exit 1
' && echo "$(date -Is) perfil internal reiniciado"
