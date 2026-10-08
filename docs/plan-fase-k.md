# Fase K: instalación local con licencia de la central

**Estado: hecha.**

Un cliente corre **todo el sistema en su propio servidor**: panel, API, base de
datos, FreeSWITCH y voizbot. Sus datos (grabaciones, contactos, llamadas) no
salen de ahí. Nosotros seguimos mandando en lo comercial: qué empresa es, su
tipo, sus módulos, su plan, sus topes y hasta cuándo vale. Todo eso lo
decidimos desde **nuestra** plataforma (la central) y llega firmado.

Decisiones tomadas con el cliente:

- **Una sola empresa** por instalación local.
- **Siempre con internet.** El servidor habla con la central cada hora. Un
  corte corto no afecta: hay **72 h de gracia** (la central puede cambiarlo).
- **Los datos se quedan en el servidor del cliente.** A la central solo sube
  un resumen de uso (cantidades), nunca grabaciones, números ni nombres.
- **Instalación como la de un juego**: un asistente en pantalla, con barra de
  progreso, que revisa el equipo, pide el código de activación y deja todo
  andando.

## Cómo funciona

```
 Central (nuestra nube)                       Servidor del cliente
 ─────────────────────                       ─────────────────────
 Plataforma › Instalaciones                   instalar.sh (asistente)
   «Nueva instalación» → código                 │ pide el código
   NSPBX-XXXX-XXXX-XXXX ──────────────────────▶ │ POST /api/licencia/activar
                                                │ ◀── token + licencia firmada
 Clave privada Ed25519                         backend en MODO_INSTALACION=local
   (solo en la central)                          │ verifica la firma con la
                                                 │ clave pública de la imagen
 POST /api/licencia/latido  ◀──── cada hora ─────┤ sube el uso
   devuelve la licencia firmada ────────────────▶│ aplica empresa, plan y topes
```

### La licencia firmada

Un documento JSON firmado con **Ed25519**. La clave privada vive solo en la
central (`LICENCIA_CLAVE_PRIVADA`); cada instalación verifica con la clave
pública (`LICENCIA_CLAVE_PUBLICA`, que va dentro de la imagen publicada).
Contiene:

- la instalación (id) y la empresa: nombre, slug, tipo de negocio, módulos;
- la licencia: plan, estado (activa, prueba, suspendida), vencimiento y topes;
- `emitida` y `valida_hasta` (= emitida + gracia).

Una base editada a mano no sirve de nada: lo que vale es el documento, y sin
la clave privada no se puede fabricar uno.

### Qué pasa si no hay contacto con la central

El vencimiento efectivo de la licencia local es el **menor** entre el
vencimiento comercial y `valida_hasta`. Pasadas las 72 h sin latido, la
licencia queda **vencida** con el comportamiento que ya existe
(`core/auth.py:licencia_operativa`, `workers/dialer.py`):

- los teléfonos siguen llamando y recibiendo (el dialplan no se corta);
- se detienen las campañas y no se puede crear ni modificar nada;
- el panel muestra por qué: «Sin conexión con la central desde …».

Al volver la conexión, el primer latido lo deja todo como estaba.

**Suspender o revocar** una instalación desde la central: el próximo latido
devuelve una licencia firmada con estado `suspendida`, y la instalación la
aplica igual que cualquier otra.

### Límite honesto

Quien tenga root en el servidor puede, en teoría, modificar el programa. La
firma, el latido y las imágenes cerradas impiden el uso casual y dejan rastro
(la central ve cada latido y su versión); el resto lo cubre el contrato.

## Bloques

| Bloque | Dónde | Notas |
|---|---|---|
| K1. Central | `api/instalaciones.py`, `services/licencia_firmada.py`, revisión 0039, Plataforma › Empresas › Instalaciones locales | Alta con código `NSPBX-XXXX-XXXX-XXXX` (solo su hash, vence en 7 días, se dicta sin confundir letras). Nuevo código (invalida el token anterior al usarse), suspender, reactivar, revocar, borrar. `activar` y `latido` abiertos con tope por IP. La central sirve el instalador en `/api/licencia/instalar.sh` con su dirección puesta. |
| K2. Modo local | `services/licencia_local.py`, `app/cli/licencia.py`, Ajustes › Licencia, franja de aviso | Importa `secrets/licencia.json` al arrancar; sin licencia válida, suspendida. Latido cada hora; sin central, reaplica la guardada (deshace cambios a mano). No acepta licencias viejas, de otra instalación o con otra firma. Sin usuario plataforma; empresas y servidores, 403. El arranque exige clave pública y `CENTRAL_URL`. |
| K3. Instalador | `backend/app/recursos/instalar.sh` (enlazado en `instalador/`), `instalador/nspbx`, `instalador/docker-compose.instalacion.yml`, `.github/workflows/publicar.yml` | Asistente con pantallas, revisión del equipo, activación, dominio o red local, barra de progreso y pantalla final; retoma si se corta. Hoja de recuperación con la clave de cifrado. Comando `nspbx` para el día a día. El workflow publica las imágenes (con la clave pública y la versión) y el paquete de instalación en ghcr.io. |
| K4. Panel y pruebas | `components/instalaciones-locales.tsx`, `components/licencia-local.tsx`, `tests/test_instalaciones.py` | Firma, código, activación, latido, suspensión, revocación, reinstalación, gracia, licencias alteradas o viejas, arranque. |

## Para desplegar

**En la central (una vez):**

1. Migraciones hasta la 0039.
2. Generar el par de claves: `docker compose exec backend python -m app.cli.claves_licencia`.
   - `LICENCIA_CLAVE_PRIVADA` va en el `.env` de la central (y una copia fuera del servidor).
   - `LICENCIA_CLAVE_PUBLICA` va como secreto del repositorio en GitHub (Settings › Secrets › Actions).
3. Publicar una versión: etiqueta `v1.0.0` (o «Publicar versión» a mano en Actions).
4. En el `.env` de la central: `VERSION_PUBLICADA=1.0.0`, y `REGISTRO_USUARIO` /
   `REGISTRO_TOKEN` con un token de GitHub de solo lectura de paquetes
   (`read:packages`). Si los paquetes de ghcr.io se hacen públicos, se dejan vacíos.
5. Reiniciar el backend de la central.

**Por cada cliente:**

1. Plataforma › Empresas: crear la empresa con su tipo, módulos y licencia.
2. Instalaciones locales › + Instalación → copiar el código y el comando.
3. En su servidor (Ubuntu 22.04/24.04 o Debian 12, 4 núcleos, 8 GB, 80 GB):
   `curl -fsSL https://<central>/api/licencia/instalar.sh | sudo bash`.
4. Para cambiar su plan, topes o vencimiento: se edita la empresa en la
   central; le llega en el próximo latido (o con `sudo nspbx licencia`).

**Límite conocido:** el token del registro es el mismo para todas las
instalaciones (lo da la central al activar). Revocar una instalación le
corta la licencia, no la descarga de imágenes; si hiciera falta, se rota el
token en GitHub y en el `.env` de la central.
