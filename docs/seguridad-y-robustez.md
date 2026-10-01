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

La fase 0 (sección 8) agregó la suite de `backend/tests/` y el workflow
`.github/workflows/ci.yml`: el aislamiento entre empresas (I1, I2, I3), el
alcance (I6) y el fallo seguro (I8) ya están en ✅. El resto sigue en 🟢 o
menos hasta que tenga su prueba.

Para correr las pruebas en un equipo propio hace falta un Postgres 16
descartable (la suite borra la base entera):

```bash
cd backend
pip install -r requirements-dev.txt
TEST_DATABASE_URL=postgresql+asyncpg://postgres:clave@localhost:5432/nspbx_test python -m pytest
```

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
| `tenant_id` no nulo en toda tabla de negocio | ✅ | `models/models.py` (`_tenant_fk`) | `test_aislamiento_db.py`: recorre los modelos y falla si una tabla de negocio admite NULL o no tiene RLS |
| RLS con `USING` y `WITH CHECK` en esas tablas | ✅ | `main.py:_parches_rls` | `test_aislamiento_db.py`: `SELECT`/`UPDATE`/`DELETE` sin `WHERE` no tocan otra empresa; sin empresa fijada no se ve nada; `INSERT` o mover una fila a otra empresa falla |
| La app conecta con `nspbx_app`, sin `SUPERUSER` ni `BYPASSRLS` | ✅ | `core/database.py`, `core/arranque.py` | el arranque lo verifica y en producción **no arranca** si `DATABASE_URL_APP` falta o es el rol dueño; `test_aislamiento_db.py`, `test_arranque.py` |
| `SET LOCAL app.tenant_id` sobrevive a varios commits | ✅ | `after_begin` en `core/database.py` | `test_la_empresa_sobrevive_a_varios_commits` |
| `tenant_id` nunca se toma del cliente | 🟢 | sale del token firmado | prueba: enviar `tenant_id` ajeno en el body no tiene efecto |
| Directorio y dialplan de FreeSWITCH por dominio/contexto | ✅ | `services/xml_endpoints.py`, `config_generator.py` | `test_dialplan.py`: dos empresas con extensión 1000, cola 5000 y troncal "principal"; ningún contexto menciona a la otra |
| Entrantes: DID → empresa | ✅ | contexto `public` | `test_dialplan.py`: cada DID va al contexto y dominio de su empresa; un DID sin dueño cuelga |
| Gateways con prefijo por empresa | ✅ | `services/gateways.py` | `test_dialplan.py`: cada contexto sale solo por `sofia/gateway/<su_slug>_…` |
| WebSocket de logs/eventos filtrado por empresa | ✅ | `api/logs_ws.py` fija tenant; consola FS solo operador global | `test_rutas_abiertas.py` (sin token no hay usuario), `test_alcance.py` (admin de empresa no es operador global) |
| Workers (dialer, mantenimiento) conservan la empresa | 🟡 | `workers/dialer.py` | revisar que cada consulta del worker fije tenant o filtre explícito; prueba |
| Herramientas del voizbot filtran por `tenant_id` (sesión sin RLS) | 🟡 | `services/ai_agent.py:_run_tool` | **lint/prueba que falle si una consulta en `_run_tool` no menciona `tenant_id`**; a futuro, darle al bot su propia sesión con RLS por llamada |
| **Filtro por empresa también en la aplicación** (segunda capa, independiente de RLS) | ✅ | `core/database.py`: `with_loader_criteria` en toda consulta ORM de una sesión atada a una empresa, `traer_propio()` en las búsquedas por id; la sesión exige que la empresa del token sea la del usuario | CI corre la suite de la API dos veces: con RLS y con el rol dueño (`NSPBX_TEST_SIN_RLS=1`). Desactivar el filtro de la aplicación hace fallar 25 pruebas del segundo modo |
| Caché / almacenamiento de archivos por empresa | 🟡 | grabaciones en carpetas por fecha, no por empresa | mover a `recordings/t<id>/...` para que el aislamiento también sea físico y la retención por empresa sea trivial |

