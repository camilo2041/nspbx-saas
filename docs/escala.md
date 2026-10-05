# Escala: varias réplicas, carga medida y lo que sigue

Fase 7 del contact center (docs/plan-contact-center.md). Este documento dice
qué soporta hoy el sistema, cómo se comporta con más de una réplica del
backend, qué se midió y qué decisiones de infraestructura quedan para cuando
haga falta más.

## 1. Varias réplicas del backend

El backend puede correr en más de una réplica detrás de Traefik, para
disponibilidad (si una cae, la otra sigue) más que para capacidad: una sola
réplica atiende 200 agentes con margen (ver §3).

### Una líder, las demás atienden HTTP

`services/lider.py`. La réplica que tiene el `pg_try_advisory_lock` de
Postgres es la **líder** y es la única que:

- marca (dialer del voizbot, progresivo y predictivo);
- procesa los eventos de canal de FreeSWITCH (agentes, tablero, monitoreo);
- reparte los webhooks, manda los reportes programados y hace el mantenimiento.

Las demás atienden cualquier petición HTTP o WebSocket, y de FreeSWITCH solo
reciben el resultado (`BACKGROUND_JOB`) de los `originate` que ellas mismas
lanzan (clic para llamar, por ejemplo).

Por qué: si dos réplicas procesaran los eventos, cada agente cambiaría de
estado dos veces; si dos marcaran, saldría el doble de llamadas.

**Relevo.** El candado vive en una conexión propia. Si la líder muere o pierde
la base, Postgres lo suelta y otra réplica lo toma en su siguiente vuelta
(cada 5 s). La que perdió la base deja de trabajar como líder en el acto:
más vale unos segundos sin marcar que dos marcando. Al tomar el liderazgo:

- los números que quedaron en `dialing` vuelven a pendientes;
- se cuelgan las llamadas del predictivo que la líder anterior dejó sin
  asignar (`hupall … nspbx_pred 1`): nadie las iba a pasar a un agente;
- se cierran las sesiones de agente y las escuchas del supervisor: los
  agentes vuelven a entrar (igual que tras un reinicio, que es lo que es).

Las llamadas ya conectadas con un agente siguen en FreeSWITCH (no dependen
del backend); el agente las dispone al volver a entrar.

**Migraciones.** Si dos réplicas arrancan a la vez, una migra y la otra
espera (`pg_advisory_xact_lock` en `main.migrar`).

### Lo que se comparte entre réplicas

`services/bus.py`, con LISTEN/NOTIFY de Postgres (no hace falta Redis):

| Mensaje | Para qué |
|---|---|
| `tr` | El tablero en vivo: cambios de llamadas y de agentes. Cada réplica refleja las llamadas en curso, así quien se conecta a cualquiera ve la foto completa. |
| `permisos` | Caché de permisos personalizados: la réplica que guarda avisa y las demás releen. |
| `pred` | Foto del predictivo (llamadas timbrando, clientes esperando, métricas de 15 min), cada 2 s, para las cifras en vivo de cualquier réplica. |
| `webhooks` | Invalidar la caché de suscriptores al crear, editar o borrar un webhook. |
| `nodos` | Invalidar el directorio de servidores FreeSWITCH al cambiar un servidor o mover una empresa (§4). |

Las escuchas del supervisor (escuchar, susurrar, intervenir) están en la
tabla `monitoreos`: la petición la atiende cualquier réplica y los eventos los
procesa la líder. La regla «un supervisor por agente» la garantiza la base
(restricción única), no la memoria de una réplica.

### Desplegar una segunda réplica

Hoy `docker-compose.yml` fija `container_name: nspbx_backend`, que impide
`docker compose up --scale backend=2`. Para pasar a dos réplicas:

1. Quitar `container_name` del servicio `backend` (lo demás lo encuentra por el
   nombre del servicio, `backend`, en la red interna).
2. `docker compose up -d --scale backend=2`. Traefik reparte las peticiones
   entre las dos; los WebSocket funcionan contra cualquiera.
3. Comprobar en el log de cada una cuál dice «Esta réplica es la líder».

No se hizo por defecto: con 200 agentes una réplica alcanza, y el cambio de
nombre conviene hacerlo en una ventana de mantenimiento.

## 2. Lo que se optimizó con la prueba de carga

La prueba de carga encontró tres problemas reales, ya corregidos:

