# Seguridad y robustez de NSPBX

Este documento es la referencia de seguridad, aislamiento y operación de
NSPBX (PBX SaaS multiempresa con voizbot). Complementa a
[`arquitectura-multitenant.md`](arquitectura-multitenant.md), que explica
*cómo* se aíslan las empresas; este explica *qué* tiene que ser cierto
para confiar en el sistema y *cómo se comprueba*.

## 0. Qué significa "confianza" aquí

Ningún sistema es invulnerable, y un documento que lo prometa no da
confianza: la quita. La confianza sale de tres cosas, y este documento
está organizado alrededor de ellas:

1. **Invariantes explícitas.** Una lista corta de cosas que *nunca* pueden
   pasar (sección 2). Todo lo demás existe para sostenerlas.
2. **Evidencia, no intención.** Cada control dice dónde está en el código
   y cómo se verifica. Un control sin prueba automática es una promesa.
3. **Daño acotado.** Se asume que algo *va* a fallar —una contraseña SIP
   filtrada, un endpoint sin filtro, un prompt manipulado— y se diseña
   para que el daño quede limitado en alcance (una empresa), en tiempo
   (minutos, no días) y en dinero (un tope, no la factura del carrier).

### Cómo leer los estados

| Marca | Significa |
|---|---|
| ✅ | Implementado **y** cubierto por una prueba automática que corre en CI |
| 🟢 | Implementado, pero sin prueba automática: puede romperse sin que nadie lo note |
| 🟡 | Parcial: cubre una parte del riesgo |
| ❌ | No existe |

Hoy el repositorio no tiene pruebas automáticas ni CI, así que **ningún
control está en ✅**. Ese es el hueco más importante del sistema y la
razón por la que la fase 0 de la hoja de ruta (sección 8) es verificar,
no construir.

El estado se revisó contra el código el 2026-10-01. Al cambiar un control,
se actualiza su fila en el mismo commit.

---

## 1. Sistema real

```
                  Internet
                     │
     ┌───────────────┼─────────────────────────────┬──────────────────┐
     │ HTTPS :443    │ SIP :5060 udp/tcp            │ WSS :8443         │ RTP 16384-16584/udp
     ▼               ▼                              ▼                   ▼
 ┌────────┐     ┌──────────────────────────────────────────────────────────┐
 │Traefik │     │                  FreeSWITCH 1.10                          │
 │  TLS   │     │  mod_sofia · mod_xml_curl · mod_callcenter · ESL :8021    │
 └───┬────┘     └──────┬───────────────────────────────┬──────────────────┘
     │                 │ xml_curl (?secret=)            │ ESL (red interna)
     │                 ▼                               ▼
     │          ┌──────────────────────────────┐  ┌─────────────────────┐
     ├─────────►│ backend FastAPI              │  │ voicebot            │
     │  /api    │ API · /fs/* · dialer · ws    │  │ STT · LLM · TTS     │
     │          └──────────────┬───────────────┘  │ tools con tenant_id │
     ▼                         │                  └──────────┬──────────┘
 ┌────────┐                    ▼                             │
 │Next.js │            ┌──────────────┐   rol nspbx_app      │
 │ panel  │            │ PostgreSQL 16│◄──── (RLS) ──────────┘
 └────────┘            └──────────────┘   rol dueño solo login/bot
                     disco: grabaciones · respaldos · audios de bots
                     externos: carriers SIP · Deepgram · ElevenLabs · LLM
```

**Fronteras de confianza** (donde un dato cambia de dueño y hay que
validarlo):

| Frontera | Qué la cruza | Quién valida |
|---|---|---|
| Internet → Traefik → API | peticiones HTTP del panel, widget de llamada web | token + RBAC + RLS |
| Internet → FreeSWITCH | REGISTER/INVITE de teléfonos, scanners, carriers | digest SIP, fail2ban, ACL, dialplan |
| FreeSWITCH → backend `/fs/*` | pedidos de directorio y dialplan | secreto compartido (`FS_XML_SECRET`) |
| Llamante → voizbot → herramientas | lo que dice una persona al teléfono | código de la herramienta, nunca el modelo |
| backend → proveedores de IA | texto de la conversación, claves API | TLS, claves por variable/DB |
| Empresa → empresa | — | **no debe existir ningún cruce** (invariantes I1–I4) |

Componentes que el documento genérico suele omitir y aquí importan:

- **El voizbot usa la sesión dueña de Postgres (sin RLS)** porque atiende
  a varias empresas en el mismo proceso. Su aislamiento depende de que
  cada herramienta filtre por `tenant_id` explícito
  (`services/ai_agent.py:_run_tool`). Es el punto más delicado del
  aislamiento y por eso tiene su propia invariante (I4).
- **El login** también lee `users` sin RLS (no se sabe la empresa hasta
  leer la fila). La empresa viaja luego firmada en el token.
- **El contexto `public` del dialplan** es el único lugar donde el ruteo
  cruza empresas (DID → contexto del tenant).

---

## 2. Invariantes

Si alguna de estas deja de ser cierta, es un incidente de severidad 1
aunque nadie se haya dado cuenta. Cada una necesita al menos una prueba
automática (sección 7).