### 5.2 Identidad y sesiones

| Requisito | Estado | Evidencia | Verificación |
|---|---|---|---|
| Hash de contraseñas fuerte | 🟢 | PBKDF2-SHA256 (`core/security.py`) | revisar iteraciones ≥ 600 000 (recomendación OWASP actual); migrar a Argon2id al próximo login |
| Token de acceso corto + refresh token rotado y hasheado | 🟢 | `crear_token`, `RefreshToken` | prueba: refresh reutilizado invalida la familia |
| Revocación de sesiones | ✅ | `services/sesiones.py`, `sesiones_desde` | `test_fallo_seguro.py`: usuario desactivado, rol rebajado y sesiones cerradas cortan al instante |
| Límite de intentos de login por IP y por usuario | 🟢 | `core/limitador.py` (en memoria) | prueba; pasa a Redis el día que haya más de un proceso |
| IP real detrás del proxy, no falsificable | 🟢 | `ip_cliente()` | prueba con `X-Forwarded-For` inventado |
| `AUTH_SECRET` obligatorio en producción | ✅ | `core/arranque.py` | en producción no arranca sin ella o con menos de 32 caracteres; `test_arranque.py` |
| MFA (TOTP) | ✅ | `core/mfa.py`, `/api/auth/mfa/*` | obligatorio para `plataforma` y `admin` (`MFA_OBLIGATORIO`): hasta activarla la sesión solo sirve para activarla; códigos de un solo uso y de recuperación; `test_mfa.py` (incluye los vectores de la RFC 6238) |
| Recuperación de contraseña segura | ❌/por verificar | — | token de un solo uso, 15 min, no revela si el correo existe |
| Lista de sesiones/dispositivos visible al usuario | ❌ | — | — |

### 5.3 Autorización (RBAC)

| Requisito | Estado | Evidencia | Verificación |
|---|---|---|---|
| Permisos granulares, no `if rol == "admin"` | 🟢 | `core/permissions.py`, overrides por empresa | — |
| Toda ruta bajo `/api/` exige sesión salvo lista explícita | ✅ | `core/auth.py:_es_abierta` | `test_rutas_abiertas.py`: llama TODAS las rutas sin token; la lista abierta está repetida en la prueba a propósito |
| Operaciones globales separadas de las de empresa | ✅ | `core/alcance.py` | `test_alcance.py`: admin, supervisor y asesor de una empresa reciben 403 en empresas, licencias, diagnóstico y respaldos |
| Licencia suspendida bloquea operación | ✅ | `licencia_operativa()` | `test_fallo_seguro.py`: deja ver, no deja crear (402); empresa desactivada → 403 y fuera de FreeSWITCH |
| Matriz rol × endpoint documentada y probada | 🟡 | — | `test_alcance.py` cubre lo sensible (troncales, extensiones, rutas, usuarios, ajustes: solo admin); falta la matriz completa |

### 5.4 API

