"""Tope diario de cada campaña: llamadas lanzadas y minutos por troncal.

Una campaña mal cargada (la lista equivocada, un reintento de más) o un
voizbot que se cuelga en bucle puede gastar en un día lo que debía durar
un mes. Cada campaña puede fijar cuántas llamadas lanza por día y cuántos
minutos por troncal gasta por día; al llegar, espera al día siguiente sin
dar números por fallidos.

- Llamadas: las cuenta el marcador al lanzarlas (Campaign.calls_today), así
  que el tope es exacto e inmediato.
- Minutos: salen de los CDR, que traen la campaña (nspbx_campaign_id). Como
  el cupo diario de la empresa, cuentan las llamadas terminadas; las que
  están en curso las acota la concurrencia de la campaña.

"Hoy" es el día del negocio (`now_local`), el mismo de los demás cupos.
"""

from datetime import date

from sqlalchemy import func, select

from app.models import CallLog, Campaign


def llamadas_hoy(c: Campaign, hoy: date) -> int:
    return c.calls_today if c.calls_today_date == hoy else 0


def contar_lanzadas(c: Campaign, hoy: date, cantidad: int) -> None:
    if c.calls_today_date != hoy:
        c.calls_today, c.calls_today_date = 0, hoy
    c.calls_today += cantidad


async def minutos_hoy(session, campaign_ids) -> dict[int, float]:
    from app.services.salientes import inicio_del_dia_utc

    ids = list(campaign_ids)
    if not ids:
        return {}
    filas = (await session.execute(
        select(CallLog.campaign_id, func.coalesce(func.sum(CallLog.billsec), 0))
        .where(CallLog.campaign_id.in_(ids), CallLog.via_trunk.is_(True), CallLog.started_at >= inicio_del_dia_utc())
        .group_by(CallLog.campaign_id)
    )).all()
    return {cid: segundos / 60 for cid, segundos in filas}


def disponibles(c: Campaign, hoy: date, minutos: float) -> tuple[int | None, str | None]:
    """(cuántas llamadas puede lanzar todavía hoy —None = sin tope—, motivo
    si ya no puede ninguna)."""
    if c.max_minutes_per_day and minutos >= c.max_minutes_per_day:
        return 0, f"Llegó a su tope de {c.max_minutes_per_day} minutos de hoy; sigue mañana"
    if c.max_calls_per_day:
        quedan = c.max_calls_per_day - llamadas_hoy(c, hoy)
        if quedan <= 0:
            return 0, f"Llegó a su tope de {c.max_calls_per_day} llamadas de hoy; sigue mañana"
        return quedan, None
    return None, None
