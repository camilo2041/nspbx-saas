# Plan de implementación — Contact center tipo VICIdial

Marcador predictivo con sus derivados: agentes, grabación, supervisor, tiempo
real, CRM y tiempo de ring. Lo que sigue está anclado a lo que NSPBX ya tiene
y a cómo funciona VICIdial por dentro, no a una lista de funciones sueltas.

## 0. De dónde partimos

| Pieza | Hoy | Lo que falta para un contact center |
|---|---|---|
| Marcador (`workers/dialer.py`) | Marca cada número y lo pasa al **voizbot**; concurrencia fija por campaña; topes por empresa, licencia, plataforma, troncal, horario (Ley 2300), destinos bloqueados, cupo diario | No hay agentes humanos en el bucle: ni ritmo por agentes listos, ni nivel de marcación, ni abandono |
| Resultado de la llamada | `esl.bgapi_wait`: una tarea queda esperando cada `originate` | Para predictivo hace falta el flujo de eventos (timbra, contesta, contestador, puente, cuelga), no esperar el resultado de cada orden |
| Colas (`Queue`, mod_callcenter) | Entrantes, estrategia, wrap-up, agentes = extensiones | Estados de agente propios (pausa con código, disposición), mezcla con salientes |
| Usuarios | Roles admin, supervisor, coordinador, asesor; asesor con extensión; softphone WebRTC en panel y app | Sesión de agente (login a campaña), estados, pausas |
| CDR (`CallLog`) | `started_at`, `answered_at`, `ended_at`, `duration`, `billsec`, grabación, resumen IA | Ring time separado, cola, espera en línea, wrap-up; lead, agente y disposición |
| Grabación | `record_session` por llamada, carpeta por empresa, retención por empresa, resumen IA | Control en llamada (pausar, reanudar, enmascarar), búsqueda por lead, agente o campaña |
| CRM | `Debt`, `PaymentPromise`, `Appointment`, `extra_data` por número | Contacto único por empresa, listas, historial, notas, campos propios, screen pop, webhooks |
| Tiempo real | `/ws/logs` (consola), estado de cola a pedido | Bus de eventos por empresa, tablero de agentes y campañas, wallboard |
| Aislamiento | RLS, filtro de la aplicación, matriz de permisos, `sesion_de_empresa` en workers | Todo lo nuevo entra con `tenant_id`, RLS, matriz y pruebas de aislamiento desde el día uno |

FreeSWITCH ya carga `mod_conference`, `mod_callcenter` y `eavesdrop` (en
`mod_dptools`). Para el contestador automático (AMD) hay que agregar
`mod_avmd`.

## 1. Decisión de arquitectura: el agente vive en una conferencia

Esta es la decisión que hace funcionar al predictivo, y es la misma que toma
VICIdial (agente en una sala MeetMe permanente).

```
Agente entra a la campaña
   └─ su softphone (WebRTC o SIP) llama a  agente_<tenant>_<user>  (mod_conference)
      y queda ahí, en silencio, toda la jornada  ← "sesión clavada"

Cliente contesta (humano, tras AMD)
   └─ backend: uuid_transfer <cliente> → conferencia del agente LIBRE
      el agente lo oye al instante: 0 s de timbre al agente
```

Por qué así y no con `mod_callcenter` ni haciendo timbrar al agente:

- **Abandono.** Con predictivo el cliente ya contestó. Si además hay que
  hacer timbrar al agente (3 a 5 s), se pierde el cliente o se pasa el
  límite de abandono. Con la sesión clavada el puente es inmediato.
- **Supervisor.** Escuchar, susurrar e intervenir son flags de la
  conferencia: el supervisor entra sin micrófono (escuchar), entra con
  `relate <sup> <cliente> nohear` (susurrar, el cliente no lo oye) o entra
  normal (intervenir). Se evita reinventar con `eavesdrop` y DTMF.