| # | Invariante | Capas que la sostienen |
|---|---|---|
| I1 | Un usuario de la empresa A nunca lee, crea, modifica ni borra datos de la empresa B. | filtro en la consulta → RLS (`USING` + `WITH CHECK`) → rol `nspbx_app` sin `BYPASSRLS` |
| I2 | Una llamada de la empresa A nunca termina en una extensión, cola, bot o troncal de la empresa B. | dominio SIP + contexto `ctx_t<id>` por empresa, gateways con prefijo |
| I3 | Una grabación de A nunca se entrega a alguien de B, ni a nadie sin `llamadas:ver`. | descarga solo por API con `_traer()` + RLS; carpeta no servida estáticamente |
| I4 | El voizbot de A nunca lee ni escribe datos de B, y nunca ejecuta una acción que el llamante no podría pedir. | herramientas con `tenant_id` explícito; autorización en código, no en el prompt |
| I5 | Nadie hace llamadas salientes que la empresa no autorizó explícitamente (destino, horario, volumen, gasto). | internacional bloqueado por defecto, topes de concurrencia, duración y gasto |
| I6 | Un administrador de empresa no puede afectar a otras empresas ni a la plataforma. | `core/alcance.py` (operaciones globales solo para el rol plataforma) |
| I7 | Ningún secreto (contraseñas SIP, claves API, ESL, tokens) está en Git ni en los logs. | `.env` obligatorio con `:?`, revisión de logs, escaneo de secretos en CI |
| I8 | Ante la duda, se niega. Un error en autorización, en resolver la empresa o en leer la licencia termina en 401/403/404, nunca en acceso. | `sesion_obligatoria` como lista de exclusión, RLS que devuelve vacío |

---

## 3. Modelo de amenazas

Quién ataca, qué busca y qué lo detiene. Sirve para decidir prioridades:
un control que no frena a ningún actor de esta tabla puede esperar.

| Actor | Objetivo típico | Probabilidad | Impacto | Controles principales |
|---|---|---|---|---|
| **Scanner SIP de Internet** (sipvicious, friendly-scanner) | adivinar contraseñas de extensiones y llamar al exterior | **muy alta** (llega en horas) | **muy alto**: miles de USD en una noche | contraseñas SIP fuertes, fail2ban, internacional bloqueado, topes de gasto (§5.6) |
| **Bot web / fuerza bruta** | entrar al panel | alta | alto | límite de intentos por IP+usuario, MFA para admins |
| **Usuario legítimo de una empresa** curioseando | ver datos de otra empresa cambiando IDs (IDOR) | media | **crítico** (fin del negocio SaaS) | RLS + filtro + pruebas de aislamiento |
| **Admin de empresa** malicioso o descuidado | tocar ajustes globales, saltar topes de su plan | media | alto | `alcance.py`, licencias, cuotas |
| **Credencial robada** (token, contraseña, API key) | lo mismo que su dueño, sin que se note | media | alto, acotado a su empresa | expiración corta, revocación, MFA, auditoría, alertas de anomalía |
| **Llamante al voizbot** | manipular al bot (prompt injection) para obtener datos o acciones | media | medio | herramientas con autorización propia, sin SQL ni datos de otros clientes en el contexto |
| **Carrier / webhook falsificado** | inyectar eventos de llamadas o pagos | baja | medio | firma de webhooks, IP permitidas por troncal |
| **Servidor comprometido** (SSH, dependencia vulnerable) | todo | baja | **total** | mínimo expuesto, contenedores sin root, respaldos off-site cifrados con clave fuera del servidor |
| **Fallo propio** (despliegue roto, disco lleno, migración mala) | — | **alta** | alto | CI, staging, healthchecks, respaldo antes de migrar, rollback |

La lectura importante: **el ataque más probable y más caro es el fraude
telefónico**, no el robo de datos. Ese es el primer frente.

---

## 4. Principios de diseño

- **Cerrado por defecto.** Una ruta nueva nace protegida
  (`sesion_obligatoria` es lista de exclusión), una empresa nueva nace sin
  internacional, una tabla nueva con `tenant_id` nace con RLS.
- **Dos capas independientes para lo crítico.** El aislamiento no depende
  de que la consulta esté bien escrita (RLS) ni de que el dialplan esté
  bien generado (contextos separados).
- **La seguridad no vive en el prompt ni en el frontend.** Lo que el
  modelo o el navegador digan es una *petición*; el backend decide.
- **Topes en todo lo que cuesta dinero o capacidad.** Minutos, canales,
  tokens, almacenamiento, peticiones. Un tope es una alarma que además
  frena.
- **Las fallas silenciosas son las peores.** Un control que falla debe
  hacerlo con ruido: el arranque se niega si falta un secreto, el
  respaldo off-site se niega a subir un volcado viejo.
- **Todo control tiene una prueba.** Si no se puede probar, se documenta
  por qué y cómo se revisa a mano.

---

## 5. Controles por dominio

Formato: **requisito** · estado · dónde está · cómo se verifica.

### 5.1 Aislamiento entre empresas