| Requisito | Estado | Evidencia | Verificación |
|---|---|---|---|
| Validación de entradas (teléfonos, nombres, XML, rutas de audio) | 🟢 | `core/validacion.py`, Pydantic | pruebas con inyección en dialplan/XML (`limpiar_xml`, `TELEFONO_RE`) |
| CORS abierto **sin credenciales**, token en cabecera | 🟢 | `main.py:576` | prueba de que no hay cookies de sesión |
| Sin stack traces en producción | por verificar | — | prueba: error 500 devuelve mensaje genérico + `request_id` |
| `request_id` en cada petición y en cada log | ✅ | `core/auditoria.py` | cabecera `X-Request-ID` en cada respuesta y en cada línea de log; `LOG_FORMATO=json` para un recolector; `test_auditoria.py` |
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
| `mod_xml_curl` y CDR con secreto compartido | ✅ | `verificar_secreto_fs` | `test_dialplan.py`: `/fs/directory`, `/fs/dialplan` y `/fs/cdr` sin secreto o con otro dan 403 |
| WS/WSS de desarrollo solo en loopback | 🟢 | `127.0.0.1:5066` | escaneo de puertos externo |
| fail2ban para registro fallido y escaneo | 🟢 | `deploy/fail2ban/` | prueba con sipvicious contra staging: la IP queda bloqueada en < 1 min |
| Rango RTP acotado | 🟢 | `16384-16584/udp` | — |
| Contraseñas SIP fuertes y generadas por el sistema | ✅ | `validacion.problema_clave_sip`, `generar_clave_sip` | `test_claves_sip.py`: 12+ caracteres, no solo números, sin el número de la extensión, no comunes; vacía = generada (20). Las existentes débiles se listan en Seguridad |
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
| Destino | una sola política para los tres caminos de salida (dialplan, clic para llamar, campañas) | ✅ (`services/salientes.py`) | antes el clic para llamar y el marcador salían directo a la troncal sin filtro |
| Destino | internacional solo con permiso de la empresa **y** de la regla | ✅ | apagado |
| Destino | el filtro se aplica a lo que sale (después de quitar y anteponer dígitos), no a lo que se marca | ✅ | `test_dialplan_y_python_deciden_igual` compara la regla del dialplan y la de Python en todas las combinaciones |
| Destino | lista de países permitidos (no un sí/no a "internacional") | ✅ (`international_countries`) | vacía = ningún internacional |
| Destino | lista negra de prefijos premium/satelitales siempre bloqueados | ✅ | `+870`, `+881`, `+882`, `+883`, `+979`, `+808`, `+1 900` |
| Volumen | llamadas salientes simultáneas por empresa | 🟢 (`max_concurrent_calls`, licencia) | según plan |
| Volumen | llamadas por segundo por empresa | ❌ | 1 CPS (campañas aparte) |
| Duración | duración máxima por llamada | 🟢 (`max_call_duration_minutes`) | 60 min |
| Dinero | minutos salientes por día por empresa | ✅ (`License.max_outbound_minutes_day`) | prueba 60, gratis 120, pro 5000, enterprise sin tope; al llegar **se cortan las salientes** hasta medianoche. Cuenta solo la pata que salió por troncal (`CallLog.via_trunk`) y solo llamadas terminadas: las que están en curso las acotan la duración máxima y las simultáneas |
| Dinero | gasto estimado por día y por mes | ❌ | tarifa por prefijo × minutos |
| Horario | salientes fuera de horario laboral requieren permiso | ❌ | opcional por empresa |
| Detección | alerta si la última hora supera 3× el promedio de esa hora en los 7 días previos (mín. 30 min) | ✅ (`services/alertas.py`) | alerta en el panel y webhook. **No corta**: una campaña nueva también es un pico; el corte lo da el cupo |
| Detección | alerta por salientes de madrugada, prefijo internacional nuevo y 80 % del cupo | ✅ | alerta |
| Detección | alerta por extensión registrada desde un país distinto al habitual | ❌ | alerta |
| Reacción | botón "cortar todas las salientes" por empresa (la empresa y la plataforma) y global | ✅ | ver §5.15. Corta toda llamada **nueva**; las que están en curso terminan por la duración máxima |
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
| Empresa + permiso validados antes de entregar | ✅ | `_traer()` + RLS | `test_grabacion_de_otra_empresa_no_se_entrega` (con el archivo presente en disco) |
| Tope de disco | 🟢 | `recordings_max_gb` | — |
| Registro de cada escucha/descarga | ❌ | — | §5.10 |
| Retención configurable por empresa y borrado real | 🟡 | tope global por espacio | retención en días por empresa; borrado verificable |
| Cifrado en reposo | 🟡 | respaldos cifrados; disco en vivo según proveedor | cifrado de volumen del proveedor |
| Exportar y borrar datos de un cliente final / de una empresa | ❌ | — | requisito de la Ley 1581 (Colombia) y similares |

