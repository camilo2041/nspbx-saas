# Fase G: comprobar en vivo, fila sin espera y operación más tranquila

**Estado: hecha** (ver «Lo que se hizo» al final). Abajo, el plan tal como se
escribió para decidir el alcance. Sale de lo que quedó abierto al cerrar las
fases A a F (auditoría de funcionamiento) y de lo que todavía no se puede
saber sin llamadas reales.

Los bloques van por orden de prioridad. Cada uno dice qué problema resuelve,
qué se haría y cómo se sabe que quedó bien.

## G1. Prueba de humo contra la central real (prioridad alta)

**Problema.** Todo lo de FreeSWITCH de las fases A a F se probó con una
central simulada: transferencias, buzón, música y posición en la fila, IVR con
horario, aviso al celular, «hablar los tres». Un detalle de FreeSWITCH (una
variable, una tecla de att_xfer, un formato de `list members`) solo aparece
con llamadas de verdad, y hoy eso se descubre cuando falla con un cliente.

**Qué se haría.**
- Un comando `python -m app.humo` (y un botón en Plataforma › Diagnóstico) que,
  en una empresa de prueba, arma extensiones y un grupo temporales y hace
  llamadas `loopback/` con `originate`. Cada escenario se comprueba con los
  eventos de ESL y el CDR:
  - el buzón graba y llega el mensaje;
  - el grupo pone música, dice la posición y desborda;
  - el IVR va por «abierto» o «cerrado» según la hora;
  - la transferencia directa y la consultada (incluida la de tres) terminan
    con las patas correctas;
  - un número sin ruta queda en la lista de la plataforma.
- Un informe por escenario («pasó» o «falló en el paso X, se esperaba Y y
  llegó Z») y limpieza de todo lo temporal al terminar.

**Listo cuando.** El informe pasa completo en el servidor de producción, y
correrlo después de cada despliegue toma menos de 3 minutos.

## G2. Devolución de llamada desde la fila (prioridad alta)

**Problema.** Con picos de llamadas, quien espera mucho cuelga. El reporte de
entrantes ya mide ese abandono, pero no hay una salida para quien no quiere
seguir esperando.

**Qué se haría.**
- En la fila: «Para que te devolvamos la llamada sin perder tu turno, marca 1».
  Se confirma el número (el que llama u otro que marque) y la persona cuelga.
- La llamada queda en la fila como pendiente, en su lugar. Cuando le toca, la
  central llama primero al agente y después al cliente. Reutiliza los
  callbacks de agentes (`callbacks`) y el marcador.
- Un reporte de devoluciones: pedidas, hechas, contestadas y el tiempo hasta
  la devolución.

**Listo cuando.** Una prueba de humo (G1) pide la devolución, cuelga y recibe
la llamada con el agente ya en línea. El abandono del grupo baja en el reporte
de entrantes.

## G3. Tablero en vivo de los grupos (prioridad media)

**Problema.** Supervisión muestra agentes y campañas, pero no las filas de
entrada: no hay forma de ver cuántos esperan ahora, el que más lleva esperando
ni el nivel de servicio de la última hora.

**Qué se haría.**
- Foto de cada grupo cada pocos segundos (`callcenter_config queue list
  members` y `list agents`, en la líder). Se publica por el bus como la del
  predictivo.
- Una tarjeta por grupo en Supervisión y en el wallboard:
  - en espera y la espera más larga;
  - agentes libres, hablando y en pausa;
  - nivel de servicio y abandono de la última hora.
- Alerta en pantalla cuando la espera más larga pasa un umbral.

**Listo cuando.** Con 3 llamadas esperando en la prueba de humo, el tablero
las muestra en menos de 5 segundos.

## G4. Buzón de voz completo (prioridad media)

**Qué se haría.**
- Saludo propio de cada extensión, grabado desde el teléfono (`*98`) o subido
  en el panel. Hoy todos usan el saludo general.
- Escuchar los mensajes desde el teléfono con un PIN (`*97`).
- Transcripción del mensaje (Deepgram, si hay clave) en el correo y en la app.
- Aviso al celular de cada mensaje nuevo, con el número de mensajes sin
  escuchar en el ícono de la app.

**Listo cuando.** Un mensaje dejado en la prueba de humo llega transcrito por
correo y por aviso al celular.

## G5. Festivos y horarios especiales (prioridad media)

