# Runbook 9 — Rotación de cada secreto

Para cada secreto: dónde vive, qué permite si se filtra, cómo rotarlo y qué
se corta al hacerlo. Si la rotación es por una filtración, empieza por el
runbook 2 (contener primero); este es el detalle de cada paso.

Reglas generales:

- **Uno distinto por variable**, generado al azar: `openssl rand -base64 32`
  (o `48` para `AUTH_SECRET`).
- Después de cambiar el `.env`, `bash scripts/verificar.sh` tiene que
  quedar en verde («Secretos sincronizados» incluido).
- Anotar la rotación (qué, cuándo, quién) en el informe o en la bitácora
  del servidor. Las rotaciones desde el panel quedan solas en la auditoría.
- Rotación preventiva sugerida: cada 12 meses los de infraestructura, al
  salir alguien del equipo todos los que conocía.

## Secretos de infraestructura (`.env` del servidor)

| Secreto | Si se filtra | Cómo rotar | Qué se corta |
|---|---|---|---|
| `AUTH_SECRET` | se fabrican sesiones de cualquier usuario | valor nuevo en `.env` → `docker compose up -d backend voicebot`. Si fue filtración, cerrar también las sesiones de la app: `docker compose exec postgres psql -U nspbx -d nspbx -c "DELETE FROM refresh_tokens"` | todas las sesiones del panel; con el DELETE, también las de la app (vuelven a entrar con usuario y contraseña o huella) |
| `DATA_ENCRYPTION_KEY` | junto con un volcado de la base, se leen las claves de proveedores, troncales y extensiones | la actual pasa a `DATA_ENCRYPTION_KEY_ANTERIOR`, se genera una nueva (`python3 -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"`) → `docker compose up -d backend voicebot` → esperar «Cifrado de secretos: N valores cifrados» en el log → quitar la anterior y reiniciar. **Guardar la nueva fuera del servidor** | nada |
| `FS_ESL_PASSWORD` | originar llamadas y ejecutar comandos en FreeSWITCH (fraude) | valor nuevo en `.env` → `bash scripts/setup.sh` (reescribe `event_socket.conf.xml`) → `docker compose restart freeswitch` → `docker compose up -d backend voicebot` | llamadas en curso (se reinicia FreeSWITCH): hacerlo en horario bajo |
| `FS_XML_SECRET` | leer las claves SIP de **todas** las extensiones y meter llamadas falsas al historial | valor nuevo en `.env` → `bash scripts/setup.sh` (reescribe `xml_curl.conf.xml` y `json_cdr.conf.xml`) → `docker compose restart freeswitch` → `docker compose up -d backend`. Si fue filtración: tratar todas las claves SIP como filtradas | igual que el anterior |
| `POSTGRES_PASSWORD` (dueño de la base) | acceso total a la base, sin aislamiento | la imagen de Postgres solo la usa al crear la base: cambiarla adentro primero, `docker compose exec postgres psql -U nspbx -d nspbx -c "ALTER USER nspbx PASSWORD '<nueva>'"`, después en `.env` y `docker compose up -d backend voicebot` | segundos de reconexión |
| `POSTGRES_APP_PASSWORD` (rol `nspbx_app`) | acceso a la base con aislamiento (RLS) | valor nuevo en `.env` → `docker compose up -d backend` (el arranque le pone la clave nueva al rol) → después `docker compose up -d voicebot` | segundos de reconexión |
| `TURN_SECRET` | usar el relay de audio de la central | valor nuevo en `.env` → `docker compose up -d coturn backend` | las credenciales viejas dejan de valer: el panel y la app las renuevan solos cada 30 min; hasta entonces, en redes que solo dejan salir por 443 el audio puede no pasar. Recargar el panel o reabrir la app las renueva en el acto |
| Clave de respaldos off-site (`BACKUP_PASSPHRASE_FILE`) | junto con un paquete off-site, se lee toda la base y las grabaciones | `openssl rand -base64 48 > nueva; chmod 600 nueva`, apuntar `BACKUP_PASSPHRASE_FILE` a ella. **Guardar la vieja** mientras haya paquetes cifrados con ella (o borrarlos si se filtraron) | nada |
| `APNS_AUTH_KEY` (+ `APNS_KEY_ID`) | mandar notificaciones a la app en iPhone | revocar la clave en developer.apple.com → crear otra → `.env` → `docker compose up -d backend` | nada |
| Cuenta de servicio de FCM (`FCM_SERVICE_ACCOUNT_FILE`) | mandar notificaciones a la app en Android | Google Cloud → IAM → cuentas de servicio → borrar la clave vieja y crear otra → reemplazar `secrets/fcm.json` → `docker compose up -d backend` | nada |
| `ALERTAS_WEBHOOK_URL` | escribir en el canal de alertas | regenerar el webhook en Slack/Teams → `.env` → `docker compose up -d backend` | nada |
| `SMTP_CLAVE` | mandar correo como la plataforma | cambiarla en el proveedor de correo → `.env` → `docker compose up -d backend` | nada (los reportes que fallen se reintentan en la próxima vuelta) |
| `ADMIN_PASSWORD` | solo se usa al crear la base por primera vez | quitarla del `.env` después del primer arranque; la contraseña del admin se cambia en Usuarios | — |

## Secretos que se rotan desde el panel o la app

| Secreto | Dónde | Notas |
|---|---|---|
| Contraseña de un usuario | Usuarios → editar | cierra todas sus sesiones, web y app |
| Verificación en dos pasos | Usuarios → «Restablecer 2 pasos» | la vuelve a configurar al entrar |
| Clave SIP de una extensión | Extensiones → editar → «Generar» | tira el registro y cuelga sus salientes en curso; reconfigurar el teléfono |
| Clave de una troncal | primero en el portal del proveedor, después en Troncales | la troncal se vuelve a registrar sola |
| Claves de IA (modelo, ElevenLabs, Deepgram) | revocar en el proveedor → Ajustes → la sección | aplica a la siguiente llamada |
| Claves de la API pública (`/api/v1`) | Seguridad → Claves de la API → crear la nueva, cambiarla en el sistema que la usa, revocar la vieja | conviene que venzan (Días de validez) |
| Secreto del agente externo | Ajustes → Agente conversacional externo → «Generar» | cambiarlo también en el sistema que agenda por API |
| Turnstile (llamada desde la web) | Cloudflare → Turnstile → rotar la secret key → Ajustes → Llamada desde la web | el botón del sitio sigue funcionando |

## Comprobar

```bash
bash scripts/verificar.sh
docker compose logs --since 10m backend | grep -iE "error|secret|cifrado"
```

Y una llamada entrante, una saliente y un login en la app.
