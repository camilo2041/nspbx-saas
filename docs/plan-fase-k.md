# Fase K: instalación local con licencia de la central

**Estado: en curso.**

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

| Bloque | Qué |
|---|---|
| K1. Central | Tabla `instalaciones` (de la plataforma, sin `tenant_id`). Plataforma › Instalaciones locales: crear (da el código de activación una sola vez, vence en 7 días), nuevo código, suspender, revocar. `services/licencia_firmada.py`: arma, firma y verifica. Públicos: `POST /api/licencia/activar` (código → token + licencia) y `POST /api/licencia/latido` (token → licencia; sube versión y uso). Con tope por IP. |
| K2. Modo local | `MODO_INSTALACION=local`. Tabla `licencia_local` (una fila, token cifrado). Al arrancar importa `secrets/licencia.json` que deja el instalador. Latido cada hora (el líder). Aplica la licencia a la empresa y a `licenses`. Sin usuario `plataforma`; empresas, licencias y servidores de FreeSWITCH en solo lectura. `GET /api/licencia/local` para el panel. |
| K3. Instalador | `instalador/instalar.sh`: asistente con `whiptail` (revisión del equipo, código, acceso por dominio o red local, resumen, barra de progreso, pantalla final). Compose de instalación con su propio Traefik (Let's Encrypt o certificado propio). Comando `nspbx` para después: estado, logs, actualizar, respaldo, licencia, soporte, desinstalar. Workflow que publica las imágenes y el paquete de instalación. |
| K4. Panel y cierre | Plataforma › Instalaciones locales (último latido, versión, uso, estado). En la instalación local: estado de la licencia en Ajustes y aviso arriba si no hay conexión. Pruebas, matriz de permisos, documento final. |

## Para desplegar

1. En la central: generar el par de claves (`python -m app.cli.claves_licencia`)
   y poner `LICENCIA_CLAVE_PRIVADA` en su `.env`. La pública va como secreto
   del repositorio para publicar las imágenes.
2. Migraciones.
3. Plataforma › Instalaciones locales → Nueva → darle el código al cliente.
4. En el servidor del cliente: el comando de una línea del instalador.
