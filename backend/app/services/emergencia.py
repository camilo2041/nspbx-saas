"""Cortar llamadas EN CURSO: el control de emergencia ante un fraude.

Pausar las salientes (de una empresa o de toda la plataforma) frena las
llamadas NUEVAS; las que ya estaban hablando seguían hasta la duración
máxima — con un fraude a destinos internacionales, eso es justo lo que
se factura. Acá se cuelgan.

Cómo: toda llamada que sale por una troncal lleva marcada su empresa en la
variable de canal `nspbx_saliente` (el dialplan de salida, el marcador de
campañas y el clic para llamar; ver config_generator, dialer y
extensions), y la extensión que la originó en `nspbx_saliente_ext`.
`hupall <causa> <variable> <valor>` cuelga en FreeSWITCH todos los canales
con esa marca y ninguno más: ni las internas ni las entrantes, ni las de
otra empresa. Colgar es asíncrono: puede tardar unos segundos.
"""

import logging

from app.core import validacion
from app.services import esl

logger = logging.getLogger(__name__)

# Queda en el CDR (hangup_cause): se distingue de un corte del proveedor.
CAUSA = "MANAGER_REQUEST"


async def colgar_salientes(tenant_ids) -> list[int]:
    """Cuelga las salientes en curso de esas empresas. Lanza si FreeSWITCH
    no responde: quien lo pide tiene que enterarse de que no se cortó."""
    hechas = []
    for tid in tenant_ids:
        await esl.api(f"hupall {CAUSA} nspbx_saliente {int(tid)}", tenant_id=int(tid))
        hechas.append(int(tid))
    logger.warning("Salientes EN CURSO colgadas: empresas %s", hechas)
    return hechas


async def cortar_extension(numero: str, dominio: str) -> None:
    """Extensión desactivada o borrada (p. ej. su clave se filtró): se
    cuelgan sus salientes en curso y se tira su registro. Sin esto, el
    teléfono (o el atacante) seguía registrado y hablando hasta que vencía
    el registro o la llamada."""
    validacion.exigir(validacion.EXTENSION_RE, numero, "Extensión")
    validacion.exigir(validacion.HOST_RE, dominio, "Dominio")
    usuario = f"{numero}@{dominio}"
    # En todos los servidores: el teléfono pudo quedar registrado en otro
    # (p. ej. antes de mover la empresa). Donde no está, no hace nada.
    await esl.api_todos(f"hupall {CAUSA} nspbx_saliente_ext {usuario}")
    await esl.api_todos(f"sofia profile internal flush_inbound_reg {usuario}")
    logger.warning("Extensión %s cortada: salientes en curso colgadas y registro eliminado", usuario)
