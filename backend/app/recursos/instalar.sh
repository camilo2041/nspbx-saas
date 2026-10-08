#!/usr/bin/env bash
#
# Instalador de NSPBX en el servidor de un cliente (docs/plan-fase-k.md).
#
#   curl -fsSL https://<central>/api/licencia/instalar.sh | sudo bash
#
# Un asistente en pantalla: revisa el equipo, pide el código de activación,
# pregunta cómo se va a entrar (dominio o red local), muestra un resumen e
# instala todo con una barra de progreso. Al final deja la dirección, el
# usuario y la contraseña del administrador.
#
# Se puede volver a correr: lo que ya quedó hecho (activación, secretos) se
# reutiliza, así que un corte a mitad de camino se retoma sin código nuevo.
#
# Variables opcionales: NSPBX_CENTRAL (la central), NSPBX_DIR (/opt/nspbx).

# Todo va dentro de main(): con `curl | bash`, bash lee el script por la
# entrada estándar; así lo lee COMPLETO antes de que main() pase la
# entrada a la terminal para el asistente.
main() {
set -uo pipefail

# La central lo reemplaza por su propia dirección al servir este archivo.
CENTRAL="${NSPBX_CENTRAL:-__CENTRAL__}"
DIR="${NSPBX_DIR:-/opt/nspbx}"
LOG="/var/log/nspbx-instalador.log"
TITULO="Instalador de NSPBX"
ESTADO="$DIR/.instalador"
export NEWT_COLORS='
root=white,blue
window=black,lightgray
border=blue,lightgray
title=blue,lightgray
button=white,blue
actbutton=white,red
compactbutton=black,lightgray
entry=black,white
checkbox=black,lightgray
actcheckbox=white,blue
listbox=black,lightgray
actlistbox=white,blue
textbox=black,lightgray
acttextbox=white,blue
helpline=white,blue
roottext=white,blue
'

# --- Utilidades -------------------------------------------------------------------------

registrar() { printf '[%s] %s\n' "$(date '+%F %T')" "$*" >> "$LOG"; }

morir() {
  registrar "ERROR: $1"
  whiptail --title "$TITULO" --msgbox "No se pudo completar la instalación:\n\n$1\n\nEl detalle quedó en $LOG.\nCorrige el problema y vuelve a correr el instalador: retoma desde donde quedó." 18 72 2>/dev/null \
    || printf '\n\033[31mNo se pudo completar la instalación:\033[0m %s\nDetalle en %s\n' "$1" "$LOG"
  exit 1
}

guardar() { mkdir -p "$ESTADO"; printf '%s' "$2" > "$ESTADO/$1"; chmod 600 "$ESTADO/$1"; }
leido()   { cat "$ESTADO/$1" 2>/dev/null; }

json() { python3 -c "import json,sys; d=json.load(sys.stdin); print($1)" 2>/dev/null; }

# --- 0. Lo mínimo para mostrar el asistente --------------------------------------------

[ "$(id -u)" -eq 0 ] || { echo "Corre el instalador como administrador: curl -fsSL $CENTRAL/api/licencia/instalar.sh | sudo bash"; exit 1; }
exec < /dev/tty
mkdir -p "$(dirname "$LOG")"; : >> "$LOG"; chmod 600 "$LOG"
registrar "Instalador iniciado (central $CENTRAL, destino $DIR)"

. /etc/os-release 2>/dev/null || true
case "${ID:-}:${VERSION_ID:-}" in
  ubuntu:22.04|ubuntu:24.04|debian:12) ;;
  *) echo "Sistema no soportado (${PRETTY_NAME:-desconocido}). Usa Ubuntu 22.04/24.04 o Debian 12."; exit 1 ;;
esac
if ! command -v whiptail >/dev/null || ! command -v curl >/dev/null || ! command -v python3 >/dev/null || ! command -v openssl >/dev/null; then
  echo "Preparando el instalador…"
  apt-get update -qq >> "$LOG" 2>&1 && apt-get install -y -qq whiptail curl python3 openssl ca-certificates dnsutils >> "$LOG" 2>&1 \
    || { echo "No se pudieron instalar las herramientas básicas (revisa $LOG)."; exit 1; }
fi

# --- 1. Bienvenida -----------------------------------------------------------------------

