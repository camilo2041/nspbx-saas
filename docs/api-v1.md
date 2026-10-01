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

## Endpoints

| Método y ruta | Permiso | Notas |
|---|---|---|
| `GET /api/v1/llamadas?desde=&hasta=&despues_de=&limite=` | `llamadas:leer` | Ordenadas por id. Para paginar, se pasa en `despues_de` el `siguiente` de la respuesta anterior. No incluye grabaciones ni resúmenes. |
| `GET /api/v1/citas?desde=&hasta=&limite=` | `citas:leer` | |
| `POST /api/v1/citas` | `citas:escribir` | Mismo cuerpo que el panel. Responde `409` si el horario está ocupado. |
| `POST /api/v1/campanas/{id}/numeros` | `campanas:escribir` | Mismo cuerpo que el panel (`{"numbers":[{"phone":"…","vars":{…}}]}`). Aplica la política de salientes: los destinos bloqueados vuelven en `bloqueados`. |
| `GET /api/v1/consumo?mes=AAAA-MM` | `consumo:leer` | Ver «Consumo» en docs/seguridad-y-robustez.md. |

Las fechas van en ISO 8601 (UTC). Errores: `401` clave inválida, revocada o
vencida; `403` falta un permiso o la empresa está desactivada; `402` la
licencia no está vigente (solo al escribir); `404` el recurso no existe o es
de otra empresa; `429` tope de peticiones.

## Versiones

Un cambio que rompa integraciones existentes va a `/api/v2`. `/api/v1` sigue
respondiendo igual mientras haya integraciones que lo usen.