| Requisito | Estado | Evidencia | Verificación |
|---|---|---|---|
| `tenant_id` no nulo en toda tabla de negocio | 🟢 | `models/models.py` (`_tenant_fk`) | prueba que recorre el metadata y falla si una tabla de negocio no lo tiene |
| RLS con `USING` y `WITH CHECK` en esas tablas | 🟢 | `main.py:_parches_rls` | prueba: con el filtro de la app quitado, RLS igual devuelve 0 filas ajenas |
| La app conecta con `nspbx_app`, sin `SUPERUSER` ni `BYPASSRLS` | 🟢 | `main.py:370`, `core/database.py` | el arranque lo verifica; falta que **se niegue a arrancar** en producción si `DATABASE_URL_APP` falta (hoy solo avisa) |
| `SET LOCAL app.tenant_id` sobrevive a varios commits | 🟢 | `after_begin` en `core/database.py` | prueba: endpoint con dos transacciones devuelve datos en la segunda |
| `tenant_id` nunca se toma del cliente | 🟢 | sale del token firmado | prueba: enviar `tenant_id` ajeno en el body no tiene efecto |
| Directorio y dialplan de FreeSWITCH por dominio/contexto | 🟢 | `services/xml_endpoints.py`, `config_generator.py` | prueba: dos empresas con extensión 1000, cada dominio ve solo la suya |
| Entrantes: DID → empresa | 🟢 | contexto `public` | prueba: DID de A nunca rutea a contexto de B; DID sin dueño se rechaza |
| Gateways con prefijo por empresa | 🟢 | `services/gateways.py` | prueba de nombres |
| WebSocket de logs/eventos filtrado por empresa | 🟢 | `api/logs_ws.py` fija tenant; consola FS solo operador global | prueba: suscriptor de A no recibe eventos de B |
| Workers (dialer, mantenimiento) conservan la empresa | 🟡 | `workers/dialer.py` | revisar que cada consulta del worker fije tenant o filtre explícito; prueba |
| Herramientas del voizbot filtran por `tenant_id` (sesión sin RLS) | 🟡 | `services/ai_agent.py:_run_tool` | **lint/prueba que falle si una consulta en `_run_tool` no menciona `tenant_id`**; a futuro, darle al bot su propia sesión con RLS por llamada |
| Caché / almacenamiento de archivos por empresa | 🟡 | grabaciones en carpetas por fecha, no por empresa | mover a `recordings/t<id>/...` para que el aislamiento también sea físico y la retención por empresa sea trivial |

### 5.2 Identidad y sesiones

| Requisito | Estado | Evidencia | Verificación |
|---|---|---|---|
| Hash de contraseñas fuerte | 🟢 | PBKDF2-SHA256 (`core/security.py`) | revisar iteraciones ≥ 600 000 (recomendación OWASP actual); migrar a Argon2id al próximo login |
| Token de acceso corto + refresh token rotado y hasheado | 🟢 | `crear_token`, `RefreshToken` | prueba: refresh reutilizado invalida la familia |
| Revocación de sesiones | 🟢 | `services/sesiones.py` | prueba: tras cambiar contraseña o desactivar usuario, el token viejo da 401 |
| Límite de intentos de login por IP y por usuario | 🟢 | `core/limitador.py` (en memoria) | prueba; pasa a Redis el día que haya más de un proceso |
| IP real detrás del proxy, no falsificable | 🟢 | `ip_cliente()` | prueba con `X-Forwarded-For` inventado |
| `AUTH_SECRET` obligatorio en producción | 🟡 | hoy tiene valor vacío por defecto y genera uno al azar | que el arranque **falle** sin él en producción |
| MFA (TOTP) | ❌ | — | obligatorio para `plataforma` y `admin`; opcional para el resto |
| Recuperación de contraseña segura | ❌/por verificar | — | token de un solo uso, 15 min, no revela si el correo existe |
| Lista de sesiones/dispositivos visible al usuario | ❌ | — | — |

### 5.3 Autorización (RBAC)

| Requisito | Estado | Evidencia | Verificación |
|---|---|---|---|
| Permisos granulares, no `if rol == "admin"` | 🟢 | `core/permissions.py`, overrides por empresa | — |
| Toda ruta bajo `/api/` exige sesión salvo lista explícita | 🟢 | `core/auth.py:_es_abierta` | prueba que enumera `app.routes` y falla si una ruta nueva no declara permiso ni está en la lista abierta |
| Operaciones globales separadas de las de empresa | 🟢 | `core/alcance.py` | prueba con dos empresas: admin de empresa recibe 403 |
| Licencia suspendida bloquea operación | 🟢 | `licencia_operativa()` | prueba |
| Matriz rol × endpoint documentada y probada | ❌ | — | generar la matriz desde el código y probarla en CI |

### 5.4 API