whiptail --title "$TITULO" --yes-button "Empezar" --no-button "Salir" --yesno "\
            _   _  ____  ____   ____ __  __
           | \\ | |/ ___||  _ \\ | __ )\\ \\/ /
           |  \\| |\\___ \\| |_) ||  _ \\ \\  /
           | |\\  | ___) |  __/ | |_) |/  \\
           |_| \\_||____/|_|    |____//_/\\_\\

        Central telefónica con voizbot y contact center

Este asistente instala NSPBX en este servidor. Tarda entre 10 y 20
minutos, casi todo descargando.

Vas a necesitar:
  • El código de activación que te dio tu proveedor (NSPBX-XXXX-…).
  • Un dominio apuntando a este servidor (recomendado) o usarlo
    solo dentro de tu red.

Tus datos (llamadas, grabaciones, contactos) se quedan en este
servidor. Solo se informa a la central un resumen de uso." 26 74 || exit 0

# --- 2. Revisión del equipo --------------------------------------------------------------

NUCLEOS=$(nproc)
RAM_GB=$(( $(awk '/MemTotal/ {print $2}' /proc/meminfo) / 1024 / 1024 ))
mkdir -p "$DIR"
DISCO_GB=$(( $(df -Pk "$DIR" | awk 'NR==2 {print $4}') / 1024 / 1024 ))
ARQ=$(uname -m)
FATAL=0; INFORME=""
linea() { INFORME+="  $1  $2\n"; }
if [ "$ARQ" = "x86_64" ]; then linea "✓" "Procesador de 64 bits ($ARQ)"; else linea "✗" "Procesador $ARQ: se necesita x86_64"; FATAL=1; fi
if [ "$NUCLEOS" -ge 4 ]; then linea "✓" "$NUCLEOS núcleos"; elif [ "$NUCLEOS" -ge 2 ]; then linea "!" "$NUCLEOS núcleos (alcanza para pocas llamadas; se recomiendan 4)"; else linea "✗" "$NUCLEOS núcleo: se necesitan al menos 2"; FATAL=1; fi
if [ "$RAM_GB" -ge 8 ]; then linea "✓" "${RAM_GB} GB de memoria"; elif [ "$RAM_GB" -ge 4 ]; then linea "!" "${RAM_GB} GB de memoria (se recomiendan 8)"; else linea "✗" "${RAM_GB} GB de memoria: se necesitan al menos 4"; FATAL=1; fi
if [ "$DISCO_GB" -ge 80 ]; then linea "✓" "${DISCO_GB} GB libres"; elif [ "$DISCO_GB" -ge 40 ]; then linea "!" "${DISCO_GB} GB libres (las grabaciones ocupan; se recomiendan 80)"; else linea "✗" "${DISCO_GB} GB libres: se necesitan al menos 40"; FATAL=1; fi
OCUPADOS=""
for p in 80 443 5060 5080; do
  if ss -ltnH "sport = :$p" 2>/dev/null | grep -q . ; then
    docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^nspbx_' || OCUPADOS+=" $p"
  fi
done
if [ -z "$OCUPADOS" ]; then linea "✓" "Puertos 80, 443, 5060 y 5080 libres"; else linea "✗" "Puertos ocupados por otro programa:$OCUPADOS"; FATAL=1; fi
if curl -fsS --max-time 10 "$CENTRAL/api/licencia/instalar.sh" -o /dev/null 2>>"$LOG"; then
  linea "✓" "Conexión con la central ($CENTRAL)"
else
  linea "✗" "Sin conexión con la central ($CENTRAL)"; FATAL=1
fi
registrar "Revisión: $(printf '%b' "$INFORME" | tr '\n' ';')"
if [ "$FATAL" -eq 1 ]; then
  whiptail --title "$TITULO · Revisión del equipo" --msgbox "Este servidor no cumple lo necesario:\n\n$INFORME\nCorrige lo marcado con ✗ y vuelve a correr el instalador." 20 76
  exit 1
fi
whiptail --title "$TITULO · Revisión del equipo" --yes-button "Continuar" --no-button "Salir" --yesno "Todo listo para instalar:\n\n$INFORME\n(! = funciona, pero conviene mejorarlo)" 20 76 || exit 0

# --- 3. Activación -----------------------------------------------------------------------