- **Una sola fuente de verdad.** El estado del agente (listo, en llamada,
  pausado con código, disposición) lo lleva el backend.
  `mod_callcenter` tiene su propio modelo de estados, sin códigos de pausa
  ni disposición, y tener dos fuentes de verdad termina en descuadres.
- **Mezcla entrantes y salientes (blended).** Una entrante de una cola
  marcada «blended» entra a la misma conferencia del agente libre.
  `mod_callcenter` sigue para las colas clásicas sin agentes de campaña.

**Motor de eventos.** Hoy el listener de ESL solo escucha `BACKGROUND_JOB`.
Pasa a escuchar (con filtro por las variables `nspbx_*`):

- `CHANNEL_CREATE`, `CHANNEL_PROGRESS`, `CHANNEL_PROGRESS_MEDIA`
- `CHANNEL_ANSWER`, `CHANNEL_BRIDGE`, `CHANNEL_HOLD`, `CHANNEL_UNHOLD`
- `CHANNEL_HANGUP_COMPLETE`
- `CUSTOM conference::maintenance`
- `CUSTOM avmd::*`

Un solo proceso, el «motor de contact center», mantiene el estado vivo de
agentes y llamadas. Lo persiste en Postgres (tablas `*_vivo` y bitácoras) y
lo publica en un bus en memoria hacia los WebSocket.

**Un solo motor a la vez.** El backend hoy es un proceso. El motor toma un
`pg_advisory_lock` al arrancar: si algún día hay dos backends, solo uno marca.
Multi-servidor (varios FreeSWITCH) queda para la fase 7.

## 2. Modelo de datos

Todas las tablas llevan `tenant_id` NOT NULL con RLS. `test_aislamiento_db.py`
ya falla si una tabla de negocio no las tiene.

### CRM y leads

| Tabla | Para qué |
|---|---|
| `contactos` | Cliente único por empresa: nombres, documento, teléfonos (1..n, con tipo y orden), email, dirección, ciudad, `campos` (JSON validado contra la definición de la empresa), fuente, `no_llamar` |
| `campos_contacto` | Definición de campos propios por empresa: nombre, tipo, obligatorio, opciones, visible para el agente |
| `listas` | Lista de leads: campaña, activa, prioridad, fecha de carga, origen (CSV, API) |
| `leads` | Contacto **en** una lista: estado, prioridad, intentos, `ultimo_intento`, `proximo_intento`, dueño (agente para callbacks propios), última disposición, teléfono que toca |
| `notas` | Notas del agente sobre el contacto (con llamada y agente) |
| `no_llamar` | DNC por empresa y por plataforma: teléfono, motivo, desde, hasta |

`Debt`, `PaymentPromise` y `Appointment` pasan a colgar del contacto
(`contacto_id` nullable al principio). `CampaignNumber` se migra a
contacto + lista + lead, con una migración que conserva ids y estados. Las
campañas de voizbot siguen funcionando igual, ahora sobre leads.

### Campaña (columnas nuevas en `campaigns`)

| Grupo | Campos |
|---|---|
| Método | `metodo`: `voizbot` (lo de hoy), `difusion`, `manual`, `vista_previa`, `progresivo`, `proporcional`, `predictivo` |
| Ritmo | `nivel_marcacion` (decimal), `nivel_max`, `adaptativo` (bool), `abandono_objetivo_pct` (3,0 por defecto), `modo_adaptativo` (`solo_abandono`, `equilibrado`, `agresivo`) |
| Tiempos | `timeout_marcado` (s de timbre al cliente), `temporizador_abandono` (s que espera un cliente contestado antes de declararlo abandonado; 2 por defecto) |
| Abandono | `mensaje_abandono` (audio o voizbot), destino: colgar, cola o voizbot |
| AMD | `amd`: apagado, `avmd` o `ia`; `amd_accion`: colgar, dejar mensaje, pasar al voizbot |
| Hopper | `hopper_nivel` (cuántos leads tener listos), orden (`prioridad`, `antiguo`, `nuevo`, `aleatorio`, por zona horaria), filtro SQL seguro (constructor de filtros, no SQL libre) |
| Reciclaje | `reglas_reciclaje` JSON: por disposición, cada cuánto y cuántas veces (p. ej. NO CONTESTA cada 2 h, máx. 3/día) |
| Identificador de llamada | troncal, CID fijo, por lista o rotativo por área |
| Agentes | `campana_agentes` (usuario, rango o prioridad), colas mezcladas (blended) |
| Agente | `guion` (texto con `{variables}`), `url_crm` (plantilla firmada), disposiciones permitidas, grabación (todas, ninguna, a pedido) |