### 5.10 Auditoría

✅ Implementada (`core/auditoria.py`, `test_auditoria.py`). Es el control
que permite responder "¿quién hizo esto?" después de un incidente.

Un middleware registra **toda** petición que modifica algo bajo `/api/` y
cada escucha de grabación, incluidos los logins fallidos: un endpoint
nuevo queda auditado sin que nadie tenga que acordarse. La empresa la ve
en Seguridad y la plataforma en Empresas. La retención
(`AUDITORIA_RETENCION_DIAS`, 365) la aplica el worker de mantenimiento.
Lo que todavía no guarda: el valor **anterior** de lo que cambió (solo lo
enviado).

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
| `.env` fuera de Git | ✅ | `.gitignore` (`.env`, `.env.*`) | gitleaks sobre el historial completo en cada push (`ci.yml`) |
| Claves privadas en el historial | ❌ | `freeswitch/conf/tls/wss.pem` y `dtls-srtp.pem` del primer commit | ya no están en el árbol, pero sí en el historial: tratarlas como filtradas y **rotarlas** si el servidor todavía las usa. Detalle en `.gitleaksignore` |
| Claves de proveedores por empresa (ElevenLabs, Deepgram, LLM, ARI, Turnstile) cifradas en DB | ❌ | columnas en texto claro en `system_settings` | cifrado de aplicación (AES-GCM con clave en `.env`), nunca devueltas completas por la API |
| Contraseñas de troncales y extensiones | ❌ | texto claro (FreeSWITCH las necesita) | cifradas en DB y descifradas solo al generar el XML; extensiones con `a1-hash` |
| Rotación documentada (ESL, `AUTH_SECRET`, claves de proveedor, SIP) | ❌ | — | runbook por secreto: cómo rotar y qué se corta |
| TLS en todo lo público | 🟢 | Traefik + WSS | renovación automática; alerta 14 días antes de vencer |
| Respaldos cifrados con clave fuera del servidor | 🟢 | `scripts/backup-offsite.sh` | restauración de prueba (§6.3) |

### 5.12 Base de datos

| Requisito | Estado | Evidencia | Verificación |
|---|---|---|---|
| Migraciones versionadas y reversibles | ✅ | Alembic en `app/migraciones` (revisión base idempotente); permisos y RLS convergen en cada arranque | `test_migraciones.py`: el esquema base congelado llevado a la última revisión tiene que coincidir con los modelos (un modelo cambiado sin revisión rompe el CI) |
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
| minutos salientes por día | ✅ | `License.max_outbound_minutes_day`, ver §5.6 |
| almacenamiento de grabaciones | 🟡 | tope global, no por empresa |
| llamadas y tokens de voizbot por día | ❌ | — |
| peticiones a la API por minuto | ❌ | — |

### 5.15 Controles de emergencia

Deben poder ejecutarse en menos de un minuto, por alguien de guardia, sin
tocar código. Cada uno queda auditado.

