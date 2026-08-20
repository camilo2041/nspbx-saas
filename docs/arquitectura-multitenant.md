# Arquitectura multiempresa

Este documento define cómo pasa NSPBX de servir a **una** empresa a servir
a muchas, aisladas entre sí. Es la decisión que condiciona todo lo demás:
atención al cliente, ventas y cobranza se construyen encima, y si el
aislamiento se define mal, rehacerlo después implica tocar cada consulta
y cada archivo de configuración de FreeSWITCH.

## De dónde partimos

El sistema actual asume una sola empresa en todos lados:

| Punto | Estado hoy | Dónde |
|---|---|---|
| Tablas | 12 tablas, ninguna con `tenant_id` | `models/models.py` |
| Ajustes | fila única `id=1`, leída en **16 lugares** | `session.get(SystemSettings, 1)` |
| Configuración viva | singleton de proceso, **19 usos** en 7 archivos | `core/runtime_settings.py` |
| Dominio SIP | uno solo (`nspbx.local`) | `config_generator.py:25` |
| Dialplan | un contexto `default` + un `public` | `config_generator.py:433,452` |
| Extensiones | `user_context` fijo en `"default"` | `config_generator.py:39,42` |
| Endpoints de FreeSWITCH | ignoran los parámetros y devuelven **todo** | `services/xml_endpoints.py` |

Ese último punto es el más importante y el menos evidente. FreeSWITCH
**ya** pregunta por empresa: cuando resuelve un usuario manda
`tag_name=domain&key_name=name&key_value=nspbx.local`, y cuando resuelve
un destino manda el contexto. Hoy descartamos esos parámetros y
respondemos con el directorio y el dialplan completos. El mecanismo que
necesitamos ya existe del lado de FreeSWITCH; falta usarlo.

## La decisión central

**Un tenant es un dominio SIP más un contexto de dialplan.**

No es una convención nuestra: es la unidad de multiempresa nativa de
FreeSWITCH, y adoptarla nos evita inventar un aislamiento paralelo que
después pelee con el que el motor ya trae.

```
tenant 42  →  dominio  t42.pbx.ejemplo.com
           →  contexto ctx_t42
           →  troncales  t42_nscolombia, t42_pr
           →  colas      soporte@t42.pbx.ejemplo.com
```

De ahí sale sola la propiedad que más nos importa: **la extensión 1000 va
a existir en muchas empresas a la vez**. Hoy el dialplan hace coincidir
`^1000$` de forma global; con un contexto por tenant, cada 1000 vive en
el suyo y no hay ambigüedad posible. Sin contextos separados, la primera
empresa que cargue la extensión 1000 se queda con las llamadas de todas
las demás — y sería un fallo silencioso, porque el dialplan coincide sin
error.

## Capa de datos

Tres opciones reales:

| Opción | A favor | En contra |
|---|---|---|
| Base por tenant | aislamiento total | migraciones × N, conexiones × N, reportes cruzados imposibles |
| Esquema por tenant | buen aislamiento | migraciones × N, complejidad de conexión |
| **Una base + `tenant_id`** | una migración, un pool, reportes triviales | **una consulta sin filtrar filtra datos ajenos** |

Vamos por la tercera, pero **con Row-Level Security de Postgres**, que
convierte su única desventaja en un problema del motor y no de la
disciplina de quien escribe la consulta:

```sql
ALTER TABLE extensions ENABLE ROW LEVEL SECURITY;
ALTER TABLE extensions FORCE ROW LEVEL SECURITY;
CREATE POLICY p_tenant ON extensions
  USING (tenant_id = current_setting('app.tenant_id')::int);
```

Cada petición abre su transacción con `SET LOCAL app.tenant_id = ...`. A
partir de ahí, un `SELECT * FROM extensions` sin `WHERE` devuelve solo lo
del tenant activo. El día que alguien agregue un endpoint y olvide el
filtro —que va a pasar— no hay fuga.

Tres detalles que hacen que RLS funcione de verdad y que es fácil pasar
por alto. Los tres están implementados; se dejan escritos porque cada uno
falla **en silencio**:

- **La app no puede conectarse con el rol dueño.** El usuario que crea la
  imagen de Postgres es superusuario, y un superusuario se saltea las
  políticas siempre — ni siquiera `FORCE ROW LEVEL SECURITY` lo detiene.
  Por eso hay un rol `nspbx_app` aparte, y el arranque **verifica** que no
  sea superusuario ni tenga `BYPASSRLS` en vez de darlo por hecho.

- **`WITH CHECK` además de `USING`.** `USING` filtra lo que se lee;
  sin `WITH CHECK` se puede escribir con el `tenant_id` de otra empresa
  — insertar en la central ajena, que es peor que leerla.