### Agentes y tiempo

| Tabla | Para qué |
|---|---|
| `codigos_pausa` | Por empresa: código, nombre, pagada, máximo de minutos, activo. Semilla: BREAK, LUNCH, TRAINING, MEETING, ADMIN, TECHNICAL, PERSONAL |
| `disposiciones` | Por empresa (y por campaña opcional): código, nombre, categoría (`venta`, `contacto`, `no_contacto`, `no_llamar`, `callback`, `promesa`), final o no, cuenta como contacto humano, color. Semilla: VENTA, NO_INTERESADO, CALLBACK, NO_CONTESTA, OCUPADO, EQUIVOCADO, POTENCIAL, RECHAZADO, SEGUIMIENTO, NO_LLAMAR, PROMESA_PAGO |
| `sesiones_agente` | Login y logout del agente: campaña(s), extensión, softphone, IP, inicio, fin, motivo de salida (normal, forzada, caída) |
| `estados_agente` | **Bitácora**: una fila por tramo de estado (`LISTO`, `PAUSA`, `TIMBRANDO`, `EN_LLAMADA`, `DISPO`, `MUERTO`), con código de pausa, llamada, inicio y fin. Todos los tiempos del agente salen de acá |
| `agentes_vivo` | Una fila por agente conectado: estado actual, desde cuándo, llamada, lead y campaña actuales. La lee el tiempo real |
| `callbacks` | Lead, campaña, `agente_id` (NULL = cualquier agente), fecha y hora, zona horaria, estado, nota, recordatorio enviado |

### Llamada (columnas nuevas en `call_logs`)

| Columna | Origen |
|---|---|
| `lead_id`, `contacto_id`, `agente_id`, `disposicion_id`, `sesion_agente_id` | Variables `nspbx_*` que el motor pone en el canal |
| `progress_at`, `progress_media_at` | `progress_uepoch`, `progress_media_uepoch` del CDR |
| `ring_ms` | `answer` − `progress` (sin progress: `answer` − `start`) |
| `setup_ms` | `progress` − `start` (lo que tarda la red en dar timbre; sirve para medir la troncal) |
| `cola_ms` | Desde que el cliente contesta hasta que llega a un agente |
| `espera_ms` | Tiempo en espera (hold), de `hold_accum_seconds` |
| `amd_resultado` | `humano`, `maquina`, `incierto` o `apagado` |
| `abandonada` | El cliente contestó y no hubo agente dentro del temporizador |
| `dispo_ms` | Tiempo del agente en disposición tras colgar |
| `colgo` | Quién colgó: cliente, agente o sistema (`sip_hangup_disposition`) |

Ninguna de estas va dentro de `duration`, que queda como está. Cada tiempo es
su propia columna, como pide el documento de referencia.

## 3. Motor de marcación

### Métodos

| Método | Qué hace | Cuántas llamadas lanza |
|---|---|---|
| `voizbot` | Lo de hoy | `max_concurrency` |
| `difusion` | Mensaje grabado o voizbot, sin agentes | `max_concurrency` |
| `manual` | El agente escribe o elige el número | 1, cuando el agente lo pide |
| `vista_previa` | El motor le muestra el siguiente lead al agente; el agente marca (o se marca solo a los N s) | 1 por agente que acepta |
| `progresivo` | Marca cuando hay un agente listo | `listos` − `timbrando` |
| `proporcional` | Proporción fija | `ceil(listos × nivel)` − `timbrando` |
| `predictivo` | Nivel que se ajusta solo | Ver abajo |

