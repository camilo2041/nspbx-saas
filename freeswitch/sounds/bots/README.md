# Audios de los voizbots

Acá caen los archivos que el panel genera o sube para cada bot: el saludo
inicial, el audio de cada nodo del flujo y los "whisper" de transferencia.
Los escribe el backend (ver `app/services/greetings.py` y
`app/services/flow_engine.py`) y los reproduce FreeSWITCH.

La carpeta viaja vacía a propósito: los audios son contenido de cada
cliente, no del producto.

## `saludo_inicial.wav`

Es el único con nombre fijo y conviene reponerlo pronto. El dialplan lo
reproduce apenas descuelgan y después espera 1,8 s antes de arrancar el
menú, para no pisar el "aló" de quien contesta — en una llamada humana
nadie empieza a hablar en el instante exacto en que levantan.

`flow_engine.py` comprueba `SALUDO_INICIAL.exists()` y, si no está, se
saltea **tanto el audio como la pausa**. No falla ni deja rastro en el
log: el menú simplemente arranca encima del saludo del otro y las
primeras palabras se pierden. Si alguien reporta que "el bot atropella al
que contesta", empezá mirando si este archivo existe.
