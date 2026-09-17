"""Lógica de agenda: horario de atención fijo + cálculo de huecos libres.

Horario simple por ahora (lunes a sábado, 8:00-18:00, turnos de 30 min) —
si se necesita configurar por día/feriados, esto es lo primero que habría
que hacer configurable desde Ajustes.

Las horas de acá son hora LOCAL del negocio; el "ahora" se toma de
`now_local()` y nunca de `utcnow()` (ver app/core/clock.py)."""

from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now_local
from app.models import Appointment

BUSINESS_START = time(8, 0)
BUSINESS_END = time(18, 0)
SLOT_MINUTES = 30
CLOSED_WEEKDAY = 6  # domingo (Monday=0 ... Sunday=6)


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def parse_time(value: str) -> time:
    return datetime.strptime(value, "%H:%M").time()


async def get_appointments_on(
    session: AsyncSession, day: date, tenant_id: int | None = None
) -> list[Appointment]:
    start = datetime.combine(day, time.min)
    end = datetime.combine(day, time.max)
    query = select(Appointment).where(
        Appointment.appointment_date >= start,
        Appointment.appointment_date <= end,
        Appointment.status == "confirmed",
    )
    if tenant_id is not None:
        query = query.where(Appointment.tenant_id == tenant_id)
    result = await session.execute(query)
    return list(result.scalars().all())


async def available_slots(session: AsyncSession, day: date, tenant_id: int | None = None) -> list[str]:
    if day.weekday() == CLOSED_WEEKDAY:
        return []
    booked = await get_appointments_on(session, day, tenant_id)
    busy_ranges = [(a.appointment_date, a.appointment_date + timedelta(minutes=a.duration_minutes)) for a in booked]

    slots: list[str] = []
    cursor = datetime.combine(day, BUSINESS_START)
    end_of_day = datetime.combine(day, BUSINESS_END)
    now = now_local()
    while cursor + timedelta(minutes=SLOT_MINUTES) <= end_of_day:
        slot_end = cursor + timedelta(minutes=SLOT_MINUTES)
        if cursor > now and not any(cursor < b_end and slot_end > b_start for b_start, b_end in busy_ranges):
            slots.append(cursor.strftime("%H:%M"))
        cursor = slot_end
    return slots


def business_hours_error(start: datetime, duration_minutes: int = SLOT_MINUTES) -> str | None:
    """Devuelve el motivo por el que NO se puede agendar en ese momento, o
    None si es válido.

    El horario y el cierre dominical solo vivían como instrucciones del
    prompt, así que dependían de que el modelo obedeciera: bastaba una
    alucinación para dejar una cita el domingo a las 3 de la mañana en la
    base. Las reglas del negocio se validan acá, del lado del código.

    El texto devuelto se le entrega al modelo como resultado de la
    herramienta, así que está escrito para que pueda leerlo en voz alta."""
    if start < now_local():
        return "Esa fecha y hora ya pasaron."
    if start.weekday() == CLOSED_WEEKDAY:
        return "El consultorio no atiende los domingos."
    fin = start + timedelta(minutes=duration_minutes)
    if start.time() < BUSINESS_START:
        return f"La atención empieza a las {BUSINESS_START.strftime('%H:%M')}."
    if fin.date() > start.date() or fin.time() > BUSINESS_END:
        return f"La atención termina a las {BUSINESS_END.strftime('%H:%M')}."
    return None


async def find_next_appointment(
    session: AsyncSession,
    phone: str,
    on_date: date | None = None,
    tenant_id: int | None = None,
) -> Appointment | None:
    # Coincidencia por los últimos 10 dígitos, no por igualdad exacta: el
    # mismo teléfono llega distinto según de dónde venga la llamada
    # ("3011321381", "573011321381", "+57 301 132 1381"), y una comparación
    # exacta hacía que el bot no encontrara la cita del paciente.
    digits = "".join(c for c in phone if c.isdigit())
    suffix = digits[-10:] if len(digits) >= 10 else digits

    query = select(Appointment).where(Appointment.status == "confirmed")
    if tenant_id is not None:
        # Con la sesión del DUEÑO (voizbot) no hay RLS que filtre: sin esto
        # el bot encontraría las citas de CUALQUIER empresa para un número.
        query = query.where(Appointment.tenant_id == tenant_id)
    if suffix:
        query = query.where(Appointment.phone.like(f"%{suffix}"))
    else:
        query = query.where(Appointment.phone == phone)
    if on_date:
        start = datetime.combine(on_date, time.min)
        end = datetime.combine(on_date, time.max)
        query = query.where(Appointment.appointment_date >= start, Appointment.appointment_date <= end)
    else:
        query = query.where(Appointment.appointment_date >= now_local())
    query = query.order_by(Appointment.appointment_date)
    result = await session.execute(query)
    return result.scalars().first()


async def is_slot_free(
    session: AsyncSession, start: datetime, duration_minutes: int, tenant_id: int | None = None
) -> bool:
    day_appts = await get_appointments_on(session, start.date(), tenant_id)
    end = start + timedelta(minutes=duration_minutes)
    for a in day_appts:
        a_end = a.appointment_date + timedelta(minutes=a.duration_minutes)
        if start < a_end and end > a.appointment_date:
            return False
    return True