| Requisito | Estado | Evidencia | Verificación |
|---|---|---|---|
| Validación de entradas (teléfonos, nombres, XML, rutas de audio) | 🟢 | `core/validacion.py`, Pydantic | pruebas con inyección en dialplan/XML (`limpiar_xml`, `TELEFONO_RE`) |
| CORS abierto **sin credenciales**, token en cabecera | 🟢 | `main.py:576` | prueba de que no hay cookies de sesión |
| Sin stack traces en producción | por verificar | — | prueba: error 500 devuelve mensaje genérico + `request_id` |
| `request_id` en cada petición y en cada log | ❌ | — | middleware que lo genere/propague y lo devuelva en cabecera |
| Cabeceras de seguridad (CSP, HSTS, X-Frame-Options, Referrer-Policy) | ❌ | `next.config.ts` y Traefik sin ellas | middleware de Traefik + `headers()` en Next |
| Límite de peticiones por usuario/empresa (no solo login) | 🟡 | `limitar_uso` en endpoints puntuales | límite general por token y por empresa |
| Idempotencia en operaciones críticas (iniciar campaña, cobros) | ❌ | — | cabecera `Idempotency-Key` |
| Webhooks firmados (HMAC + timestamp + tolerancia de 5 min) | 🟡 | `agent_webhook_secret`, `core/firmas.py` | prueba de firma inválida y de repetición |
| API keys por empresa con scopes y expiración | ❌ | — | cuando exista API pública: hash en DB, prefijo visible, scopes, revocación |
| Versionado `/api/v1` | ❌ | — | antes de abrir API a terceros |

### 5.5 FreeSWITCH y SIP

| Requisito | Estado | Evidencia | Verificación |
|---|---|---|---|
| ESL no publicado; contraseña obligatoria y distinta de `ClueCon` | 🟢 | `docker-compose.yml`, `FS_ESL_PASSWORD:?` | `scripts/verificar.sh`; prueba de que el puerto 8021 no responde desde fuera |
| `mod_xml_curl` con secreto compartido | 🟢 | `verificar_secreto_fs` | prueba: `/fs/*` sin secreto da 401 |
| WS/WSS de desarrollo solo en loopback | 🟢 | `127.0.0.1:5066` | escaneo de puertos externo |
| fail2ban para registro fallido y escaneo | 🟢 | `deploy/fail2ban/` | prueba con sipvicious contra staging: la IP queda bloqueada en < 1 min |
| Rango RTP acotado | 🟢 | `16384-16584/udp` | — |
| Contraseñas SIP fuertes y generadas por el sistema | por verificar | — | el backend rechaza contraseñas < 16 caracteres o sacadas de diccionario; las genera por defecto |
| Límite de registros por extensión | por verificar | — | `max-registrations-per-extension` |
| Troncales con IP permitida (ACL) cuando el carrier la tiene fija | 🟡 | — | ACL por troncal en el perfil `external` |
| SBC o capa de filtrado delante de FreeSWITCH | ❌ | 5060 publicado directo | fase 3: Kamailio/OpenSIPS como SBC con `pike` y `ratelimit`; mientras tanto, firewall del host + fail2ban |
| SIP TLS / SRTP | 🟡 | WSS para el navegador; UDP para teléfonos y troncales | TLS+SRTP en teléfonos que lo soporten; troncales según carrier (muchos no lo ofrecen) |
| Registro de contraseña de extensión con hash A1 en vez de texto | ❌ | `extensions.password` en claro | evaluar `a1-hash` en el directorio para no guardar la contraseña en claro |

### 5.6 Fraude telefónico (prioridad máxima)

El fraude por llamadas internacionales/premium es el riesgo más caro y el
más probable. Se defiende en capas, de modo que cualquiera alcance para
cortar la pérdida:

| Capa | Requisito | Estado | Valor propuesto por defecto |
|---|---|---|---|
| Destino | internacional bloqueado salvo permiso explícito por empresa y por ruta | 🟢 (`allow_international`) | apagado |
| Destino | lista de países permitidos (no un sí/no a "internacional") | ❌ | solo el país de la empresa |
| Destino | lista negra de prefijos premium/satelitales siempre bloqueados | ❌ | rangos premium conocidos, `+882`, `+881`, etc. |
| Volumen | llamadas salientes simultáneas por empresa | 🟢 (`max_concurrent_calls`, licencia) | según plan |
| Volumen | llamadas por segundo por empresa | ❌ | 1 CPS (campañas aparte) |
| Duración | duración máxima por llamada | 🟢 (`max_call_duration_minutes`) | 60 min |
| Dinero | minutos salientes por día por empresa | ❌ | según plan; al llegar, **se cortan las salientes**, no solo se avisa |
| Dinero | gasto estimado por día y por mes | ❌ | tarifa por prefijo × minutos |
| Horario | salientes fuera de horario laboral requieren permiso | ❌ | opcional por empresa |
| Detección | alerta si la última hora supera 3× el promedio de esa hora en los 7 días previos | ❌ | alerta + bloqueo temporal de salientes de esa extensión |
| Detección | alerta por primer uso de un país/prefijo nuevo | ❌ | alerta |
| Detección | alerta por extensión registrada desde un país distinto al habitual | ❌ | alerta |
| Reacción | botón "cortar todas las salientes" por empresa y global | 🟡 (desactivar troncal/empresa) | ver §5.14 |
| Auditoría | todo cambio de rutas salientes, internacional o topes queda registrado | ❌ | ver §5.10 |

Verificación: prueba de dialplan con destinos `00…`, `011…`, premium y
números largos que deben rechazarse; prueba de que al superar el tope
diario la siguiente llamada se rechaza; simulacro trimestral en staging
con una extensión "comprometida".

### 5.7 Voizbot