Blended entra en todos: una entrante de cola blended tiene prioridad sobre la
saliente siguiente, y el agente que la toma deja de contar como listo.

### Hopper

Es una tabla, `hopper`, con `SELECT … FOR UPDATE SKIP LOCKED` para que el
motor no tome dos veces el mismo lead. Cada 5 s se rellena hasta
`hopper_nivel × agentes listos`, respetando:

- reglas de reciclaje y `proximo_intento`
- DNC de la empresa y de la plataforma
- horario de marcación (`horario_marcacion`) y la zona horaria del lead
- callbacks vencidos primero
- prioridad de la lista

### Cálculo del predictivo (cada segundo, por campaña)

```
p          = tasa de contacto humano  (contestadas humanas / intentos)
             ventana móvil de 15 min, con suavizado bayesiano si hay < 50 intentos
listos     = agentes LISTO
pronto     = agentes EN_LLAMADA con tiempo hablado ≥ (AHT − ring medio)  ← VICIdial
efectivos  = listos + factor_pronto × pronto
a_lanzar   = ceil(efectivos × nivel) − llamadas_timbrando − clientes_en_espera
             recortado por: max_concurrency, tope de la empresa, tope de la
             licencia, tope global, CPS de la troncal, cupo diario
```

**Nivel adaptativo**, un controlador con dos lazos:

1. **Abandono.** Si la tasa de abandono (acumulada del día y móvil de 15 min)
   supera el objetivo, el nivel baja con fuerza (×0,8). Este lazo siempre
   gana.
2. **Espera del agente.** Si el abandono está bajo el objetivo y la espera
   promedio de los agentes entre llamadas pasa de X s, el nivel sube de a poco
   (+0,1).

El nivel se mantiene entre 1,0 y `nivel_max`.

Al arrancar una campaña sin historial, el nivel empieza en 1,0 (progresivo) y
sube con los datos.

### Abandono (drop)

El cliente contestó (humano) y no hay agente libre dentro de
`temporizador_abandono`:

1. Se reproduce el mensaje de abandono: quién llama y que volverán a
   llamar.
2. Se cuelga o se pasa al voizbot.
3. Se marca `abandonada = true`.
4. El lead se recicla con prioridad.

La tasa de abandono del día por campaña va en tiempo real y en el reporte de
cumplimiento.

### AMD

- `avmd`: detecta el pitido del buzón (`mod_avmd`). Es barato, pero solo
  detecta el pitido.
- `ia`: se transcriben los primeros 2 a 3 s con Deepgram, que ya está
  integrado, y se clasifican:
  - saludo humano corto
  - mensaje de buzón ("deje su mensaje")
  - operador ("el número que usted marcó…")
  - silencio

  Esta opción conviene en Colombia, donde los buzones y los mensajes del
  operador son en español y el pitido no siempre llega.
- El resultado se guarda siempre, para medir falsos positivos (un humano
  colgado como máquina) con una muestra que el supervisor escucha.

## 4. Agentes

### Estados (máquina en el motor)

```
LOGOUT ─login→ LISTO ⇄ PAUSA(código)
                 │
     (cliente asignado)
                 ↓
            EN_LLAMADA ─cuelga→ DISPO ─guarda→ LISTO | PAUSA
                 │
       (la otra parte colgó y el agente sigue)  → MUERTO
```

`TIMBRANDO` solo existe en `manual` y `vista_previa` (el agente oye el timbre
del cliente). `COLA` es el estado del **cliente**, no del agente.

Cada transición:

- cierra el tramo abierto en `estados_agente` y abre el nuevo
- actualiza `agentes_vivo`
- se publica en el bus

### Consola del agente (panel web, `/agente`)

- Login a campaña(s), con el softphone del panel (WebRTC ya existe) o un
  teléfono SIP.