ACTIVACION="$ESTADO/activacion.json"
if [ ! -s "$ACTIVACION" ]; then
  MENSAJE="Escribe el código de activación que te dio tu proveedor.\n\nTiene esta forma:  NSPBX-XXXX-XXXX-XXXX"
  while true; do
    CODIGO=$(whiptail --title "$TITULO · Activación" --inputbox "$MENSAJE" 13 66 3>&1 1>&2 2>&3) || exit 0
    CODIGO=$(printf '%s' "$CODIGO" | tr -d '[:space:]')
    [ -n "$CODIGO" ] || continue
    RESP=$(curl -sS --max-time 30 -H 'Content-Type: application/json' -w '\n%{http_code}' \
      -d "{\"codigo\": \"$CODIGO\", \"version\": \"instalador\"}" "$CENTRAL/api/licencia/activar" 2>>"$LOG")
    COD=$(printf '%s' "$RESP" | tail -1); CUERPO=$(printf '%s' "$RESP" | sed '$d')
    if [ "$COD" = "200" ]; then
      mkdir -p "$ESTADO"; printf '%s' "$CUERPO" > "$ACTIVACION"; chmod 600 "$ACTIVACION"
      registrar "Activación correcta"
      break
    fi
    DETALLE=$(printf '%s' "$CUERPO" | json 'd.get("detail","")')
    registrar "Activación rechazada ($COD): $DETALLE"
    MENSAJE="${DETALLE:-No se pudo validar el código (respuesta $COD).}\n\nRevisa el código y vuelve a escribirlo:"
  done
fi
EMPRESA=$(json 'json.loads(d["documento"])["empresa"]["nombre"]' < "$ACTIVACION")
PLAN=$(json 'json.loads(d["documento"])["licencia"]["plan"]' < "$ACTIVACION")
VENCE=$(json '(json.loads(d["documento"])["licencia"].get("expires_at") or "sin vencimiento")[:10]' < "$ACTIVACION")
VERSION=$(json 'd["descarga"]["version"]' < "$ACTIVACION")
REGISTRO=$(json 'd["descarga"]["registro"]' < "$ACTIVACION")
# Dirección segura para red local (services/certificados_locales.py en la
# central). Vacía = esa central no la ofrece: red local con certificado propio.
SUBDOMINIO=$(json 'd.get("subdominio") or ""' < "$ACTIVACION")
[ -n "$VERSION" ] || morir "La central todavía no tiene una versión publicada para instalar. Avisa a tu proveedor."
whiptail --title "$TITULO · Activación" --yes-button "Es correcto" --no-button "Salir" --yesno "\
Código aceptado. Vas a instalar:\n
    Empresa:   $EMPRESA
    Plan:      $PLAN
    Vence:     $VENCE
    Versión:   $VERSION" 15 64 || exit 0

# --- 4. Cómo se va a entrar ----------------------------------------------------------------

IP_PUB=$(curl -fsS --max-time 10 https://api.ipify.org 2>/dev/null || true)
IP_LAN=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i=1;i<NF;i++) if ($i=="src") print $(i+1)}')
ETIQUETA_LOCAL="Solo dentro de esta red, por la IP ${IP_LAN:-local}"
[ -n "$SUBDOMINIO" ] && ETIQUETA_LOCAL="Solo dentro de esta red, con dirección segura (sin dominio propio)"
MODO=$(leido modo)
if [ -z "$MODO" ]; then
  MODO=$(whiptail --title "$TITULO · Acceso" --menu "¿Cómo van a entrar al panel y los teléfonos?" 16 76 2 \
    "dominio" "Con un dominio, desde cualquier lugar (recomendado)" \
    "local"   "$ETIQUETA_LOCAL" 3>&1 1>&2 2>&3) || exit 0