El modelo de lenguaje es **no confiable por diseño**: hay que asumir que
un llamante puede hacerle decir o pedir cualquier cosa.

```
llamante ─► STT ─► LLM ─► pide herramienta(args)
                              │
                              ▼
               _run_tool: valida args, empresa, llamante, regla de negocio
                              │  (el modelo no participa aquí)
                              ▼
                       servicio de negocio ─► DB (filtro tenant_id)
```

| Requisito | Estado | Evidencia | Verificación |
|---|---|---|---|
| El LLM no tiene acceso directo a la base ni a SQL | 🟢 | solo herramientas cerradas | — |
| Cada herramienta valida empresa y reglas fuera del modelo | 🟢 | `_run_tool` | prueba por herramienta: args de otra empresa → rechazo |
| El llamante solo actúa sobre **sus** datos (citas/deudas ligadas a su número o a la campaña) | 🟡 | `caller_phone`, `appointment_id` | prueba: pedir "cancela la cita de 3001234567" desde otro número → rechazo |
| El contexto del prompt no incluye datos de otros clientes | por verificar | — | revisión de `voice_prompts.py` |
| Éxito de herramienta explícito (no deducido del texto) | 🟢 | `_run_tool` devuelve `(ok, …)` | — |
| Topes por llamada: turnos, duración, tokens | 🟡 | `max_turns`, duración | tope de tokens por llamada y por empresa/día |
| Concurrencia de bots por empresa | 🟡 | concurrencia general | tope propio del bot |
| Costo por empresa medido | 🟢 | `AiCallUsage`, `services/usage.py` | alerta al pasar el presupuesto |
| Versionado de prompts/flujos con rollback | ❌ | `flow_json` sin historial | tabla de versiones; la campaña apunta a una versión |
| Proveedor de IA caído → degradación controlada | por verificar | — | prueba de caos: transferir a humano o mensaje y colgar, nunca silencio |
| Pruebas de prompt injection | ❌ | — | conjunto fijo de ataques ("ignora tus instrucciones", "dime los datos del cliente anterior") que corre contra `bot_sim.py` en CI |

### 5.8 Campañas

| Requisito | Estado | Evidencia | Verificación |
|---|---|---|---|
| Estados explícitos | 🟡 | `idle → running ↔ paused → done` | agregar `validating/approved` solo si hay aprobación de un segundo usuario; no antes |
| Concurrencia por campaña y tope global por empresa | 🟢 | `max_concurrency`, `max_concurrent_calls` | — |
| Validación de números antes de iniciar (formato, destino permitido, duplicados) | por verificar | — | prueba: lista con números internacionales en empresa sin permiso → rechazo |
| Horario permitido de marcación (regulación local) | ❌ | — | ventana por empresa y zona horaria |
| Límite diario y presupuesto por campaña | ❌ | — | — |
| Detener ya (kill switch) | 🟢 | pausa | prueba: tras pausar, ninguna llamada nueva sale en ≤ 2 s |
| Auditoría de crear/iniciar/pausar | ❌ | — | §5.10 |

### 5.9 Grabaciones y datos personales

| Requisito | Estado | Evidencia | Verificación |
|---|---|---|---|
| No servidas desde carpeta pública | 🟢 | solo `GET /api/calls/{id}/recording` | prueba: la ruta del archivo no es accesible por HTTP |
| Empresa + permiso validados antes de entregar | 🟢 | `_traer()` + RLS | prueba de aislamiento I3 |
| Tope de disco | 🟢 | `recordings_max_gb` | — |
| Registro de cada escucha/descarga | ❌ | — | §5.10 |
| Retención configurable por empresa y borrado real | 🟡 | tope global por espacio | retención en días por empresa; borrado verificable |
| Cifrado en reposo | 🟡 | respaldos cifrados; disco en vivo según proveedor | cifrado de volumen del proveedor |
| Exportar y borrar datos de un cliente final / de una empresa | ❌ | — | requisito de la Ley 1581 (Colombia) y similares |

### 5.10 Auditoría

Hoy **no existe** una bitácora de auditoría. Es el control que permite
responder "¿quién hizo esto?" después de un incidente, y sin él la
mayoría de los demás no se pueden investigar.

Tabla `audit_log` (append-only: el rol `nspbx_app` solo puede `INSERT` y
`SELECT`, nunca `UPDATE`/`DELETE`):

| Campo | Ejemplo |
|---|---|
| `ts` | `2026-10-01T14:03:22Z` |
| `tenant_id` | `42` |
| `actor` | `user:17`, `bot:5`, `sistema:dialer`, `plataforma:1` |
| `accion` | `ruta_saliente.actualizar` |
| `recurso` | `outbound_route:9` |
| `antes` / `despues` | JSON solo de los campos cambiados, **sin secretos** |
| `resultado` | `ok` / `denegado` / `error` |
| `ip`, `user_agent`, `request_id` | — |

Acciones mínimas a registrar: login (éxito y fallo), cambio de
contraseña, MFA, usuarios y roles, troncales, rutas salientes, permiso
internacional, topes, campañas (crear/iniciar/pausar), escucha y descarga
de grabaciones, cambios de bots, acciones del rol plataforma dentro de
una empresa, kill switches.

