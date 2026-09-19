# NSPBX — PBX básico con FreeSWITCH + FastAPI

Sistema tipo Issabel pero minimalista: troncales SIP, extensiones, marcación masiva (autodialer) y voizbots (IVR/IA).

## Stack

- **FreeSWITCH 1.10** (`safarov/freeswitch`) — motor telefónico
- **FastAPI** — API de gestión + endpoints XML para `mod_xml_curl` + autodialer
- **Next.js 16** (React 19 + Tailwind 4) — frontend de gestión
- **PostgreSQL 16** — persistencia
- **Docker Compose** — entorno completo

## Arquitectura

```
softphone/telefono → SIP :5060 → FreeSWITCH (mod_sofia)
                                      ├─ mod_xml_curl → backend /fs/directory (extensiones)
                                      ├─ mod_xml_curl → backend /fs/dialplan   (rutas/IVR)
                                      └─ ESL :8021    → backend (originate, status)
backend → gateways → freeswitch/conf/sip_profiles/external/gw_*.xml + sofia rescan
```

Las extensiones y el dialplan se generan dinámicamente desde la DB (mod_xml_curl).
Las troncales se aplican en caliente escribiendo el gateway y haciendo `sofia profile external rescan`.

## Arranque

```bash
docker compose up -d --build
```

Verificar:

```bash
curl http://localhost:8001/health          # backend OK
curl http://localhost:8001/fs/dialplan     # dialplan XML servido a FreeSWITCH
curl http://localhost:3005                 # frontend OK
```

- Frontend de gestión: http://localhost:3005
- API docs (Swagger): http://localhost:8001/docs
- FreeSWITCH console: `docker exec -it nspbx_freeswitch fs_cli`

> Requisito: Docker Desktop con RAM suficiente (si hay muchos proyectos activos, detenerlos o
> subir la memoria asignada). Si el engine no levanta: cerrar Docker Desktop y relanzar.

## Usuarios y acceso

El panel exige iniciar sesión. En el primer arranque, si la tabla de usuarios está vacía, el backend
crea la cuenta `admin` y **escribe la contraseña en el log del contenedor**:

```bash
docker compose logs backend | grep -A 3 "Usuario inicial"
```

Para fijarla en vez de que se genere, poner `ADMIN_PASSWORD` en `.env` antes del primer arranque.

`AUTH_SECRET` (también en `.env`) firma los tokens de sesión. Si falta, se genera una clave al azar en
cada arranque y todo el mundo queda desconectado al reiniciar el backend. Si se cambia, pasa lo mismo.

### Roles

| Rol | Alcance |
| --- | --- |
| **Administrador** | Todo: usuarios, ajustes, troncales, extensiones y rutas. |
| **Supervisor** | Operación completa: llamadas, colas, campañas, voizbots y consumo de IA. No toca la configuración. |
| **Coordinador** | Día a día: agenda, campañas, llamadas y consumo. Consulta los voizbots sin editarlos. |
| **Asesor** | Su extensión: softphone, la agenda y **solo sus propias llamadas**. |

Un asesor necesita una extensión asignada, y cada extensión pertenece a una sola persona: el filtro de
"mis llamadas" y el registro del softphone se apoyan en esa relación.

Los permisos viven en `backend/app/core/permissions.py`. Los endpoints piden permisos, no roles, así que
para agregar un rol nuevo basta con añadir una fila a `PERMISOS_POR_ROL`.

## Uso rápido

### 1. Crear extensión

```bash
curl -X POST localhost:8001/api/extensions -H 'Content-Type: application/json' \
  -d '{"number":"1000","password":"clave","caller_id_name":"Agente Uno"}'
```

Conecta un softphone (Zoiper/MicroSIP) a `IP_MAQUINA:5060`, usuario `1000`, password `clave`,
transport UDP. Dos extensiones pueden llamarse entre sí.

### 2. Crear troncal (proveedor SIP)

```bash
curl -X POST localhost:8001/api/trunks -H 'Content-Type: application/json' \
  -d '{"name":"mi-provider","gateway_host":"sip.provider.com","gateway_port":5060,"username":"user","password":"pass"}'
```

Se genera automáticamente el gateway y se aplica en FreeSWITCH. El autodialer marca por
`sofia/gateway/<nombre-troncal>`.

### 3. Crear voizbot

