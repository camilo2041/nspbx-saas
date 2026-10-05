#!/usr/bin/env bash
#
# Chequeo completo de una instalación: contenedores, secretos, base,
# ESL, troncales, ruteo por Traefik y certificado.
#
#   bash scripts/verificar.sh
#
# Cada línea dice qué se probó y contra qué. No "arregla" nada: solo
# reporta, para poder correrlo tranquilo en producción.

cd "$(dirname "$0")/.."
AUTOLOAD="freeswitch/conf/autoload_configs"
FALLAS=0

ok()    { printf '  \033[32m✓\033[0m %s\n' "$1"; }
falla() { printf '  \033[31m✗\033[0m %s\n' "$1"; FALLAS=$((FALLAS+1)); }
aviso() { printf '  \033[33m!\033[0m %s\n' "$1"; }
titulo(){ printf '\n\033[1m%s\033[0m\n' "$1"; }

titulo "1. Contenedores"
for c in nspbx_postgres nspbx_backend nspbx_voicebot nspbx_freeswitch nspbx_frontend; do
  ESTADO=$(docker inspect "$c" --format '{{.State.Health.Status}}' 2>/dev/null || echo "ausente")
  case "$ESTADO" in
    healthy) ok "$c" ;;
    ausente) falla "$c no existe" ;;
    *)       falla "$c está '$ESTADO'" ;;
  esac
done

# Ninguno de los nuestros corre como root (ver docs/seguridad-y-robustez.md,
# §5.13). Se mira el proceso principal de la app, no el PID 1 del
# contenedor (en FreeSWITCH es tini, que sí es root).
uid_de() { docker exec "$1" sh -c "for p in /proc/[0-9]*; do [ \"\$(cat \$p/comm 2>/dev/null)\" = '$2' ] && awk '/^Uid/ {print \$2; exit}' \$p/status && exit; done" 2>/dev/null; }
for par in nspbx_backend:uvicorn nspbx_voicebot:uvicorn nspbx_freeswitch:freeswitch nspbx_frontend:node; do
  c="${par%%:*}"; proc="${par##*:}"
  u="$(uid_de "$c" "$proc")"
  case "$u" in
    "") aviso "$c: no pude ver con qué usuario corre $proc" ;;
    0)  falla "$c: $proc corre como root" ;;
    *)  ok "$c: $proc corre sin root (uid $u)" ;;
  esac
done