- **`SET LOCAL` no sobrevive a un `commit`.** Dura lo que dura la
  transacción, y hay endpoints que hacen varios. La consulta siguiente
  abriría una transacción sin empresa fijada y las políticas no
  devolverían nada: listados vacíos, sin error, solo después del primer
  commit. Se resuelve con un enganche `after_begin` que reaplica el valor
  en cada transacción (`core/database.py`).

Y una consecuencia que hay que aceptar: el **login** no puede pasar por
RLS. Para saber de qué empresa es alguien hay que leer su fila en
`users`, que es justamente lo que está protegido. Se resuelve con la
sesión del dueño solo para esa consulta, y desde ahí la empresa viaja
firmada dentro del token — así el resto de las peticiones la conocen sin
volver a preguntar.

## Capa de FreeSWITCH

Es donde está el trabajo real.

### Directorio

`/fs/directory` pasa a leer `key_value` (el dominio que pregunta
FreeSWITCH), resolver el tenant y devolver **solo** sus extensiones,
dentro de `<domain name="{dominio del tenant}">`.

### Dialplan

`/fs/dialplan` pasa a leer el contexto pedido y generar solo ese. Cada
tenant recibe su `ctx_t<id>` con sus extensiones, sus bots, sus colas y
su ruta de salida.

### Entrantes

El contexto `public` sigue siendo uno solo —es donde caen las llamadas
del proveedor— pero deja de resolver destinos: mira el número marcado,
busca a qué tenant pertenece ese DID y transfiere a su contexto. Es el
único lugar donde el ruteo cruza empresas, y por eso conviene que sea
corto y esté cubierto por pruebas.

### Troncales

Los gateways son globales en el perfil `external`, así que los nombres
tienen que llevar prefijo (`t42_nscolombia`). Sin eso, dos empresas con
una troncal del mismo proveedor se pisan el nombre y la segunda no
registra.

### Colas

`mod_callcenter` ya nombra colas y agentes con el dominio
(`soporte@t42.pbx.ejemplo.com`), así que el aislamiento sale gratis en
cuanto el dominio sea por tenant. Hay que revisar `queues_sync.py`, que
hoy arma esos nombres con el singleton.

## El singleton

`runtime_settings` es un objeto de módulo: una configuración por
**proceso**. Con varias empresas eso deja de tener sentido, y es la parte
más mecánica y más extendida del cambio — 19 usos en 7 archivos.

Pasa a resolverse por petición: en la API, desde la sesión del usuario;
en los endpoints que consume FreeSWITCH, desde el dominio o el contexto
que viene en la consulta. Conviene hacerlo temprano, porque cada línea
nueva que se escriba contra el singleton es una línea más para migrar.

## Usuarios y acceso

`users` gana `tenant_id` y el token de sesión lo transporta. Aparece un
rol nuevo por encima de los actuales —el de la plataforma— que puede
crear empresas y entrar a cualquiera; todo lo demás queda encerrado en
la suya. Ese rol es el único que puede saltarse el filtro, así que su
manejo merece más cuidado que el resto del sistema junto.

## Orden de trabajo

Las dependencias mandan el orden:

1. **Tabla `tenants` + `tenant_id` en todas las tablas + RLS.** Base de
   todo. Migración de datos: lo existente pasa a ser el tenant 1.
2. **Sesión con tenant.** Sin esto no hay de dónde sacar el `SET LOCAL`.
3. **Ajustes por tenant y muerte del singleton.** Los 16 `SystemSettings, 1`
   y los 19 `runtime_settings`.
4. **FreeSWITCH: dominio y contexto por tenant**, endpoints por parámetro,
   troncales con prefijo, entrantes por DID.
5. **Recién ahí** los módulos de negocio: atención, ventas, cobranza.

Del 1 al 4 el sistema no gana ninguna función visible. Es tentador
adelantar el 5 porque es lo que se ve, pero cada módulo construido antes
del 4 hay que reescribirlo después.

## Cómo se prueba que el aislamiento funciona

No alcanza con revisar el código. Hace falta una prueba automática que
cree dos tenants con **la misma extensión 1000**, y verifique que:

- el directorio de cada dominio devuelve solo su 1000
- una llamada al 1000 en `ctx_t1` no puede terminar en el 1000 de `ctx_t2`
- un usuario del tenant 1 no ve ni una fila del tenant 2 en ninguna vista
- con el filtro de la aplicación deliberadamente quitado, RLS igual corta

Esa última es la que da confianza real: comprueba la red de seguridad, no
solo el camino feliz.