### 5.11 Secretos y cifrado

| Requisito | Estado | Evidencia | Verificación |
|---|---|---|---|
| Secretos de infraestructura solo en `.env`, arranque falla si faltan | 🟢 | `:?` en `docker-compose.yml` | — |
| `.env` fuera de Git | por verificar | `.gitignore` | escaneo de secretos (gitleaks) en CI y sobre el historial completo |
| Claves de proveedores por empresa (ElevenLabs, Deepgram, LLM, ARI, Turnstile) cifradas en DB | ❌ | columnas en texto claro en `system_settings` | cifrado de aplicación (AES-GCM con clave en `.env`), nunca devueltas completas por la API |
| Contraseñas de troncales y extensiones | ❌ | texto claro (FreeSWITCH las necesita) | cifradas en DB y descifradas solo al generar el XML; extensiones con `a1-hash` |
| Rotación documentada (ESL, `AUTH_SECRET`, claves de proveedor, SIP) | ❌ | — | runbook por secreto: cómo rotar y qué se corta |
| TLS en todo lo público | 🟢 | Traefik + WSS | renovación automática; alerta 14 días antes de vencer |
| Respaldos cifrados con clave fuera del servidor | 🟢 | `scripts/backup-offsite.sh` | restauración de prueba (§6.3) |

### 5.12 Base de datos

| Requisito | Estado | Evidencia | Verificación |
|---|---|---|---|
| Migraciones versionadas y reversibles | ❌ | `ALTER TABLE ... IF NOT EXISTS` en `main.py` | migrar a Alembic; la lista actual pasa a ser la migración base |
| Respaldo antes de cada migración | por verificar | — | paso obligatorio del despliegue |
| Índices en `tenant_id` + columnas de filtro habituales | por verificar | — | revisión con `pg_stat_statements` |
| Pool de conexiones dimensionado | por verificar | — | — |
| Constraints de integridad (FK, únicos por empresa) | 🟢 | p. ej. `ux_campaigns_tenant_name` | — |

### 5.13 Infraestructura

| Requisito | Estado | Evidencia | Verificación |
|---|---|---|---|
| Postgres sin puerto publicado | 🟢 | solo red `nspbx_net` | escaneo externo |
| Rotación de logs de Docker | 🟢 | `x-logging` | — |
| `no-new-privileges` | 🟡 | backend sí; resto por verificar | — |
| Contenedores sin root | 🟡 | frontend `USER node`; backend corre como root | usuario sin privilegios en `backend/Dockerfile` |
| Límites de CPU/memoria por contenedor | ❌ | — | evita que el voizbot o el dialer tumben FreeSWITCH |
| Filesystem de solo lectura donde se pueda | ❌ | — | backend y frontend con `read_only` + `tmpfs` |
| Healthchecks | 🟢 | postgres, freeswitch, backend, voicebot | — |
| SSH solo con llave, sin root, con allowlist o VPN | por verificar | — | checklist del servidor |
| Firewall del host: solo 80/443, 5060, 8443, 15080, rango RTP | por verificar | — | escaneo externo trimestral |
| Actualizaciones de imágenes y dependencias | ❌ | — | Dependabot/Renovate + `pip-audit` / `npm audit` en CI |

### 5.14 Cuotas por empresa (noisy neighbor)

Un cliente no puede degradar a los demás. Todo lo que consume un recurso
compartido tiene tope por empresa, y el tope se hace cumplir en el
backend o en el dialplan, no en el panel.

| Recurso | Estado | Dónde |
|---|---|---|
| extensiones, troncales, campañas | 🟢 | `License.max_*`, `licensing.hay_cupo` |
| llamadas simultáneas | 🟢 | `License.max_concurrent_calls`, `tope_concurrentes` |
| usuarios | ❌ | — |
| minutos salientes por día/mes | ❌ | ver §5.6 |
| almacenamiento de grabaciones | 🟡 | tope global, no por empresa |
| llamadas y tokens de voizbot por día | ❌ | — |
| peticiones a la API por minuto | ❌ | — |

### 5.15 Controles de emergencia

Deben poder ejecutarse en menos de un minuto, por alguien de guardia, sin
tocar código. Cada uno queda auditado.

| Acción | Estado | Cómo |
|---|---|---|
| Suspender empresa | 🟢 | licencia `suspended` / `Tenant.enabled` |
| Cortar todas las salientes de una empresa | 🟡 | desactivar troncales; falta un interruptor único |
| Cortar todas las salientes de la plataforma | ❌ | interruptor global leído por el dialplan |
| Detener campaña | 🟢 | pausar |
| Desactivar un voizbot | 🟢 | `VoiceBot.enabled` |
| Bloquear extensión (y tirar su registro) | 🟡 | `enabled`; falta `sofia profile ... flush_inbound_reg` automático |
| Cerrar sesiones de un usuario / de una empresa | 🟡 | `revocar_sesiones` por usuario |
| Bloquear un país o prefijo para todos | ❌ | lista negra global |
| Bloquear IP | 🟢 | fail2ban / panel de seguridad |

---

## 6. Operación

### 6.1 Observabilidad

Métricas mínimas, cada una con su alerta:

