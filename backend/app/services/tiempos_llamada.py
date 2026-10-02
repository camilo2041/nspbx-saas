"""Tiempos de una llamada a partir de las variables del CDR de FreeSWITCH.

Cada tramo va por separado (ver CallLog): mezclarlos en `duration` pierde
justo lo que se necesita para medir una troncal (setup), el marcador
predictivo (ring) o a un agente (espera).

    start ──setup──▶ progress (timbra) ──ring──▶ answer ──…──▶ end

FreeSWITCH entrega las marcas en microsegundos (`*_uepoch`, "0" si no
ocurrieron). Una llamada que entra con audio temprano sin 180 trae
`progress_media_uepoch` y no `progress_uepoch`: cuenta la primera de las dos.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Tiempos:
    progress_at: datetime | None
    setup_ms: int | None
    ring_ms: int | None
    espera_ms: int | None
    colgo: str | None


def _us(variables: dict, clave: str) -> int | None:
    try:
        valor = int(variables.get(clave) or 0)
    except (TypeError, ValueError):
        return None
    return valor if valor > 0 else None


def _ms(desde: int | None, hasta: int | None) -> int | None:
    if desde is None or hasta is None or hasta < desde:
        return None
    return (hasta - desde) // 1000


# sip_hangup_disposition: recv_* = colgó el otro extremo de ESTE canal;
# send_* = colgó FreeSWITCH (por el otro lado de la llamada o por sí mismo).
# En un canal entrante el otro extremo es quien llama; en uno saliente, el
# llamado.
_RECIBIDO = {"recv_bye", "recv_cancel", "recv_refuse"}
_ENVIADO = {"send_bye", "send_cancel", "send_refuse"}


def _quien_colgo(variables: dict) -> str | None:
    disp = (variables.get("sip_hangup_disposition") or "").strip().lower()
    if disp not in _RECIBIDO | _ENVIADO:
        return None
    entrante = variables.get("direction") == "inbound"
    remoto = "llamante" if entrante else "llamado"
    local = "llamado" if entrante else "llamante"
    return remoto if disp in _RECIBIDO else local


def calcular(variables: dict) -> Tiempos:
    inicio = _us(variables, "start_uepoch")
    marcas_timbre = [m for m in (_us(variables, "progress_uepoch"), _us(variables, "progress_media_uepoch")) if m]
    timbre = min(marcas_timbre) if marcas_timbre else None
    contesta = _us(variables, "answer_uepoch")
    fin = _us(variables, "end_uepoch")

    if timbre is not None:
        setup = _ms(inicio, timbre)
        ring = _ms(timbre, contesta or fin)
    else:
        # Sin señal de timbre (una extensión que contesta en el acto, un
        # IVR): no hay setup que medir y el ring es lo que tardó en contestar.
        setup = None
        ring = _ms(inicio, contesta)

    espera = _us(variables, "hold_accum_usec")
    if espera is None:
        try:
            segundos = int(variables.get("hold_accum_seconds") or 0)
        except (TypeError, ValueError):
            segundos = 0
        espera_ms = segundos * 1000 if segundos > 0 else None
    else:
        espera_ms = espera // 1000

    return Tiempos(
        progress_at=datetime.utcfromtimestamp(timbre / 1_000_000) if timbre else None,
        setup_ms=setup,
        ring_ms=ring,
        espera_ms=espera_ms,
        colgo=_quien_colgo(variables),
    )