fi
if [ "$MODO" = "dominio" ]; then
  HOST=$(leido host)
  while [ -z "$HOST" ]; do
    HOST=$(whiptail --title "$TITULO · Dominio" --inputbox "Dominio del panel (sin https://), por ejemplo:\n\n    pbx.miempresa.com\n\nTiene que apuntar a este servidor (registro A → ${IP_PUB:-tu IP pública})." 14 70 3>&1 1>&2 2>&3) || exit 0
    HOST=$(printf '%s' "$HOST" | sed -e 's#^https\?://##' -e 's#/.*##' -e 's#:.*##' | tr -d '[:space:]' | tr 'A-Z' 'a-z')
    if ! printf '%s' "$HOST" | grep -qE '^[a-z0-9]([a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}$'; then
      whiptail --title "$TITULO" --msgbox "«$HOST» no parece un dominio." 8 50; HOST=""; continue
    fi
    APUNTA=$(dig +short A "$HOST" 2>/dev/null | tail -1)
    if [ -n "$IP_PUB" ] && [ "$APUNTA" != "$IP_PUB" ]; then
      whiptail --title "$TITULO · Dominio" --yes-button "Seguir igual" --no-button "Cambiarlo" --yesno "\
$HOST apunta a «${APUNTA:-nada}», pero este servidor sale a internet con $IP_PUB.\n
Sin eso, el certificado no se emite y los teléfonos no lo encuentran.
Si usas Cloudflare, apaga el proxy (nube gris) para este registro." 14 72 || { HOST=""; continue; }
    fi
  done
  CORREO=$(leido correo)
  [ -n "$CORREO" ] || CORREO=$(whiptail --title "$TITULO · Certificado" --inputbox "Correo para el certificado de seguridad (Let's Encrypt avisa ahí si hay problemas al renovarlo):" 11 70 3>&1 1>&2 2>&3) || exit 0
else
  CORREO=""
  [ -n "$IP_LAN" ] || morir "No pude detectar la IP de este servidor en la red local."
  case "$IP_LAN" in
    10.*|192.168.*|172.1[6-9].*|172.2[0-9].*|172.3[01].*) ;;
    *) SUBDOMINIO="" ;;  # la central solo publica IP privadas
  esac
  HOST="${SUBDOMINIO:-$IP_LAN}"
fi
guardar modo "$MODO"; guardar host "$HOST"; guardar correo "$CORREO"

# --- 5. Resumen --------------------------------------------------------------------------

if [ "$MODO" = "dominio" ]; then ACCESO="https://$HOST (certificado de Let's Encrypt)"
elif [ -n "$SUBDOMINIO" ]; then ACCESO="https://$HOST (solo en esta red, $IP_LAN)"
else ACCESO="https://$HOST (solo en esta red, certificado propio)"; fi
whiptail --title "$TITULO · Resumen" --yes-button "Instalar" --no-button "Salir" --yesno "\
Todo listo. Se va a instalar:\n
    Empresa:     $EMPRESA ($PLAN)
    Versión:     $VERSION
    Acceso:      $ACCESO
    Carpeta:     $DIR
\nSe instala Docker si falta y se abren los puertos de telefonía en el
cortafuegos (si está activo). No apagues el servidor mientras tanto." 18 76 || exit 0

# --- 6. Instalación con barra de progreso -----------------------------------------------

PASOS=(
  "10|Instalando Docker|paso_docker"
  "20|Conectando con el registro de imágenes|paso_registro"
  "30|Bajando el paquete de instalación|paso_paquete"
  "40|Generando claves y configuración|paso_configurar"
  "50|Preparando el certificado de seguridad|paso_certificado"
  "60|Abriendo los puertos de telefonía|paso_cortafuegos"
  "85|Bajando las imágenes (la parte más larga)|paso_imagenes"
  "95|Arrancando la central|paso_arrancar"
  "100|Últimos detalles|paso_final"
)

paso_docker() {
  command -v docker >/dev/null && docker compose version >/dev/null 2>&1 && return 0
  curl -fsSL https://get.docker.com | sh && systemctl enable --now docker
}

paso_registro() {
  local usuario token
  usuario=$(json 'd["descarga"]["usuario"]' < "$ACTIVACION"); token=$(json 'd["descarga"]["token"]' < "$ACTIVACION")
  [ -z "$usuario" ] && return 0  # registro público
  printf '%s' "$token" | docker login "${REGISTRO%%/*}" -u "$usuario" --password-stdin
}

paso_paquete() {
  local tmp; tmp=$(mktemp -d)
  docker pull -q "$REGISTRO/nspbx-paquete:$VERSION" \
    && docker run --rm "$REGISTRO/nspbx-paquete:$VERSION" > "$tmp/p.tgz" \
    && tar -xzf "$tmp/p.tgz" -C "$tmp" \
    && cp -rn "$tmp/nspbx/." "$DIR/" && cp "$tmp/nspbx/VERSION" "$tmp/nspbx/nspbx" "$tmp/nspbx/docker-compose.yml" "$tmp/nspbx/docker-compose.instalacion.yml" "$DIR/"
  local r=$?; rm -rf "$tmp"; return $r
}