- Barra de estado con cronómetro, botón de pausa con código y salida.
- **Screen pop**:
  - ficha del contacto
  - campos propios
  - historial (llamadas, disposiciones, notas, callbacks, deudas, promesas, citas)
  - guion con variables
  - botón para abrir el CRM externo (URL firmada)
- Controles de llamada:
  - colgar y espera (hold)
  - transferir: ciega, consultada, o a cola/voizbot
  - marcar el segundo teléfono del contacto
  - grabación: pausar, reanudar y enmascarar para datos de tarjeta
- Formulario de disposición obligatorio, con callback (propio o de
  cualquiera, fecha, hora y nota), promesa de pago (`PaymentPromise`, que
  ya existe), nota y "no llamar".
- Vista previa: tarjeta del lead con "Marcar" y "Saltar" (la omisión queda
  registrada).

La app móvil **no** lleva consola de agente en las primeras fases (el puesto
de agente es web). Sí lleva supervisor y wallboard (fase 5).

### Permisos nuevos (entran a `docs/matriz-permisos.md`)

| Permiso | Admin | Supervisor | Coordinador | Asesor |
|---|---|---|---|---|
| `agente:operar` | ✔ | ✔ | ✔ | ✔ |
| `crm:ver` | ✔ | ✔ | ✔ | ✔ (los leads que le tocan) |
| `crm:gestionar` (importar, campos, DNC) | ✔ | ✔ | ✔ | |
| `supervision:ver` (tiempo real, wallboard) | ✔ | ✔ | ✔ | |
| `supervision:intervenir` (escuchar, susurrar, intervenir, forzar pausa o salida) | ✔ | ✔ | | |
| `reportes:ver` | ✔ | ✔ | ✔ | |

## 5. Grabación

Ya existe la grabación por llamada, la carpeta por empresa, la retención y el
resumen. Se agrega:

- Asociación en `call_logs`: lead, contacto, agente, campaña y disposición.
  Se busca por cualquiera de ellos.
- Política por campaña: todas, ninguna, o solo a pedido (el agente la
  inicia).
- Control en llamada: `uuid_record start|stop|mask|unmask`. `mask` pone
  silencio mientras se dictan datos sensibles, y la pausa queda registrada.
- Las grabaciones de conferencia (agente + cliente + supervisor) se graban
  sobre el canal del cliente, no sobre la sala, para que la grabación sea por
  llamada.
- Aviso legal al inicio, por campaña, para el consentimiento (Ley 1581 de
  habeas data).
- Escuchar o descargar queda en la auditoría (ya existe `AuditLog`).

## 6. Supervisor y tiempo real

### Bus de eventos

Lo publica el motor en memoria y lo sirve un WebSocket `/ws/tiempo-real`:

- token como el de `/ws/logs`
- **filtrado por empresa** en el servidor
- prueba de aislamiento como las de hoy

Mensajes: `agente.estado`, `llamada.timbra`, `llamada.contesta`,
`llamada.abandona`, `llamada.cuelga` y `campana.metricas` (cada 2 s).

### Pantallas

- **Agentes en vivo**: agente, estado, tiempo en el estado, campaña,
  número del cliente, lead, ring y hablado de la llamada actual, código de
  pausa. Filtros por campaña y estado; colores por umbral (pausa > máximo
  del código).
- **Campañas en vivo**:
  - agentes conectados, listos, en pausa y en llamada
  - llamadas timbrando y clientes en espera
  - contestadas, abandonadas, nivel de marcación actual, hopper
  - tasa de contacto, tasa de abandono (hoy y 15 min), ring medio y AHT
- **Acciones**:
  - escuchar, susurrar e intervenir (conferencia; ver §1)
  - forzar pausa, forzar salida
  - cambiar el nivel de marcación en caliente
  - pausar la campaña

  Todas quedan en la auditoría con quién, a quién y cuándo.
- **Wallboard** `/wallboard`: pantalla completa para sala de operaciones,
  números grandes, se actualiza sola. Se puede abrir con un token de solo
  lectura que vence (para una TV sin sesión de usuario).