**Problema.** Los horarios de las rutas, del IVR y de las campañas son por día
de la semana. Un festivo se atiende como un día hábil.

**Qué se haría.**
- Calendario de festivos de Colombia precargado por año, más fechas propias de
  la empresa (cierre por inventario, horario de diciembre).
- Un festivo cuenta como «cerrado» en las rutas entrantes, en el bloque
  Horario del IVR y en el horario de marcación de las campañas, con su propio
  mensaje opcional.

**Listo cuando.** Una ruta de prueba va a «cerrado» un festivo dentro del
horario normal.

## G6. Calidad automática (prioridad media)

**Qué se haría.**
- Muestreo nocturno: la IA sugiere la evaluación de un porcentaje de las
  llamadas grabadas de cada agente (por ejemplo 5 al día). Quedan como «por
  revisar» para el supervisor, que confirma o corrige.
- Tendencia por agente y por criterio (semana contra semana).
- Tope de gasto de IA por día para el muestreo.

**Listo cuando.** Cada mañana hay sugerencias por revisar y el costo del día
aparece en Consumo IA.

## G7. Operación y respaldo (prioridad media-baja)

**Qué se haría.**
- Copia de los respaldos fuera del servidor (S3 o compatible) y una prueba de
  restauración mensual automática en una base temporal.
- Métricas para Prometheus o Grafana:
  - llamadas activas y canales por servidor;
  - registros SIP y estado de cada proveedor;
  - latencia de la API;
  - tamaño de la cola de webhooks.
- Tope compartido también para los intentos de inicio de sesión
  (`core/cupos.py`), si se pasa a dos réplicas.
- Un panel de fail2ban en Seguridad: IP bloqueadas y desbloqueo.

**Listo cuando.** La restauración de prueba corre sola y avisa si falla.

## G8. App móvil, segunda vuelta (prioridad baja)

**Qué se haría.**
- Consola de agente en la app: entrar o salir, pausas, disposición al colgar.
- Ficha de quien llama al sonar, como en el panel (fase C).
- Contador de mensajes sin escuchar en el menú (G4).

## Fuera de alcance, por ahora

- Video y pantalla compartida.
- WhatsApp o chat como canal (sería un producto aparte: bandeja omnicanal).
- Grabaciones cifradas en reposo. Conviene evaluarlo con la retención legal de
  cada cliente antes de construirlo.

## Orden sugerido

G1 primero: valida todo lo hecho y deja la red de seguridad para lo que sigue.
Después G2 y G3, que atacan juntos el abandono en la fila. Luego G4, G5 y G6
según lo que pidan los clientes, y G7 antes de pasar a dos réplicas o de sumar
empresas grandes.


## Lo que se hizo

| Bloque | Dónde | Notas |
|---|---|---|
| G1 | `services/humo.py`, `python -m app.humo`, Plataforma › Empresas › «Probar la central» | Central, proveedores, teléfonos, voces, número sin ruta, buzón y fila de un grupo. Las transferencias necesitan dos teléfonos: a mano. |
| G2 y G3 | `services/vigia_colas.py`, revisión 0026, Supervisión y wallboard | Devolución con la tecla 1 (`cc_exit_keys`); hasta 3 intentos. Tarjetas de grupos con alerta a los 2 min. |
| G4 | `config_generator` (*97, *98), `api/buzon.py` (saludo), revisión 0027 | Transcripción con Deepgram; aviso solo en Android (en iOS el token es de llamadas). Sin PIN: *97 escucha el buzón de la extensión que marca. |
| G5 | `services/festivos.py`, revisión 0028, Ajustes | «Cerrar en festivos» es opcional (apagado por defecto) para no cambiar de golpe lo que ya atiende. |
| G6 | `services/calidad_auto.py`, revisión 0029, Calidad | Las propuestas sin revisar no cuentan ni las ve el agente. El costo no se registra aparte en Consumo IA. |
| G7 | `services/operacion.py`, `core/metricas.py` | No se reimplementó la copia externa ni el simulacro: ya existen como scripts (cifrados y sin tocar producción); el panel muestra su estado y `/metrics` lo exporta. fail2ban sigue de solo lectura. El tope de inicio de sesión sigue por réplica. |
| G8 | App: Menú › Trabajar, ficha en la llamada, contador del buzón | El audio de la sala se contesta solo con el token de la sesión. |