| Qué | Antes | Después | Causa |
|---|---|---|---|
| Vuelta del predictivo (lanzar 131 llamadas, 50 agentes) | 3,7 s | 0,13 s | La política de salientes de la empresa se recalculaba por cada número. Ahora se calcula una vez por tanda (`agentes.ContextoLlamada`); la lista de no llamar ya la filtra el hopper. |
| Asignar una contestada | 38 ms, en fila | 16 ms, 8 en paralelo | La asignación bloqueaba a TODOS los agentes listos de la empresa; ahora elige uno en SQL con `SKIP LOCKED`. Contar y asignar van en una transacción, y las contestadas se asignan en paralelo manteniendo el orden por llamada. |
| Reporte de agentes de una semana (200 agentes) | 24,5 s | 0,3 s | Se cargaban 560 mil tramos en Python; ahora suma la base (`GROUP BY`). Igual en campañas (4 s → 50 ms) y cumplimiento (5,4 s → 1,3 s). |

Las cifras de los reportes siguen siendo exactamente las mismas: las pruebas
de la fase 6 (jornada sembrada a mano) lo comprueban.

## 3. Resultados (200 agentes)

`backend/carga/prueba_carga.py`, en el contenedor de desarrollo (4 núcleos,
Postgres local, FreeSWITCH simulado). En un servidor de producción con
Postgres afinado los tiempos de base deberían ser menores.

| Medición | Resultado |
|---|---|
| Una vuelta del predictivo con 200 agentes listos (30 % de contacto) | 560 llamadas lanzadas en 0,28 s |
| 220 clientes contestando al mismo instante | 200 asignados y 20 en espera en 3,5 s, ningún agente con dos llamadas |
| Pantalla de supervisión (200 agentes) | agentes 32 ms, campañas 12 ms, resumen 37 ms |
| Reportes de 1 día (200 agentes, 20 mil llamadas) | agentes 129 ms, campañas 31 ms, disposiciones 25 ms, cumplimiento 280 ms |
| Reportes de 7 días (560 mil tramos, 140 mil llamadas) | agentes 293 ms, campañas 50 ms, disposiciones 36 ms, cumplimiento 1,3 s |

Lectura: 220 contestando **en el mismo instante** es el peor caso teórico. En
la operación real, con 200 agentes y conversaciones de unos 2 minutos,
contestan del orden de 2 clientes por segundo y la capacidad medida es de
unos 60 por segundo. El margen frente al temporizador de abandono (2 s) es
amplio.

Correr de nuevo (contra una base de PRUEBA, siembra datos):

```
cd backend
DATABASE_URL=postgresql+asyncpg://…/nspbx_carga python -m carga.prueba_carga --agentes 200 --dias 7
```

En CI corre una versión liviana (`tests/test_carga.py`, 40 agentes) que
comprueba la corrección bajo carga y atrapa regresiones de orden de magnitud.

## 4. Varios FreeSWITCH (opción A: cada empresa en un servidor)

### Capacidad de un servidor

Lo que se midió arriba es el backend y la base. FreeSWITCH no se pudo medir
acá (no hay uno real en este ambiente). Estimación para 200 agentes en
predictivo: hasta unos 600 canales de clientes en el pico (nivel 3) + 200 de
agentes en conferencia + 200 grabaciones. Un FreeSWITCH en un servidor de 8
núcleos lo soporta; hay que confirmarlo con `scripts/medir-recursos.sh` en una
prueba con llamadas reales antes del piloto. **Objetivo: 200 agentes por
servidor** (`capacidad_agentes`, editable por servidor).

Para pasar de un servidor se eligió la opción A:

| | A. Empresas repartidas por servidor (**implementada**) | B. Proxy SIP delante de varios FreeSWITCH |
|---|---|---|
| Cómo | Cada empresa vive en un FreeSWITCH; el backend elige el servidor por empresa | Kamailio u OpenSIPS recibe todo y reparte; los FreeSWITCH comparten registros |
| Escala | Por empresas (una empresa no puede pasar de un servidor: 200 agentes) | Dentro de una empresa también |
| Esfuerzo | Medio | Alto |

Si algún día una sola empresa pasa de 200 agentes, ahí toca B.

### Cómo funciona

- **Principal y adicionales.** El principal es el de siempre (`FS_ESL_HOST`
  o Ajustes). Los adicionales se dan de alta en **Empresas → Servidores
  FreeSWITCH** (panel y app; solo la plataforma), con su ESL (la clave se
  guarda cifrada) y su dirección SIP. Sin adicionales nada cambia.
- **Cada empresa en uno** (`tenants.nodo_id`; vacío = el principal). Cada
  comando a FreeSWITCH va al servidor de la empresa: el marcador, clic para
  llamar, la consola del agente, la supervisión, colgar las salientes de una
  empresa, las colas. `services/nodos.py` guarda el directorio en memoria
  (30 s; al cambiar algo se invalida en todas las réplicas por el bus).
