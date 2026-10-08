#!/usr/bin/env bash
#
# Arma instalador/paquete.tar.gz: lo que necesita un servidor de cliente
# además de las imágenes (docs/plan-fase-k.md). Sin código fuente.
#
#   bash instalador/armar-paquete.sh 1.2.0
#
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION="${1:?Uso: armar-paquete.sh <versión>}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
D="$TMP/nspbx"
mkdir -p "$D/scripts" "$D/freeswitch" "$D/deploy"

cp docker-compose.yml instalador/docker-compose.instalacion.yml .env.example "$D/"
cp -r freeswitch/conf "$D/freeswitch/conf"
# Nada con secretos ni archivos generados de este equipo.
rm -f "$D"/freeswitch/conf/vars.xml \
      "$D"/freeswitch/conf/autoload_configs/{event_socket,xml_curl,json_cdr}.conf.xml \
      "$D"/freeswitch/conf/sip_profiles/external/gw_*.xml
rm -rf "$D/freeswitch/conf/tls"
mkdir -p "$D/freeswitch/sounds" "$D/freeswitch/recordings"
cp scripts/setup.sh scripts/sonidos.sh scripts/verificar.sh scripts/restore.sh \
   scripts/backup-offsite.sh scripts/fail2ban-desbloquear.sh scripts/medir-recursos.sh "$D/scripts/"
cp -r deploy/fail2ban "$D/deploy/"
cp instalador/nspbx "$D/nspbx"
chmod +x "$D/nspbx" "$D"/scripts/*.sh
echo "$VERSION" > "$D/VERSION"

tar -C "$TMP" -czf instalador/paquete.tar.gz nspbx
echo "instalador/paquete.tar.gz ($(du -h instalador/paquete.tar.gz | cut -f1)) para la versión $VERSION"
