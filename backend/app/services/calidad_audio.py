"""Calidad del audio de cada llamada, con lo que mide FreeSWITCH.

Al colgar, FreeSWITCH deja en las variables del canal las estadísticas RTP
del audio que RECIBIÓ: `rtp_audio_in_mos` (1 a 5, la nota que daría una
persona), `rtp_audio_in_quality_percentage` y los paquetes recibidos y
perdidos. Se guardan en el CDR (api/calls.py) para responder «se escucha
mal» con datos: qué proveedor, qué agente, desde cuándo.

MOS de referencia: 4 o más, bien; de 3.5 a 4, aceptable; menos de 3.5, se
nota (cortes, robótico).
"""

from sqlalchemy import func, select

from app.models import CallLog, User

MOS_MALO = 3.5


def _num(valor) -> float | None:
    try:
        n = float(valor)
    except (TypeError, ValueError):
        return None
    return n if n == n else None  # NaN fuera


def de_cdr(variables: dict) -> dict:
    """Las columnas audio_* y troncal a partir de las variables del CDR."""
    mos = _num(variables.get("rtp_audio_in_mos"))
    calidad = _num(variables.get("rtp_audio_in_quality_percentage"))
    recibidos = _num(variables.get("rtp_audio_in_packet_count")) or 0
    perdidos = _num(variables.get("rtp_audio_in_skip_packet_count")) or 0
    perdida = round(perdidos * 100 / (recibidos + perdidos), 2) if (recibidos + perdidos) > 0 else None
    troncal = (variables.get("sip_gateway_name") or "").strip()[:100] or None
    return {
        "audio_mos": round(mos, 2) if mos is not None and 0 < mos <= 5 else None,
        "audio_calidad": round(calidad, 1) if calidad is not None and 0 <= calidad <= 100 else None,
        "audio_perdida": perdida,
        "troncal": troncal,
    }


async def resumen(session, ini, fin) -> dict:
    """Por proveedor y por agente: llamadas medidas, MOS promedio y % malas."""
    medida = CallLog.audio_mos.is_not(None)
    filtro = [CallLog.started_at >= ini, CallLog.started_at < fin, medida]
    malas = func.count().filter(CallLog.audio_mos < MOS_MALO)

    def filas(grupo):
        return select(grupo, func.count(), func.avg(CallLog.audio_mos), malas, func.avg(CallLog.audio_perdida)).where(*filtro).group_by(grupo)

    def salida(clave, n, mos, n_malas, perdida):
        return {"clave": clave, "llamadas": n, "mos": round(float(mos), 2) if mos is not None else None,
                "malas": n_malas, "malas_pct": round(n_malas * 100 / n, 1) if n else 0,
                "perdida_pct": round(float(perdida), 2) if perdida is not None else None}

    total = (await session.execute(select(func.count(), func.avg(CallLog.audio_mos), malas, func.avg(CallLog.audio_perdida)).where(*filtro))).one()
    por_troncal = [salida(t or "Interna (sin proveedor)", *rest) for t, *rest in (await session.execute(filas(CallLog.troncal))).all()]
    nombres = {u.id: u.full_name for u in (await session.execute(select(User))).scalars().all()}
    por_agente = [
        salida(nombres.get(a, f"Agente {a}"), *rest)
        for a, *rest in (await session.execute(filas(CallLog.agente_id))).all()
        if a is not None
    ]
    orden = lambda xs: sorted(xs, key=lambda x: (x["mos"] is None, x["mos"] or 0))  # noqa: E731
    return {"total": salida("Todas", *total), "por_troncal": orden(por_troncal), "por_agente": orden(por_agente), "mos_malo": MOS_MALO}