- **Eventos.** La réplica líder abre una conexión de eventos con cada
  servidor. Lo que se hace al procesar un evento va al servidor que lo mandó.
  Si se cae la conexión con uno, el tablero en vivo descarta solo sus
  llamadas; los demás siguen.
- **Lo de la plataforma llega a todos**: recargar la configuración
  (`reloadxml`), colgar las huérfanas del predictivo al tomar el liderazgo,
  cortar una extensión. Un servidor caído no impide que los demás lo reciban.
- **El tope de canales de la plataforma** (`MAX_CONCURRENT_CALLS_GLOBAL`)
  protege la troncal compartida, así que se compara con la suma de canales de
  todos los servidores. Si el principal no responde no se marca (como antes);
  un adicional caído no suma (sus empresas tampoco pueden marcar).
- **Desactivar un servidor** lo saca de servicio: sus empresas pasan a usar el
  principal en el acto (para mantenimiento o si se cae del todo).

### Mover una empresa de servidor

Empresas → la columna **Servidor** (en la app: la empresa → Servidor
FreeSWITCH). Al mover:

1. Si tiene agentes conectados, pide confirmar: sus sesiones se cierran en el
   servidor anterior (sus llamadas en curso se cuelgan) y vuelven a entrar.
   Hacerlo fuera de la jornada.
2. Sus troncales pasan a la carpeta del servidor nuevo y se recargan los dos
   (`sofia profile external rescan`).
3. **Falta a mano:** el DNS del dominio SIP de la empresa tiene que apuntar a
   la dirección SIP del servidor nuevo, para que sus teléfonos y softphones se
   registren ahí. Mientras el DNS no cambie, sus teléfonos siguen en el
   anterior y no reciben llamadas del nuevo.

Un servidor con empresas no se puede borrar: primero se mueven.

### Desplegar un servidor adicional

Todos los FreeSWITCH usan la misma configuración; lo único propio de cada uno
son sus troncales.

1. **Configuración compartida.** `freeswitch/conf` (la que escribe el
   backend) se monta en el servidor nuevo por NFS, de solo lectura salvo la
   carpeta de troncales. El dialplan, los usuarios y las colas ya los sirve el
   backend por `xml_curl`: el `xml_curl.conf.xml` del servidor nuevo apunta al
   mismo backend con el mismo `FS_XML_SECRET`.
2. **Troncales del servidor.** Las del principal están en
   `sip_profiles/external/`; las de un adicional en
   `FS_CONF/nodos/<nombre>/sip_profiles/external/`. En el servidor nuevo se
   monta esa carpeta como su `sip_profiles/external`. El backend la crea al
   dar de alta el servidor y la reconcilia al arrancar.
3. **Grabaciones y sonidos compartidos.** `freeswitch/recordings` también va
   por NFS al mismo lugar (`/var/lib/freeswitch/recordings`): el backend las
   sirve, las retiene y las borra desde una sola carpeta. Igual los audios de
   los voizbots y las colas.
4. **ESL.** `event_socket.conf.xml` con la clave que se carga en el panel y
   un ACL que solo acepte al backend. El puerto 8021 nunca abierto a
   internet.
5. **CDR.** `xml_cdr` apunta al mismo `/fs/cdr` del backend, como el
   principal.
6. **Alta en el panel.** Empresas → Servidores FreeSWITCH → + Servidor. Con
   **Probar** se verifica la conexión antes de mover empresas.
7. **Mover empresas** y cambiar su DNS (arriba).

Repartir: llenar cada servidor hasta unos 160 agentes (80 %) y dejar margen
para que crezcan sin moverlas en plena operación. El panel marca en rojo un
servidor que pasa del 90 %.

## 5. Particionar `estados_agente` y `call_logs` (no hace falta todavía)

Con 200 agentes son unos 30 millones de tramos al año. Con los índices de la
revisión 0017 los reportes de una semana tardan décimas de segundo.
Particionar hoy tiene costo real: `call_logs.uuid` es único, y en Postgres una
restricción única en una tabla particionada tiene que incluir la columna de
partición; además hay claves foráneas que la apuntan.

Cuándo hacerlo: cuando `estados_agente` pase de unos 100 millones de filas, o
cuando la retención exija borrar meses enteros rápido (un `DROP` de partición
en vez de un `DELETE` masivo). El procedimiento: tabla nueva particionada por
mes en `inicio` / `started_at`, copia por lotes, cambio de nombre en una
ventana de mantenimiento, y `uuid` único por (`uuid`, `started_at`).