paso_configurar() {
  cd "$DIR" || return 1
  if [ ! -f .env ]; then
    ADMIN_PASSWORD=$(openssl rand -base64 18 | tr -dc 'A-Za-z0-9' | head -c 16)
    guardar admin "$ADMIN_PASSWORD"
    PBX_HOST="$HOST" ACME_RESOLVER=letsencrypt IP_PUBLICA="${IP_PUB:-$HOST}" ADMIN_PASSWORD="$ADMIN_PASSWORD" \
      bash scripts/setup.sh || return 1
    {
      echo
      echo "# --- Instalación local (lo escribió instalador/instalar.sh) ---"
      echo "CENTRAL_URL=$CENTRAL"
      echo "NSPBX_REGISTRO=$REGISTRO"
      echo "NSPBX_VERSION=$VERSION"
      echo "ACME_EMAIL=$CORREO"
      echo "TZ=$(timedatectl show -p Timezone --value 2>/dev/null || echo America/Bogota)"
    } >> .env
    # En red local no hay relay de audio público, y Traefik no pide
    # certificados por HTTP (nadie de afuera llega): usa el de certs/.
    if [ "$MODO" = "local" ]; then
      sed -i -e 's/^TURN_HOST=.*/TURN_HOST=/' -e 's/^ACME_RESOLVER=.*/ACME_RESOLVER=/' .env
      echo "IP_LOCAL=$IP_LAN" >> .env
    fi
  fi
  # La licencia que importa el backend al arrancar (services/licencia_local.py).
  mkdir -p secrets
  python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); json.dump({k: d[k] for k in ("instalacion_id","token","documento","firma")}, open(sys.argv[2],"w"))' \
    "$ACTIVACION" secrets/licencia.json || return 1
  chmod 600 secrets/licencia.json && chown -R 10001:10001 secrets
  # Hoja de recuperación: sin la clave de cifrado, un respaldo restaurado
  # tiene ilegibles las claves de los proveedores.
  {
    echo "NSPBX — hoja de recuperación ($(date +%F))"
    echo "Guárdala FUERA de este servidor y bórrala de aquí después."
    echo
    echo "Panel:                https://$HOST"
    echo "Usuario:              admin"
    echo "Contraseña inicial:   $(leido admin)"
    grep -E '^DATA_ENCRYPTION_KEY=' .env
  } > RECUPERACION.txt
  chmod 600 RECUPERACION.txt
}

# Red local con dirección segura: la clave se genera AQUÍ y nunca sale; a la
# central solo va el CSR. Ella publica el nombre y saca el certificado de
# Let's Encrypt por DNS (tarda hasta un par de minutos).
certificado_real() {
  local token resp
  token=$(json 'd["token"]' < "$ACTIVACION")
  [ -f certs/panel.key ] || openssl ecparam -name prime256v1 -genkey -noout -out certs/panel.key || return 1
  chmod 600 certs/panel.key
  openssl req -new -key certs/panel.key -subj "/CN=$SUBDOMINIO" -addext "subjectAltName=DNS:$SUBDOMINIO" -out certs/panel.csr || return 1
  resp=$(python3 -c 'import json,sys; print(json.dumps({"ip_local": sys.argv[1], "csr": open(sys.argv[2]).read()}))' "$IP_LAN" certs/panel.csr \
    | curl -sS --max-time 300 -H 'Content-Type: application/json' -H "Authorization: Bearer $token" \
        -w '\n%{http_code}' -d @- "$CENTRAL/api/licencia/certificado") || return 1
  if [ "$(printf '%s' "$resp" | tail -1)" != "200" ]; then
    echo "La central no pudo emitir el certificado: $(printf '%s' "$resp" | sed '$d')"
    return 1
  fi
  printf '%s' "$resp" | sed '$d' | json 'd["cadena"]' > certs/panel.crt && [ -s certs/panel.crt ]
}

