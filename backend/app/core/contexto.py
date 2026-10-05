"""Contexto de la tarea en curso: de qué empresa es y, si viene de un evento
de FreeSWITCH, de qué servidor (services/nodos.py).

Lo leen los comandos a FreeSWITCH para saber a qué servidor ir sin que cada
llamada tenga que pasarlo a mano. Las tareas que se crean adentro (asyncio)
heredan el contexto de quien las crea.
"""

from contextvars import ContextVar

# Empresa de la petición o de la sesión de empresa abierta (core/database.py).
empresa_actual: ContextVar[int | None] = ContextVar("empresa_actual", default=None)
# Servidor del que llegó el evento que se está procesando. Gana sobre la
# empresa: lo que se haga con ese canal tiene que ir adonde vive el canal.
nodo_del_evento: ContextVar[int | None] = ContextVar("nodo_del_evento", default=None)
# Distingue «sin evento» de «evento del servidor principal» (cuyo id es None).
hay_evento: ContextVar[bool] = ContextVar("hay_evento", default=False)
