"""Llamadas que entran por una troncal a un número sin ruta de entrada.

El dialplan las cuelga (config_generator `no_route`, UNALLOCATED_NUMBER) y
marca el canal con `nspbx_sin_ruta`. El CDR llega acá: no se guarda como
llamada de ninguna empresa (antes caía en la primera de la instalación) sino
como un número sin ruta, agrupado por número, para que la plataforma vea
«al 6015551234 entraron 12 llamadas y no hay ruta». Si la troncal es de una
empresa (gateway `<slug>_<nombre>`, services/gateways.py), esa empresa
recibe un aviso (services/alertas.py).
"""

import re
from datetime import datetime

from sqlalchemy.dialects.postgresql import insert

from app.models import NumeroSinRuta

_LIMPIO = re.compile(r"[^0-9A-Za-z+*#@._-]")


def _limpio(valor, largo: int = 64) -> str | None:
    v = _LIMPIO.sub("", str(valor or ""))[:largo]
    return v or None


async def registrar(session, variables: dict) -> str | None:
    """Suma la llamada al número (sin commit). Devuelve el número."""
    numero = _limpio(variables.get("destination_number")) or _limpio(variables.get("sip_req_user"))
    if not numero:
        return None
    ahora = datetime.utcnow()
    datos = {
        "numero": numero,
        "para": _limpio(variables.get("sip_to_user")),
        "origen": _limpio(variables.get("caller_id_number") or variables.get("sip_from_user")),
        "troncal": _limpio(variables.get("sip_gateway_name") or variables.get("sip_gateway"), 120),
        "veces": 1,
        "primera_vez": ahora,
        "ultima_vez": ahora,
    }
    stmt = insert(NumeroSinRuta).values(**datos)
    stmt = stmt.on_conflict_do_update(
        index_elements=[NumeroSinRuta.numero],
        set_={
            "veces": NumeroSinRuta.veces + 1,
            "ultima_vez": ahora,
            "origen": stmt.excluded.origen,
            "para": stmt.excluded.para,
            "troncal": stmt.excluded.troncal,
        },
    )
    await session.execute(stmt)
    return numero


def empresa_de_troncal(troncal: str | None, slugs: dict[int, str]) -> int | None:
    """La empresa dueña del gateway `<slug>_<nombre>` (el slug más largo que
    calce, por si uno es prefijo de otro)."""
    if not troncal:
        return None
    candidatas = [(len(s), tid) for tid, s in slugs.items() if s and troncal.startswith(f"{s}_")]
    return max(candidatas)[1] if candidatas else None