## 7. CRM e integraciones

- **Importar**: CSV con mapeo de columnas a campos (los propios incluidos),
  deduplicación por teléfono o documento, validación de teléfonos, reporte de
  errores.
- **Ficha del contacto** en el panel: datos, historial unificado, notas,
  callbacks, grabaciones, deudas, promesas y citas.
- **Screen pop en entrantes**: el caller ID se busca en `contactos`; si hay
  coincidencia, se abre la ficha al agente que atiende.
- **CRM externo, de salida**: webhooks firmados (HMAC) en
  `llamada.contestada`, `llamada.disposicionada`, `callback.creado` y
  `lead.no_llamar`. Con reintentos y bitácora.
- **CRM externo, de entrada**: `/api/v1` (con claves que ya existen) para
  crear y actualizar leads y contactos, consultar estado y disposición, y
  agendar callbacks.
- **URL del CRM en la consola**: plantilla por campaña con variables del
  lead, firmada para que el CRM pueda verificar que el enlace viene de NSPBX.

## 8. Métricas y reportes

Todo sale de tres fuentes: `estados_agente` (tiempo del agente), `call_logs`
(tiempos de la llamada) y el motor (nivel y hopper).

| Grupo | Métricas |
|---|---|
| Predictivo | intentos, contestadas humanas, máquinas (AMD), ocupado, no contesta, fallidas, abandonadas; tasas de contacto, conexión, abandono, AMD, ocupado y no contesta; nivel medio; llamadas/hora; leads/hora |
| Llamada | setup, ring, cola, hablado, espera (hold), disposición, total; quién colgó |
| Agente | login, listo, pausa (por código: inicio, fin, cantidad, total, promedio), timbrando, en llamada (entrante y saliente), disposición (ACW), muerto; AHT; ocupación = (hablado + ACW) / (login − pausa); utilización = (hablado + ACW) / login; llamadas/hora |
| Resultado | disposiciones por campaña, agente y lista; conversión (ventas y promesas / contactos); callbacks cumplidos |
| Cumplimiento | abandono por día y campaña frente al objetivo; llamadas fuera de horario (debería ser 0); intentos por contacto por semana (Ley 2300 en cobranza) |

Los reportes son por rango, campaña, agente y lista, con exportación CSV y
programados por correo (fase 6).

## 9. Fases

Cada fase se puede usar sola, entra con pruebas (incluido el aislamiento
entre empresas y la matriz de permisos) y no rompe las campañas de voizbot
actuales.

| Fase | Qué entra | Cuándo está lista |
|---|---|---|
| **1. Eventos y tiempo de ring** ✅ | Listener ESL con los eventos de canal (`services/tiempo_real.py`); columnas nuevas de `call_logs` (`progress_at`, `setup_ms`, `ring_ms`, `espera_ms`, `colgo`; revisión 0011, `services/tiempos_llamada.py`); bus por empresa y `/ws/tiempo-real`; ring y promedios en el historial, el inicio y la app; «Llamadas en vivo» en el panel | `test_tiempo_real.py`: tiempos de cada forma de CDR, promedios, cada empresa recibe solo sus canales (por variable, dominio o contexto), ciclo completo de una llamada, socket que exige permiso y sesión vigente. Pendiente: probar con CDRs reales de FreeSWITCH en el ambiente local |
| **2. CRM base y leads** | `contactos`, campos propios, `listas`, `leads`, `notas`, DNC; migración de `CampaignNumber`; importación CSV; ficha del contacto; hopper con reciclaje y DNC (el voizbot ya lo usa) | Las campañas de voizbot siguen igual sobre leads; reciclaje y DNC probados |
| **3. Agentes: manual, vista previa y progresivo** | Sesión clavada en conferencia; motor de estados; códigos de pausa; disposiciones; callbacks; consola del agente con screen pop y guion; grabación asociada; métodos manual, vista previa y progresivo | Un agente entra, recibe clientes uno a uno sin timbre propio, dispone, pausa y sale; la bitácora suma exacto el tiempo de login |
| **4. Predictivo** | Proporcional y predictivo; nivel adaptativo; temporizador y mensaje de abandono; AMD (`avmd` y luego `ia`); blended con colas | Simulación: con tasa de contacto y AHT sintéticos el abandono se mantiene bajo el objetivo y la espera del agente baja frente al progresivo. Después, piloto con una campaña real |
| **5. Supervisor y wallboard** | Agentes y campañas en vivo; escuchar, susurrar e intervenir; forzar pausa y salida; nivel en caliente; wallboard; supervisor en la app móvil | Cada acción probada con dos llamadas reales en el ambiente local; auditoría de cada intervención |
| **6. Reportes e integración CRM** | Reportes de agente, campaña, disposición y cumplimiento; CSV; webhooks firmados; `/api/v1` de leads y callbacks; reportes programados | Las cifras cuadran con la bitácora en pruebas con datos sembrados |
| **7. Escala** | Varios FreeSWITCH (multi-servidor), motor con líder por `advisory lock`, partición de `estados_agente` y `call_logs` por mes | Prueba de carga con el objetivo de agentes simultáneos que se defina |