| Acción | Estado | Cómo |
|---|---|---|
| Suspender empresa | 🟢 | licencia `suspended` / `Tenant.enabled` |
| Cortar todas las salientes de una empresa | ✅ | la empresa (Ajustes → Pausar) o la plataforma (Empresas → Cortar salientes; la empresa no puede deshacerlo) |
| Cortar todas las salientes de la plataforma | ✅ | Empresas → Cortar todas las salientes (`PUT /api/plataforma/salientes`) |
| Colgar las salientes **en curso** | ❌ | hoy terminan por la duración máxima; falta un `hupall` por empresa |
| Detener campaña | 🟢 | pausar |
| Desactivar un voizbot | 🟢 | `VoiceBot.enabled` |
| Bloquear extensión (y tirar su registro) | 🟡 | `enabled`; falta `sofia profile ... flush_inbound_reg` automático |
| Cerrar sesiones de un usuario / de una empresa | 🟡 | `revocar_sesiones` por usuario |
| Bloquear un país o prefijo para todos | 🟡 | lista fija en `salientes.CODIGOS_BLOQUEADOS`; falta poder agregar desde el panel |
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
- **Restauración de prueba mensual**: 🟡 `scripts/simulacro-restauracion.sh`
  restaura el último respaldo (o el paquete off-site cifrado) en un
  Postgres descartable, comprueba empresas, usuarios y RLS, y registra
  tiempo y edad del respaldo en `backups/simulacros.log`. Falta correrlo en
  el servidor y, una vez por trimestre, completarlo con backend, registro
  de una extensión y una llamada (RTO real). Ensayarlo encontró que
  `restore.sh` rechazaba todo respaldo real y que `setup.sh` no servía en
  un servidor nuevo con el `.env` guardado: los dos están corregidos.
- Procedimiento escrito de recuperación total: ✅
  `docs/runbooks/recuperacion-total.md`.

### 6.4 Runbooks

Cada uno con: síntomas, cómo confirmar, cómo contener, cómo recuperar, a
quién avisar. En `docs/runbooks/`: ✅ 1, 2, 3 y 8. Pendientes: 4, 5, 6, 7 y
9 (la rotación de secretos está resumida en el 2). Mínimo:

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
| ✅ **Aislamiento** (`test_aislamiento_db.py`, `test_aislamiento_api.py`) | dos empresas con datos espejo (misma extensión 1000, mismo nombre de campaña). Para **cada** ruta con id, la empresa A ataca el recurso de B → 404, sin datos de B en la respuesta, y la foto de B en la base queda idéntica. Control positivo: el mismo pedido sobre lo propio funciona. En la base, consultas sin `WHERE` con el rol de la aplicación. | I1, I3 |
| ✅ **Cobertura de rutas** (`test_rutas_abiertas.py`, `test_aislamiento_api.py`) | enumera `app.routes`; falla si una ruta responde sin token fuera de la lista abierta, o si una ruta con un id nuevo no tiene recurso declarado para atacarla. | I1, I8 |
| ✅ **Dialplan** (`test_dialplan.py`) | directorio y dialplan para dos empresas: ningún destino de A resuelve en B; DID ajeno rechazado; salientes sin 00/011. | I2 |
| ✅ **Fraude** (`test_salientes*.py`, `test_interruptores.py`, `test_alertas.py`) | destinos internacionales, premium, largos, con prefijos raros → rechazados en los tres caminos de salida; Python y dialplan deciden igual; interruptores y cupo diario cortan; alertas. | I5 |
| **Voizbot** | cada herramienta con args de otra empresa o de otro llamante → rechazo; batería de prompt injection contra `bot_sim`. | I4 |
| ✅ **Alcance** (`test_alcance.py`) | admin de empresa en instalación con 2+ empresas → 403 en todas las operaciones globales. | I6 |
| 🟡 **Secretos** (`ci.yml`) | gitleaks sobre el historial completo ✅; falta comprobar que los logs no contengan contraseñas ni claves. | I7 |
| ✅ **Fallo seguro** (`test_fallo_seguro.py`, `test_arranque.py`) | token corrupto, sin firma, vencido, de otra clave, con la empresa de otro usuario o una inexistente; usuario o empresa desactivados; licencia suspendida; secretos faltantes al arrancar → todos niegan. | I8 |

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

### Fase 0 — Probar lo que ya existe ✅

- ✅ Infraestructura de pruebas con Postgres real y RLS activo (`backend/tests/conftest.py`).
- ✅ Suites de aislamiento, cobertura de rutas, dialplan, alcance y fallo seguro (§7.1).
- ✅ CI que las corre en cada push, más gitleaks sobre el historial (`.github/workflows/ci.yml`).
- ✅ Arranque que falla en producción sin `DATABASE_URL_APP`, `AUTH_SECRET` o `FS_XML_SECRET` (`core/arranque.py`).

