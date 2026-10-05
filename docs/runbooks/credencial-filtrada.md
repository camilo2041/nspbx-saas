# Runbook 2 — Credencial filtrada

Una contraseña, token o clave quedó expuesta (en un chat, un repositorio,
una captura, un equipo robado) o se sospecha que alguien la está usando.
Regla: **se rota primero y se investiga después**. Rotar de más es barato;
rotar tarde no.

## Confirmar

- Auditoría de la plataforma filtrando por el usuario: accesos desde IPs o
  navegadores que no son los habituales, cambios que nadie reconoce.
- Logins fallidos repetidos (`resultado=denegado`, acción `POST /api/auth/login`).

## Contener y rotar, según qué se filtró

### Usuario del panel (contraseña o sesión)

1. Usuarios → editar → contraseña nueva. Cambiarla **cierra todas sus
   sesiones** (web y app móvil).
2. Si tiene verificación en dos pasos y se sospecha del teléfono: otro
   administrador → Usuarios → *Restablecer 2 pasos*. La vuelve a configurar
   al entrar.
3. Si es un administrador sin MFA todavía: la próxima vez que entre se le
   exigirá activarla (`MFA_OBLIGATORIO`).

### Extensión SIP

Extensiones → editar → contraseña vacía (se genera una de 20 caracteres) →
reconfigurar el teléfono. Mientras tanto, la extensión se puede
deshabilitar.

### Troncal del proveedor

Cambiar la contraseña en el portal del proveedor y en Troncales. Si hubo
llamadas: runbook 1.

### Claves de proveedores de IA (ElevenLabs, Deepgram, LLM)

Revocarla en el panel del proveedor, crear una nueva y cargarla en Ajustes.
Revisar el consumo del proveedor.

### `AUTH_SECRET` (firma de sesiones)

Con ella se pueden fabricar sesiones de cualquier usuario. Generar una nueva
(`openssl rand -base64 48`), ponerla en `.env` y reiniciar el backend:
```bash
docker compose up -d backend
```
Todas las sesiones quedan cerradas (es lo que se busca).

### `FS_ESL_PASSWORD` o `FS_XML_SECRET` (FreeSWITCH)

El ESL permite originar llamadas; `FS_XML_SECRET` da las contraseñas SIP de
todas las extensiones. Cambiar el valor en `.env` y sincronizar los XML:
```bash
bash scripts/setup.sh          # detecta la diferencia y reescribe los XML
docker compose restart freeswitch
docker compose up -d backend voicebot
```
Si se filtró `FS_XML_SECRET`, tratar además **todas** las contraseñas SIP
como filtradas.

### `DATA_ENCRYPTION_KEY` (cifrado de secretos en la base)

Sola no sirve: hace falta además un volcado de la base. Si se filtraron las
dos, tratar como filtradas todas las claves de proveedores y contraseñas de
troncales y extensiones (rotarlas). Para rotar la clave:
```bash
# en .env: la actual pasa a DATA_ENCRYPTION_KEY_ANTERIOR y se genera una nueva
python3 -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
docker compose up -d backend voicebot   # el arranque vuelve a cifrar todo con la nueva
docker compose logs backend | grep "Cifrado de secretos"
```
Cuando el log confirma el recifrado, quitar `DATA_ENCRYPTION_KEY_ANTERIOR`
y reiniciar. Guardar la nueva fuera del servidor.

### Clave de los respaldos off-site (`BACKUP_PASSPHRASE_FILE`)

Los paquetes ya subidos siguen cifrados con la vieja: rotar la clave para
los nuevos y, si el destino remoto también se expuso, borrar los paquetes
viejos de ahí.

## Investigar

Con el `request_id` de cada fila de auditoría se encuentra el detalle en el
log del backend. Reconstruir qué hizo la credencial entre la filtración y
la rotación.

## Cerrar

Informe: qué se filtró, cómo, ventana de exposición, qué se hizo con ella.
Si fue un secreto en el repositorio, el CI (gitleaks) debió frenarlo: ver
por qué no.
