# API pública v1

Para conectar sistemas de la empresa (CRM, agenda, ERP) sin prestarles un
usuario del panel.

## Claves

Se crean en **Seguridad → Claves de la API** (solo el administrador). Cada clave:

- es de una sola empresa y solo ve los datos de esa empresa;
- tiene permisos (`scopes`) elegidos al crearla;
- se muestra **una vez**: se guarda solo su hash;
- puede vencer (recomendado) y se puede revocar en cualquier momento;
- funciona solo en `/api/v1`. El token del panel no entra a `/api/v1`, y la
  clave no entra al panel;
- tiene un tope de `API_LIMITE_POR_MINUTO` peticiones por minuto (120 por
  defecto). Al pasarlo, la respuesta es `429` con `Retry-After`.

Todo lo que se hace con una clave, lecturas incluidas, queda en el registro de
auditoría como `api:<nombre> (<prefijo>)`.

Se envía así:

```
Authorization: Bearer nspbx_<prefijo>_<secreto>
```

o con la cabecera `X-API-Key`.

| Permiso | Para qué |
|---|---|
| `llamadas:leer` | Leer el registro de llamadas |
| `citas:leer` | Leer la agenda |
| `citas:escribir` | Crear citas |
| `campanas:escribir` | Cargar números a campañas |
| `consumo:leer` | Leer el consumo mensual |
| `contactos:leer` | Buscar contactos del CRM |
| `contactos:escribir` | Crear y actualizar contactos del CRM |
| `leads:leer` | Consultar el estado y la disposición de los leads |
| `callbacks:escribir` | Agendar volver a llamar a un lead |

## Endpoints

| Método y ruta | Permiso | Notas |
|---|---|---|
| `GET /api/v1/llamadas?desde=&hasta=&despues_de=&limite=` | `llamadas:leer` | Ordenadas por id. Para paginar, se pasa en `despues_de` el `siguiente` de la respuesta anterior. No incluye grabaciones ni resúmenes. |
| `GET /api/v1/citas?desde=&hasta=&limite=` | `citas:leer` | |
| `POST /api/v1/citas` | `citas:escribir` | Mismo cuerpo que el panel. Responde `409` si el horario está ocupado. |
| `POST /api/v1/campanas/{id}/numeros` | `campanas:escribir` | Mismo cuerpo que el panel (`{"numbers":[{"phone":"…","vars":{…}}]}`). Aplica la política de salientes: los destinos bloqueados vuelven en `bloqueados`. |
| `GET /api/v1/consumo?mes=AAAA-MM` | `consumo:leer` | Ver «Consumo» en docs/seguridad-y-robustez.md. |
| `GET /api/v1/contactos?telefono=&documento=` | `contactos:leer` | Uno de los dos es obligatorio. El teléfono se compara por sus últimos dígitos (da igual el formato). |
| `POST /api/v1/contactos` | `contactos:escribir` | Crea el contacto o, si ya hay uno con ese teléfono, lo actualiza (lo que viene pisa; lo que no viene se deja). `201` si lo creó, `200` si lo actualizó; `creado` lo dice. Mismos campos que el panel (`nombre`, `documento`, `telefono`, `telefonos`, `email`, `direccion`, `ciudad`, `campos`). |
| `GET /api/v1/leads/{id}` | `leads:leer` | Estado, intentos, próximo intento, disposición (`codigo`, `nombre`, `categoria`) y callbacks pendientes. |
| `GET /api/v1/campanas/{id}/leads?telefono=&cambiados_desde=&despues_de=&limite=` | `leads:leer` | Para sincronizar: `cambiados_desde` (UTC) trae solo los intentados desde esa fecha. Paginación como en llamadas. |
| `POST /api/v1/callbacks` | `callbacks:escribir` | `{"lead_id", "cuando", "agente_id"?, "nota"?}`. `cuando` en ISO 8601 con zona (sin zona se toma UTC), futuro y a no más de 6 meses. El lead vuelve a la cola con prioridad en esa fecha (y solo para ese agente, si se indica). Dispara el webhook `callback.creado`. |

Las fechas van en ISO 8601 (UTC). Errores: `401` clave inválida, revocada o
vencida; `403` falta un permiso o la empresa está desactivada; `402` la
licencia no está vigente (solo al escribir); `404` el recurso no existe o es
de otra empresa; `429` tope de peticiones.

## Webhooks (de NSPBX hacia tu sistema)

Se configuran en **Seguridad → Webhooks hacia tu CRM**. Por cada evento
suscrito, NSPBX hace `POST` a tu URL (https, accesible desde internet) con:

```
Content-Type: application/json
X-NSPBX-Evento: llamada.disposicionada
X-NSPBX-Entrega: 1234
X-NSPBX-Firma: t=1727900000,v1=5f2b…

{"evento": "llamada.disposicionada", "empresa_id": 7, "creado": "2026-10-03T15:04:05Z", "datos": {…}}
```

| Evento | Cuándo | `datos` |
|---|---|---|
| `llamada.contestada` | Un cliente contestó y quedó con un agente | `llamada_uuid`, `campana_id`, `lead_id`, `telefono`, `agente_id` |
| `llamada.disposicionada` | El agente eligió la disposición | lo anterior + `contacto_id`, `disposicion` (`id`, `codigo`, `nombre`, `categoria`), `nota`, `callback_at` |
| `callback.creado` | Se agendó volver a llamar (agente o API) | `lead_id`, `campana_id`, `contacto_id`, `telefono`, `cuando`, `agente_id`, `nota` |
| `lead.no_llamar` | Un número pasó a no llamar (agente o panel) | `telefono`, `motivo`, `origen`, y `lead_id`/`campana_id` si vino de una llamada |

**Verificar la firma.** `v1 = HMAC-SHA256(secreto, t + "." + cuerpo)` en
hexadecimal, sobre el cuerpo tal cual llegó. Compárala en tiempo constante y
rechaza un `t` de más de 5 minutos de diferencia:

```python
import hashlib, hmac, time

def valido(secreto: str, cuerpo: bytes, cabecera: str) -> bool:
    partes = dict(p.split("=", 1) for p in cabecera.split(","))
    if abs(time.time() - int(partes["t"])) > 300:
        return False
    esperado = hmac.new(secreto.encode(), f"{partes['t']}.".encode() + cuerpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, partes.get("v1", ""))
```

Responde `2xx` para confirmar. Si no, se reintenta a los 30 s, 2 min, 10 min,
30 min y 2 h; después queda «fallida» en la bitácora (se puede reintentar a
mano). Un mismo aviso puede llegar dos veces: usa `X-NSPBX-Entrega` para no
procesarlo dos veces. El secreto se ve una sola vez al crear o rotar.

**URL del CRM en la consola del agente.** En cada campaña con agentes se puede
poner una plantilla, p. ej. `https://micrm.com/clientes?tel={telefono}`. La
consola la abre con los datos del lead y le agrega `nspbx_ts` (segundos) y
`nspbx_firma = HMAC-SHA256(secreto de la campaña, URL completa sin
"&nspbx_firma=…")`. El secreto se consulta en el formulario de la campaña.

## Versiones

Un cambio que rompa integraciones existentes va a `/api/v2`. `/api/v1` sigue
respondiendo igual mientras haya integraciones que lo usen.