```bash
curl -X POST localhost:8001/api/voicebots -H 'Content-Type: application/json' \
  -d '{"name":"bot-ventas","bot_type":"ivr","welcome_message":"Bienvenido a central","config":"{\"menu\":{\"1\":\"ventas\",\"2\":\"soporte\"}}"}'
```

`bot_type` puede ser `ivr` (menú DTMF) o `ai` (para integrar STT/LLM/TTS, en desarrollo).

### 4. Campaña de marcación masiva

```bash
curl -X POST localhost:8001/api/campaigns -H 'Content-Type: application/json' \
  -d '{"name":"camp-1","trunk_id":1,"voicebot_id":1,"max_concurrency":5,"retries":1}'

curl -X POST localhost:8001/api/campaigns/1/numbers -H 'Content-Type: application/json' \
  -d '{"phones":["5551001","5551002","5551003"]}'

curl -X POST localhost:8001/api/campaigns/1/start
curl localhost:8001/api/campaigns/1/stats
```

El autodialer respeta `max_concurrency`, reintenta `retries` veces y pasa la campaña a `done`
cuando no quedan números pendientes.

## Estructura

```
backend/app/
  api/           routers: trunks, extensions, voicebots, campaigns, system, settings
  core/          config (env), runtime_settings (config editable en caliente), database (SQLAlchemy async)
  models/        Trunk, Extension, VoiceBot, Campaign, CampaignNumber, CallLog, SystemSettings
  schemas/       modelos Pydantic
  services/      esl.py (cliente ESL asyncio), config_generator.py (XML), gateways.py
  workers/       dialer.py (autodialer)
frontend/
  app/           páginas: dashboard, extensiones, troncales, voizbots, campañas, ajustes
  components/    layout (sidebar) + ui (Card, Button, Modal, Badge, ...)
  lib/           api client + tipos + utils
freeswitch/conf/ config montada en el contenedor
```

## Configuración desde el frontend

Todas las entidades (troncales, extensiones, voizbots, campañas) se crean, editan y eliminan
desde el frontend, con botones para aplicar/recargar los cambios en FreeSWITCH (`rescan` de
troncales, `reload` de extensiones y voizbots). La página **Ajustes** (`/settings`) permite
editar en caliente los parámetros generales del PBX (dominio SIP, host/puerto/password de ESL,
URL base HTTP de FreeSWITCH) sin tocar variables de entorno ni reiniciar contenedores —
se guardan en la tabla `system_settings` y se aplican de inmediato al cliente ESL.

## Pendiente / siguiente paso

- Detección real de estados de llamada (answered/busy/noanswer) vía eventos ESL
- Motor de voizbot IA (Whisper + LLM + TTS) en `workers/`
- Autenticación / gestión de usuarios del panel de administración

## Seguridad de la instalación

- **Sin contraseñas de fábrica.** `POSTGRES_PASSWORD` y `POSTGRES_APP_PASSWORD` son
  obligatorias: si faltan en `.env`, `docker compose up` se niega a arrancar.
  `bash scripts/setup.sh` genera todos los secretos (incluida la contraseña por
  defecto de FreeSWITCH) y los deja sincronizados.
- **Puertos.** Solo salen a Internet SIP (5060 TCP/UDP), 15080/UDP y el rango RTP.
  El SIP sobre WebSocket (5066/7443) queda en `127.0.0.1`: en producción el
  softphone entra por Traefik (`/sip`) a través de la red interna de Docker.
  El puerto de control ESL (8021) nunca se publica.
- **Fuerza bruta SIP.** FreeSWITCH registra los intentos fallidos
  (`log-auth-failures`); para bloquear las IPs hay que instalar fail2ban en el
  servidor con los archivos de `deploy/fail2ban/` (instrucciones dentro del jail).
- **Claves TLS de FreeSWITCH.** `freeswitch/conf/tls/` no se versiona: FreeSWITCH
  las regenera solo. Para rotarlas: borra `wss.pem` y `dtls-srtp.pem` de esa
  carpeta y ejecuta `docker compose restart freeswitch`.
- **Rotar secretos** (`FS_XML_SECRET`, `FS_ESL_PASSWORD`): cámbialos en `.env` y
  vuelve a correr `bash scripts/setup.sh`, que reescribe los XML de FreeSWITCH
  para que coincidan; después `docker compose up -d --build`.