| Señal | Alerta (propuesta) |
|---|---|
| Llamadas salientes por empresa/hora | > 3× su promedio de 7 días, o > tope diario |
| Registros SIP fallidos/min | > 30 desde una IP, > 200 en total |
| Llamadas activas | > 80 % del tope de la plataforma |
| Errores 5xx de la API | > 1 % en 5 min |
| Latencia p95 de la API | > 1 s en 10 min |
| Latencia STT/LLM/TTS por turno | p95 > 2,5 s (el llamante percibe silencio) |
| Errores de proveedores de IA | > 5 % en 5 min |
| Disco | > 80 % |
| Edad del último respaldo local / off-site | > 26 h |
| Certificados | vencen en < 14 días |
| Contenedor `unhealthy` o reiniciándose | cualquier reinicio en bucle |
| Troncal sin registro | > 2 min |

Logs: JSON con `request_id`, `tenant_id`, `call_uuid`, sin secretos ni
contenido de conversaciones completas. Retención 30 días.

### 6.2 Objetivos de servicio

| Objetivo | Hoy | Meta |
|---|---|---|
| RPO (datos que se pueden perder) | ~24 h (volcado diario) | 15 min (archivado continuo de WAL con wal-g o pgBackRest) |
| RTO (tiempo para volver a operar) | sin medir | 2 h en servidor nuevo, medido en simulacro |
| Disponibilidad mensual | sin medir | 99,5 % |

### 6.3 Respaldos y recuperación

- Diario local + off-site cifrado: 🟢 (`backup-offsite.sh`, se niega a
  subir un volcado de más de 26 h).
- **Restauración de prueba mensual** en un servidor limpio, cronometrada:
  ❌. Un respaldo que nunca se restauró no es un respaldo. El simulacro
  pasa si: la base restaura, el backend arranca, una extensión registra y
  una llamada de prueba se completa, y se anota el tiempo total (RTO real).
- Procedimiento escrito de recuperación total (servidor perdido): ❌ →
  `docs/runbooks/recuperacion-total.md`.

### 6.4 Runbooks

Cada uno con: síntomas, cómo confirmar, cómo contener, cómo recuperar, a
quién avisar. Mínimo:

1. Fraude telefónico en curso.
2. Credencial filtrada (usuario, extensión SIP, clave de proveedor, `AUTH_SECRET`).
3. Sospecha de fuga entre empresas.
4. Empresa saturando la plataforma.
5. Base de datos caída / disco lleno.
6. Proveedor de IA caído.
7. Troncal caída.
8. Recuperación total desde respaldo off-site.
9. Rotación de cada secreto.

### 6.5 Respuesta a incidentes

Severidades: **S1** viola una invariante o hay pérdida económica en curso
(respuesta inmediata, contener primero); **S2** degradación para varias
empresas; **S3** una empresa o una función. Todo S1 y S2 cierra con un
informe breve: qué pasó, cuánto duró, a quién afectó, qué prueba nueva lo
habría detectado.

---

## 7. Verificación

Esta sección es la que convierte el documento en confianza.

### 7.1 Suite obligatoria

| Suite | Qué prueba | Sostiene |
|---|---|---|
| **Aislamiento** | dos empresas con datos espejo (misma extensión 1000, mismo nombre de campaña). Para **cada** endpoint de lectura/escritura, la empresa A intenta acceder a cada recurso de B por ID → 404. Se repite con el filtro de la aplicación desactivado (RLS debe cortar igual). | I1, I3 |
| **Cobertura de rutas** | enumera `app.routes`; falla si una ruta no tiene permiso declarado ni está en la lista abierta, o si no tiene prueba de aislamiento. | I1, I8 |
| **Dialplan** | genera directorio y dialplan para dos empresas y comprueba que ningún destino de A resuelve en B; DID ajeno rechazado. | I2 |
| **Fraude** | destinos internacionales, premium, largos, con prefijos raros → rechazados; tope diario y de concurrencia → rechazo. | I5 |
| **Voizbot** | cada herramienta con args de otra empresa o de otro llamante → rechazo; batería de prompt injection contra `bot_sim`. | I4 |
| **Alcance** | admin de empresa en instalación con 2+ empresas → 403 en todas las operaciones globales. | I6 |
| **Secretos** | gitleaks sobre el repo; los logs de la suite no contienen contraseñas ni claves. | I7 |
| **Fallo seguro** | token corrupto, empresa inexistente, licencia ilegible, DB sin `app.tenant_id` → todos niegan. | I8 |

### 7.2 Pipeline

```
push ─► lint + tipos ─► unit ─► suites §7.1 contra Postgres real (con RLS)
     ─► gitleaks + pip-audit + npm audit ─► build de imágenes
     ─► staging ─► smoke (registro + llamada de prueba) ─► aprobación ─► producción
     ─► verificar.sh + monitoreo 30 min ─► rollback a la imagen anterior si falla
```

Regla: **no se despliega con una suite de §7.1 en rojo**. No hay
excepción por urgencia; si la prueba está mal, se arregla la prueba en el
mismo cambio.

### 7.3 Pruebas periódicas