**Terminado cuando:** I1, I2, I6 e I8 tienen prueba en verde en CI, y
quitar a propósito un filtro `tenant_id` hace fallar el pipeline.
Comprobado rompiendo el aislamiento a propósito: una política RLS que deja
ver todo hace fallar 93 pruebas, y sacar `extensions` de la lista de RLS
hace fallar 12.

Lo que dejó a la vista, y pasa a la fase 1:
- RLS es la única capa en unas 30 operaciones por id y 6 listados (§5.1).
- El filtro internacional mira lo marcado, no lo que sale (§5.6).
- Dos claves privadas de FreeSWITCH siguen en el historial (§5.11).

### Fase 1 — Cortar el riesgo económico ✅ (falta el simulacro en staging)

- ✅ Una sola política de salientes para dialplan, clic para llamar y
  campañas, aplicada sobre el número que sale (`services/salientes.py`).
- ✅ Filtro por empresa también en la aplicación, con la suite de la API
  corriendo también sin RLS en CI.
- ✅ Tope de minutos salientes por día por empresa, con corte automático.
- ✅ Lista de países permitidos y lista negra global de prefijos premium.
- ✅ Alertas de tráfico saliente anómalo (panel y webhook).
- ✅ Interruptores de salientes: de la empresa, de la plataforma por
  empresa y global.
- ✅ Contraseñas SIP generadas y validadas; las débiles existentes, listadas.
- ✅ Suite de fraude en CI.

**Terminado cuando:** el simulacro de extensión comprometida en staging
no logra superar el tope diario y genera alerta en < 5 min. **Pendiente**:
requiere FreeSWITCH real. También hay que confirmar con una llamada real
que el CDR de la pata hacia el proveedor llega con `via_trunk` verdadero
(el cupo y las alertas se apoyan en eso).

Quedó para después: tope de **gasto** (necesita tarifas por prefijo),
llamadas por segundo, horario permitido de salientes, colgar las llamadas
en curso al cortar, y agregar prefijos bloqueados desde el panel.

### Fase 2 — Poder investigar y recuperar 🟡

- ✅ `audit_log` de solo agregar, con todas las escrituras de la API,
  escuchas de grabaciones y logins.
- ✅ `request_id` y logs estructurados (`LOG_FORMATO=json`).
- ✅ MFA obligatorio para `plataforma` y `admin`.
- ✅ Alembic, con prueba de desvío entre modelos y revisiones.
- 🟡 Simulacro de restauración: script listo y probado; falta la primera
  corrida en el servidor para tener el RTO real.
- ❌ WAL continuo (RPO 15 min): necesita un almacenamiento externo
  (S3/B2) y configurar `archive_command` (wal-g o pgBackRest) en el
  contenedor de Postgres; no se puede probar sin ese destino. Mientras
  tanto el RPO sigue en hasta 24 h.
- ✅ Runbooks 1, 2, 3 y 8.

**Terminado cuando:** se puede reconstruir quién cambió una ruta saliente
hace 30 días (✅ con la auditoría), y hay un RTO medido (pendiente: correr
el simulacro en el servidor).

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
- [x] Invariantes I1, I2, I6, I8 con prueba en CI
- [ ] Internacional apagado y topes de concurrencia y duración activos
- [ ] Respaldo diario + off-site funcionando y alertado

**Compuerta B — Se puede vender a varias empresas**
- [ ] Todo lo de A
- [x] Tope de minutos con corte automático (I5); el de gasto, pendiente
- [x] Alertas de fraude
- [x] Auditoría de cambios sensibles
- [x] MFA para administradores
- [ ] Simulacro de restauración hecho y medido (script listo; falta correrlo en el servidor)

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