paso_certificado() {
  cd "$DIR" && mkdir -p traefik certs letsencrypt && chmod 700 letsencrypt
  if [ "$MODO" = "local" ] && [ ! -f certs/panel.crt ]; then
    if [ -n "$SUBDOMINIO" ] && certificado_real; then
      guardar certificado real
      # Algunos routers bloquean nombres públicos que apuntan a IP privadas
      # («protección contra DNS rebinding»): se avisa al final.
      sleep 5
      [ "$(getent ahostsv4 "$SUBDOMINIO" | awk 'NR==1 {print $1}')" = "$IP_LAN" ] || guardar dns_bloqueado si
    else
      [ -n "$SUBDOMINIO" ] && echo "Sin certificado real: se usa uno propio para seguir."
      rm -f certs/panel.crt certs/panel.csr
      openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj "/CN=$HOST" \
        -addext "subjectAltName=IP:$IP_LAN${SUBDOMINIO:+,DNS:$SUBDOMINIO}" -keyout certs/panel.key -out certs/panel.crt || return 1
      guardar certificado propio
    fi
    chmod 600 certs/panel.key
    cat > traefik/certificado.yml <<EOC
tls:
  stores:
    default:
      defaultCertificate:
        certFile: /certs/panel.crt
        keyFile: /certs/panel.key
EOC
  fi
  return 0
}

paso_cortafuegos() {
  command -v ufw >/dev/null && ufw status 2>/dev/null | grep -q "Status: active" || return 0
  ufw allow 80/tcp && ufw allow 443/tcp && ufw allow 5060/udp && ufw allow 5060/tcp \
    && ufw allow 5080/udp && ufw allow 5080/tcp && ufw allow 16384:16584/udp && ufw allow 3478
}

dc() { (cd "$DIR" && docker compose -f docker-compose.yml -f docker-compose.instalacion.yml "$@"); }

paso_imagenes() { dc pull -q; }

paso_arrancar() {
  dc up -d --remove-orphans || return 1
  local i e
  for i in $(seq 1 72); do
    e=$(docker inspect nspbx_backend --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' 2>/dev/null)
    [ "$e" = "healthy" ] && return 0
    sleep 5
  done
  echo "El backend no quedó sano en 6 minutos"; return 1
}

paso_final() {
  ln -sf "$DIR/nspbx" /usr/local/bin/nspbx
  (cd "$DIR" && bash scripts/sonidos.sh) || registrar "Sonidos de FreeSWITCH: se pueden bajar después con scripts/sonidos.sh"
  return 0
}

FALLO=""
{
  for p in "${PASOS[@]}"; do
    IFS='|' read -r pct texto funcion <<< "$p"
    printf 'XXX\n%s\n\n  %s…\nXXX\n' "$((pct - 5))" "$texto"
    registrar "Paso: $texto"
    if ! "$funcion" >> "$LOG" 2>&1; then
      echo "$texto" > "$ESTADO/fallo"
      break
    fi
    printf 'XXX\n%s\n\n  %s ✓\nXXX\n' "$pct" "$texto"
  done
} | whiptail --title "$TITULO · Instalando" --gauge "\n  Empezando…" 9 72 0
FALLO=$(cat "$ESTADO/fallo" 2>/dev/null); rm -f "$ESTADO/fallo"
[ -z "$FALLO" ] || morir "Falló el paso «$FALLO»."

# --- 7. Listo ----------------------------------------------------------------------------

registrar "Instalación terminada"
NOTA_LOCAL=""
if [ "$MODO" = "local" ] && [ "$(leido certificado)" = "propio" ]; then
  NOTA_LOCAL="\nEl navegador avisará que el certificado es propio: es esperado en una\nred local. Acéptalo una vez en cada equipo."
elif [ "$MODO" = "local" ]; then
  NOTA_LOCAL="\nFunciona solo dentro de esta red, con certificado de seguridad real."
  [ "$(leido dns_bloqueado)" = "si" ] && NOTA_LOCAL="$NOTA_LOCAL\n¡Ojo! El DNS de esta red no resuelve $HOST: el router tiene\n«protección contra DNS rebinding». Agrega una excepción para\n${HOST#*.} o usa https://$IP_LAN mientras tanto."
fi
whiptail --title "$TITULO · ¡Listo!" --msgbox "\
NSPBX quedó instalado y funcionando.\n
    Panel:        https://$HOST
    Usuario:      admin
    Contraseña:   $(leido admin)
\nCámbiala al entrar. Te pedirá activar la verificación en dos pasos.
$NOTA_LOCAL
La hoja de recuperación (con la clave de cifrado) está en
$DIR/RECUPERACION.txt: guárdala fuera del servidor y bórrala.
\nPara administrar la central desde aquí:  nspbx  (estado, logs,
actualizar, respaldo, soporte…)" 24 76
clear
echo -e "\n\033[1mNSPBX instalado.\033[0m Panel: https://$HOST — usuario admin. Ayuda: nspbx\n"
}

main "$@"