| Prueba | Frecuencia | Pasa si |
|---|---|---|
| Restauración en servidor limpio | mensual | completa en < RTO, llamada de prueba OK |
| Escaneo de puertos externo | trimestral | solo los puertos de §5.13 |
| Ataque SIP simulado (sipvicious) en staging | trimestral | IP bloqueada < 1 min, ninguna llamada saliente |
| Caos: matar Postgres, voicebot, proveedor IA, llenar disco, reiniciar host | semestral | se detecta, alerta, se recupera sin intervención o con runbook, sin fuga entre empresas |
| Pentest externo | anual o antes de clientes grandes | sin hallazgos críticos abiertos |
| Revisión de este documento | trimestral | estados al día |

---

## 8. Hoja de ruta

Ordenada por riesgo × probabilidad, no por facilidad. Cada fase tiene un
criterio de "terminado" verificable.

### Fase 0 — Probar lo que ya existe (antes que nada)

- Infraestructura de pruebas con Postgres real y RLS activo.
- Suites de aislamiento, cobertura de rutas, dialplan y fallo seguro (§7.1).
- CI que las corra en cada push, más gitleaks.
- Arranque que falla en producción sin `DATABASE_URL_APP` o `AUTH_SECRET`.

**Terminado cuando:** I1, I2, I6 e I8 tienen prueba en verde en CI, y
quitar a propósito un filtro `tenant_id` hace fallar el pipeline.

### Fase 1 — Cortar el riesgo económico

- Tope de minutos y gasto por día por empresa, con corte automático.
- Lista de países permitidos y lista negra global de prefijos premium.
- Alertas de anomalía de tráfico saliente.
- Interruptor global y por empresa de salientes.
- Contraseñas SIP generadas y validadas.
- Suite de fraude en CI.

**Terminado cuando:** el simulacro de extensión comprometida en staging
no logra superar el tope diario y genera alerta en < 5 min.

### Fase 2 — Poder investigar y recuperar

- `audit_log` append-only y sus acciones mínimas.
- `request_id` y logs estructurados.
- MFA para `plataforma` y `admin`.
- Alembic.
- WAL continuo (RPO 15 min) y primer simulacro de restauración medido.
- Runbooks 1, 2, 3 y 8.

**Terminado cuando:** se puede reconstruir quién cambió una ruta saliente
hace 30 días, y hay un RTO medido.

### Fase 3 — Endurecer y escalar

- Secretos de proveedores y troncales cifrados en DB; `a1-hash` en extensiones.
- Backend sin root, límites de recursos, filesystem de solo lectura.
- Cabeceras de seguridad (CSP, HSTS).
- Versionado de flujos del voizbot y suite de prompt injection.
- Grabaciones por carpeta de empresa, retención por empresa, registro de escuchas.
- Redis para limitadores y estado compartido (requisito para más de un proceso).
- SBC (Kamailio/OpenSIPS) delante de FreeSWITCH cuando el volumen lo justifique.

### Fase 4 — Producto SaaS maduro

- API pública versionada con API keys por empresa y scopes.
- Facturación por consumo y alertas de consumo al cliente.
- Exportación y borrado de datos por empresa y por titular.
- Pentest externo.
- Base dedicada para empresas grandes (el modelo de una base + RLS lo permite moviendo un `tenant_id`).

---

## 9. Criterios para salir a producción con un cliente nuevo

En vez de una lista plana de 60 casillas, cuatro compuertas. No se pasa a
la siguiente sin cerrar la anterior.

**Compuerta A — Se puede vender a una empresa**
- [ ] Invariantes I1, I2, I6, I8 con prueba en CI
- [ ] Internacional apagado y topes de concurrencia y duración activos
- [ ] Respaldo diario + off-site funcionando y alertado

**Compuerta B — Se puede vender a varias empresas**
- [ ] Todo lo de A
- [ ] Topes de minutos/gasto con corte automático (I5)
- [ ] Alertas de fraude
- [ ] Auditoría de cambios sensibles
- [ ] MFA para administradores
- [ ] Simulacro de restauración hecho y medido

**Compuerta C — Se puede vender voizbot y campañas a escala**
- [ ] Todo lo de B
- [ ] I4 con prueba (herramientas + prompt injection)
- [ ] Topes de tokens y bots por empresa
- [ ] Ventana horaria de campañas

**Compuerta D — Clientes grandes o regulados**
- [ ] Todo lo de C
- [ ] Pentest externo sin críticos abiertos
- [ ] Retención y borrado de datos por empresa
- [ ] Secretos cifrados en DB
- [ ] RPO 15 min / RTO medido ≤ 2 h

---

## 10. Lo que este documento no promete

- **No promete invulnerabilidad.** Promete que una falla queda contenida
  en una empresa, se detecta en minutos y tiene un tope económico.
- **No reemplaza al proveedor de infraestructura.** DDoS volumétrico
  contra SIP/RTP se mitiga en la red del proveedor o con un servicio
  especializado; un WAF HTTP no protege el 5060.
- **No cubre al cliente final.** Si una empresa entrega su contraseña de
  administrador, el sistema limita el daño (topes, auditoría, alertas)
  pero no lo puede evitar.
- **Un control 🟢 no está garantizado.** Hasta que tenga prueba en CI,
  cualquier cambio puede romperlo en silencio.