**Orden recomendado: 1 → 2 → 3 → 4 → 5 → 6 → 7.**

- La fase 1 da valor inmediato (tiempo de ring en todo el sistema) y es la
  base de todo lo demás.
- El predictivo (4) no puede ir antes de la 3: sin la sesión clavada y la
  máquina de estados del agente no hay nada que pronosticar.

## 10. Simulador del predictivo (parte de la fase 4)

Antes de marcar a gente real, el motor corre contra un simulador:

- **Agentes virtuales** con AHT y ACW de una distribución.
- **Clientes virtuales** con tasa de contacto, de AMD y de ring variables.

Se reportan abandono, espera del agente y llamadas por hora. Sirve para:

- ajustar el controlador sin quemar listas
- tener una prueba automática en CI: con estos parámetros el abandono no
  pasa del 3 %

## 11. Riesgos y cómo se cubren

| Riesgo | Cobertura |
|---|---|
| Abandono alto (molestia, reclamos, cumplimiento) | El lazo de abandono gana siempre; se arranca en progresivo; tope duro de nivel; alerta (ya existe `alertas`) si el abandono del día pasa el objetivo |
| AMD que cuelga a humanos | Empezar con AMD apagado o solo `avmd`; medir con muestras escuchadas; `ia` después |
| Ley 2300 (cobranza): horario y frecuencia de contacto | El horario ya está; se agrega el tope de intentos por contacto por semana en el reciclaje y el reporte de cumplimiento. Confirmar las cifras exactas con el abogado antes del piloto |
| Ley 1581 (habeas data): grabaciones y CRM | Aviso de grabación; retención por empresa (ya existe); auditoría de acceso; DNC respetado en todos los métodos |
| Softphone WebRTC inestable en el puesto del agente | La sesión clavada se reconecta sola; si cae, el agente pasa a `MUERTO`/pausa técnica y no recibe clientes; TURN ya está |
| Capacidad de FreeSWITCH y de la troncal (CPS) | Topes que ya existen (empresa, licencia, plataforma, CPS); el predictivo los respeta; prueba de carga en la fase 7 |
| Un solo proceso de backend | Advisory lock; el motor se puede separar a su propio contenedor sin cambiar el modelo |

## 12. Lo que necesito de ustedes antes de la fase 3

- Cuántos agentes simultáneos esperan por empresa, al inicio y al año.
- Qué disposiciones y códigos de pausa usan hoy (si no, quedan las de la semilla).
- Qué CRM externo hay que integrar primero (y si tiene API o webhooks).
- Objetivo de abandono que quieren usar (3 % por defecto) y si la operación
  es solo cobranza o también ventas (cambia las reglas de contacto).