# Prioridad de tiempo real de FreeSWITCH: política de planificación de sus
# hilos (campo 41 de /proc/<pid>/task/*/stat: 1 = SCHED_FIFO).
RT=$(docker exec nspbx_freeswitch sh -c 'for p in /proc/[0-9]*; do [ "$(cat $p/comm 2>/dev/null)" = freeswitch ] && pid=${p#/proc/}; done; [ -n "$pid" ] && cat /proc/$pid/task/*/stat | awk "\$41 == 1 {rt++} END {print rt+0 \"/\" NR}"' 2>/dev/null)
case "$RT" in
  ""|0/*) aviso "FreeSWITCH sin prioridad de tiempo real ($RT hilos): el audio puede entrecortarse con la CPU ocupada. Ver «Prioridad de tiempo real» en docs/seguridad-y-robustez.md" ;;
  *)      ok "FreeSWITCH con prioridad de tiempo real ($RT hilos)" ;;
esac

# Topes de memoria (docker-compose.yml): un contenedor que se pasa lo
# reinicia Docker. Se mira si ya pasó (OOMKilled, reinicios) y si alguno
# anda cerca. Para ajustar los topes: bash scripts/medir-recursos.sh
for c in nspbx_backend nspbx_voicebot nspbx_frontend; do
  oom=$(docker inspect "$c" --format '{{.State.OOMKilled}}' 2>/dev/null) || continue
  reinicios=$(docker inspect "$c" --format '{{.RestartCount}}')
  uso=""
  [ "$(docker inspect "$c" --format '{{.State.Running}}')" = "true" ] && uso=$(docker stats --no-stream --format '{{.MemPerc}}' "$c" | tr -d '%')
  if [ "$oom" = "true" ]; then
    falla "$c: Docker lo mató por pasar su tope de memoria. Medí con scripts/medir-recursos.sh y subí el tope en .env"
  elif [ "${reinicios:-0}" -gt 0 ]; then
    aviso "$c se reinició $reinicios vez/veces desde que se creó (docker logs $c para ver por qué)"
  fi
  case "$uso" in
    ""|*[!0-9.]*) ;;
    *) if [ "${uso%.*}" -ge 80 ]; then aviso "$c usa el ${uso}% de su tope de memoria"; else ok "$c: memoria al ${uso}% de su tope"; fi ;;
  esac
done

# coturn solo si está pedido: es opcional y arranca con --profile turn.
# Se comprueba acá y no en la lista de arriba porque su ausencia es lo
# normal — el relay hace falta únicamente cuando la red del usuario
# bloquea el UDP del audio.
if [ -n "$(grep '^TURN_SECRET=' .env 2>/dev/null | cut -d= -f2-)" ]; then
  case "$(docker inspect nspbx_coturn --format '{{.State.Health.Status}}' 2>/dev/null || echo ausente)" in
    healthy) ok "nspbx_coturn (relay de audio)" ;;
    ausente) falla "hay TURN_SECRET en .env pero coturn no está corriendo — docker compose --profile turn up -d" ;;
    *)       falla "nspbx_coturn no está sano" ;;
  esac
fi

titulo "2. Secretos sincronizados"
# La causa nº1 de fallas silenciosas: el mismo valor tiene que estar
# repetido idéntico en varios archivos. Si no coincide, el sistema
# arranca igual y falla después con 403 o "conexión rechazada".
ESL_ENV=$(grep '^FS_ESL_PASSWORD=' .env 2>/dev/null | cut -d= -f2-)
ESL_XML=$(grep -oE 'name="password" value="[^"]+"' "$AUTOLOAD/event_socket.conf.xml" 2>/dev/null | sed 's/.*value="//;s/"//')
XML_ENV=$(grep '^FS_XML_SECRET=' .env 2>/dev/null | cut -d= -f2-)
XML_CURL=$(grep -oE 'secret=[^"]+' "$AUTOLOAD/xml_curl.conf.xml" 2>/dev/null | head -1 | cut -d= -f2-)
XML_CDR=$(grep -oE '/fs/cdr/[^"]+' "$AUTOLOAD/json_cdr.conf.xml" 2>/dev/null | head -1 | cut -d/ -f4)

[ -n "$ESL_ENV" ] && [ "$ESL_ENV" = "$ESL_XML" ] \
  && ok "clave ESL: .env == event_socket.conf.xml" \
  || falla "clave ESL NO coincide entre .env y event_socket.conf.xml"

if [ -n "$XML_ENV" ] && [ "$XML_ENV" = "$XML_CURL" ] && [ "$XML_ENV" = "$XML_CDR" ]; then
  ok "secreto XML: .env == xml_curl == json_cdr"
else
  falla "secreto XML NO coincide (.env=${XML_ENV:0:8}… xml_curl=${XML_CURL:0:8}… json_cdr=${XML_CDR:0:8}…)"
fi

titulo "3. IP pública anunciada"
# El fallo más caro de diagnosticar de toda la migración: vars.xml venía
# con la IP del servidor anterior, FreeSWITCH la anunciaba en el Contact,
# el proveedor respondía a una dirección ajena y el REGISTER moría por
# timeout mostrando un 503 que no menciona nada de esto.
IP_REAL=$(curl -fsS --max-time 10 https://api.ipify.org 2>/dev/null)
# Solo las líneas X-PRE-PROCESS reales: los comentarios del archivo traen
# ejemplos como data="external_rtp_ip=1.2.3.4" y un grep suelto los
# tomaría como si fueran la configuración vigente.
IP_CFG=$(grep -oE '<X-PRE-PROCESS[^>]*external_sip_ip=[^"]+' freeswitch/conf/vars.xml 2>/dev/null | sed 's/.*external_sip_ip=//')
if [ -z "$IP_CFG" ]; then
  falla "no se pudo leer external_sip_ip de vars.xml"
elif [ "$IP_CFG" = "REEMPLAZAR_POR_IP_PUBLICA" ]; then
  falla "vars.xml sin configurar — corré: bash scripts/setup.sh"
elif [ -n "$IP_REAL" ] && [ "$IP_CFG" != "$IP_REAL" ]; then
  falla "vars.xml anuncia $IP_CFG pero la IP real es $IP_REAL (¿se movió de servidor?)"
else
  ok "vars.xml anuncia la IP correcta ($IP_CFG)"
fi

# No alcanza con external_sip_ip. La señalización y el audio se anuncian
# con variables DISTINTAS, y una puede quedar bien mientras la otra no:
# tras la migración, external_sip_ip y external_rtp_ip tenían la IP
# pública nueva y webrtc_ext_ip seguía con la IP LAN del servidor viejo.
# Resultado: la troncal registraba, las llamadas entraban, el softphone
# se registraba — y el audio del navegador se iba a una dirección
# inalcanzable. Este chequeo decía "Todo en orden" mientras pasaba.
V=$(grep -oE '<X-PRE-PROCESS[^>]*external_rtp_ip=[^"]+' freeswitch/conf/vars.xml 2>/dev/null | sed 's/.*external_rtp_ip=//')
if [ -z "$V" ]; then
  falla "no se pudo leer external_rtp_ip de vars.xml"
elif [ -n "$IP_REAL" ] && [ "$V" != "$IP_REAL" ]; then
  falla "external_rtp_ip es $V pero la IP real es $IP_REAL (llamadas sin audio)"
else
  ok "external_rtp_ip correcto ($V)"
fi

# webrtc_ext_ip es la dirección que se le anuncia al NAVEGADOR, y lo que
# tiene que valer depende de si hay relay TURN o no. Son dos modos
# opuestos y poner el valor del otro deja la llamada muda:
#
#   sin TURN  -> el navegador manda el audio él mismo, así que necesita
#                la IP PÚBLICA. Requiere el rango UDP abierto.
#   con TURN  -> quien entrega el audio es coturn, que vive DENTRO de la
#                red de Docker. Si le anunciamos la IP pública, le
#                mandaría el audio a la IP pública de su propia red y el
#                router tendría que hacer hairpin NAT — que es justo lo
#                que el relay viene a evitar. Va $${local_ip_v4}, que
#                FreeSWITCH resuelve a su IP de contenedor.
W=$(grep -oE '<X-PRE-PROCESS[^>]*webrtc_ext_ip=[^"]+' freeswitch/conf/vars.xml 2>/dev/null | sed 's/.*webrtc_ext_ip=//')
TURN_CFG=$(grep '^TURN_SECRET=' .env 2>/dev/null | cut -d= -f2-)
if [ -z "$W" ]; then
  falla "no se pudo leer webrtc_ext_ip de vars.xml"
elif [ -n "$TURN_CFG" ]; then
  case "$W" in
    '$${local_ip_v4}'|10.*|192.168.*|172.1[6-9].*|172.2[0-9].*|172.3[01].*)
      ok "webrtc_ext_ip apunta hacia adentro ($W), correcto con TURN" ;;
    *)
      falla "hay TURN configurado pero webrtc_ext_ip es $W: coturn no puede entregarle el audio a una IP pública desde adentro. Poné \$\${local_ip_v4}" ;;
  esac
elif [ "$W" = "REEMPLAZAR_POR_IP_PUBLICA" ]; then
  falla "webrtc_ext_ip sin configurar — corré: bash scripts/setup.sh"
elif [ -n "$IP_REAL" ] && [ "$W" != "$IP_REAL" ]; then
  falla "webrtc_ext_ip es $W pero la IP real es $IP_REAL (softphone sin audio fuera de la LAN)"
else
  ok "webrtc_ext_ip correcto ($W)"
fi

  # El puerto de señalización tiene que coincidir entre vars.xml y el
  # compose. Si no, FreeSWITCH manda desde un puerto que Docker no
  # publica y las llamadas ENTRANTES no llegan (el registro saliente sí
  # funciona, así que el problema aparece recién con la primera llamada).
  PUERTO_FS=$(grep -oE '<X-PRE-PROCESS[^>]*external_sip_port=[^"]+' freeswitch/conf/vars.xml 2>/dev/null | sed 's/.*external_sip_port=//')
  if [ -n "$PUERTO_FS" ]; then
    if grep -q "\"${PUERTO_FS}:${PUERTO_FS}/udp\"" docker-compose.yml 2>/dev/null; then
      ok "puerto SIP saliente $PUERTO_FS publicado en el compose"
    else
      falla "vars.xml usa el puerto $PUERTO_FS pero el compose no lo publica"
    fi
  fi

titulo "4. Base de datos"
if docker exec nspbx_postgres pg_isready -U "${POSTGRES_USER:-nspbx}" >/dev/null 2>&1; then
  ok "postgres acepta conexiones"
  for t in users extensions trunks appointments call_logs; do
    N=$(docker exec nspbx_postgres psql -U "${POSTGRES_USER:-nspbx}" -d "${POSTGRES_DB:-nspbx}" -t -A -c "SELECT count(*) FROM $t;" 2>/dev/null)
    [ -n "$N" ] && ok "tabla $t: $N registro(s)" || falla "no se pudo leer la tabla $t"
  done
else
  falla "postgres no responde"
fi

titulo "5. FreeSWITCH (ESL) y troncales"
ESL_OUT=$(docker exec nspbx_backend python -c "
import asyncio,sys; sys.path.insert(0,'/app')
from app.services import esl
from app.core.database import async_session
from app.models import Trunk
from sqlalchemy import select
async def m():
    st = await esl.status()
    print('VERSION', st.get('version','?')[:30])
    print('SESIONES', st.get('current_sessions','?'))
    async with async_session() as s:
        ts=(await s.execute(select(Trunk))).scalars().all()
    for t in ts:
        g=await esl.gateway_status(t.name)
        print('TRUNK', t.name, g.get('state'))
asyncio.run(m())
" 2>/dev/null)

if [ -n "$ESL_OUT" ]; then
  ok "ESL responde ($(echo "$ESL_OUT" | grep VERSION | cut -d' ' -f2-))"
  ok "llamadas activas: $(echo "$ESL_OUT" | grep SESIONES | awk '{print $2}')"
  if echo "$ESL_OUT" | grep -q TRUNK; then
    # Sustitución de proceso y NO "... | while": con una tubería, bash
    # corre el while en un SUBSHELL y el incremento de FALLAS se pierde
    # al salir de él. El script mostraba la troncal caída con ✗ y aun
    # así cerraba con "Todo en orden" y código de salida 0 — es decir,
    # aprobaba una instalación rota.
    while read -r _ N E; do
      [ "$E" = "REGED" ] && ok "troncal $N registrada" || falla "troncal $N en estado '$E'"
    done < <(echo "$ESL_OUT" | grep TRUNK)
  else
    aviso "no hay troncales cargadas todavía"
  fi
else
  falla "el backend no puede hablar con FreeSWITCH por ESL"
fi

titulo "6. Publicación web"
HOST=$(grep '^PBX_HOST=' .env 2>/dev/null | cut -d= -f2-)
if [ -z "$HOST" ]; then
  aviso "PBX_HOST no está en .env — se omite el chequeo web"
else
  case "$HOST" in
    *://*|*/*) falla "PBX_HOST mal escrito ('$HOST'): va solo el dominio, sin https:// ni barra" ;;
  esac
  P=$(curl -k -s -o /dev/null -w '%{http_code}' --max-time 10 "https://$HOST/")
  A=$(curl -k -s -o /dev/null -w '%{http_code}' --max-time 10 "https://$HOST/api/auth/me")
  [ "$P" = "200" ] || [ "$P" = "307" ] && ok "panel responde ($P)" || falla "panel devolvió $P"
  # 401 es lo correcto: el backend contesta y rechaza por falta de sesión.
  [ "$A" = "401" ] && ok "API responde y exige sesión (401)" || falla "API devolvió $A (se esperaba 401)"
  # Sin -k: si esto funciona, el certificado es de verdad y no de staging.
  if curl -s -o /dev/null --max-time 10 "https://$HOST/" 2>/dev/null; then
    ok "certificado válido y confiable"
  else
    aviso "certificado NO confiable — ¿sigue el caserver de staging en Traefik?"
  fi
  # /fs/* no debe ser alcanzable desde internet.
  F=$(curl -k -s -o /dev/null -w '%{http_code}' --max-time 10 "https://$HOST/fs/cdr/x")
  [ "$F" = "404" ] && ok "/fs/* no expuesto (404)" || aviso "/fs/* devolvió $F — debería ser 404"
fi

titulo "Resultado"
if [ "$FALLAS" -eq 0 ]; then
  printf '  \033[32mTodo en orden.\033[0m\n\n'
else
  printf '  \033[31m%s comprobación(es) fallaron.\033[0m\n\n' "$FALLAS"
  exit 1
fi
