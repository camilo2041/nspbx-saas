from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import permissions
from app.core.auth import requiere
from app.core.clock import now_local
from app.core.database import get_session
from app.models import AiCallUsage, Appointment
from app.schemas import (
    AgentBookRequest,
    AgentCancelRequest,
    AgentRescheduleRequest,
    AppointmentCreate,
    AppointmentOut,
    AppointmentUpdate,
)
from app.services.ajustes import ajustes_de
from app.services.appointments import (
    available_slots,
    find_next_appointment,
    is_slot_free,
    parse_date,
    parse_time,
)

router = APIRouter(prefix="/api/appointments", tags=["appointments"])

# Las rutas /agent/* de más abajo NO llevan este guardia: las llama el
# voizbot con el secreto compartido de Ajustes, no una persona con sesión.
_GESTION = Depends(requiere(permissions.CITAS_GESTIONAR))


# ---------- Administración (usada por la app) ----------


@router.get("/gestion", dependencies=[_GESTION])
async def gestion(days: int = 30, session: AsyncSession = Depends(get_session)):
    """Qué hizo cada llamada del voizbot sobre la agenda — confirmó,
    canceló o reagendó, y para cuándo — en vez de solo el estado actual
    de cada cita, que no dice nada sobre cómo se llegó ahí ni deja rastro
    de lo que pasó en una gestión que después se volvió a mover."""
    desde = now_local() - timedelta(days=days)
    result = await session.execute(
        select(AiCallUsage)
        .where(AiCallUsage.action.is_not(None), AiCallUsage.started_at >= desde)
        .order_by(AiCallUsage.started_at.desc())
    )
    return [
        {
            "id": f.id,
            "phone": f.phone,
            "action": f.action,
            "patient_name": f.action_patient_name,
            "appointment_date": f.action_appointment_date,
            "appointment_id": f.appointment_id,
            "called_at": f.started_at,
        }
        for f in result.scalars().all()
    ]


@router.get("", response_model=list[AppointmentOut], dependencies=[_GESTION])
async def list_appointments(
    day: str | None = None,
    search: str | None = None,
    estado: str | None = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
):
    """Antes devolvía la agenda ENTERA en cada carga, sin tope: en un
    consultorio real son miles de filas viajando y dibujándose de una,
    y no había forma de buscar a un paciente salvo con Ctrl+F. Ahora se
    pagina y se puede filtrar por nombre/teléfono y por estado.

    Se ordena por fecha DESCENDENTE (antes ascendente): con paginación,
    la primera página tiene que traer lo más cercano en el tiempo, no
    las citas más viejas del historial.
    """
    query = select(Appointment)
    if day:
        d = parse_date(day)
        start = datetime.combine(d, datetime.min.time())
        end = datetime.combine(d, datetime.max.time())
        query = query.where(Appointment.appointment_date >= start, Appointment.appointment_date <= end)
    if search:
        like = f"%{search.strip()}%"
        query = query.where((Appointment.patient_name.ilike(like)) | (Appointment.phone.ilike(like)))
    if estado:
        query = query.where(Appointment.status == estado)
    query = query.order_by(Appointment.appointment_date.desc()).limit(min(limit, 500)).offset(max(0, offset))
    result = await session.execute(query)
    return result.scalars().all()


@router.post("", response_model=AppointmentOut, status_code=status.HTTP_201_CREATED, dependencies=[_GESTION])
async def create_appointment(payload: AppointmentCreate, session: AsyncSession = Depends(get_session)):
    if not await is_slot_free(session, payload.appointment_date, payload.duration_minutes):
        raise HTTPException(status_code=409, detail="Ese horario ya está ocupado")
    appt = Appointment(**payload.model_dump())
    session.add(appt)
    await session.commit()
    await session.refresh(appt)
    return appt


@router.put("/{appointment_id}", response_model=AppointmentOut, dependencies=[_GESTION])
async def update_appointment(appointment_id: int, payload: AppointmentUpdate, session: AsyncSession = Depends(get_session)):
    appt = await session.get(Appointment, appointment_id)
    if not appt:
        raise HTTPException(status_code=404, detail="Cita no encontrada")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(appt, field, value)
    await session.commit()
    await session.refresh(appt)
    return appt


@router.delete("/{appointment_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_GESTION])
async def delete_appointment(appointment_id: int, session: AsyncSession = Depends(get_session)):
    appt = await session.get(Appointment, appointment_id)
    if not appt:
        raise HTTPException(status_code=404, detail="Cita no encontrada")
    await session.delete(appt)
    await session.commit()


@router.get("/availability", dependencies=[_GESTION])
async def get_availability(day: str, session: AsyncSession = Depends(get_session)):
    try:
        d = parse_date(day)
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de fecha inválido, usa YYYY-MM-DD")
    return {"date": day, "slots": await available_slots(session, d)}


# ---------- Herramientas para el agente de IA (ElevenLabs Conversational AI) ----------
# Autenticadas con un secreto compartido (Ajustes → Secreto del agente),
# no con las cookies/sesión de la app — estos endpoints los llama
# directamente la plataforma de IA, no un navegador logueado.


async def _check_agent_secret(session: AsyncSession, x_agent_secret: str | None) -> None:
    row = await ajustes_de(session)
    expected = row.agent_webhook_secret if row else None
    if not expected:
        raise HTTPException(status_code=503, detail="Configura primero el secreto del agente en Ajustes")
    if x_agent_secret != expected:
        raise HTTPException(status_code=401, detail="Secreto de agente inválido")


@router.get("/agent/availability")
async def agent_availability(
    day: str, session: AsyncSession = Depends(get_session), x_agent_secret: str | None = Header(default=None)
):
    await _check_agent_secret(session, x_agent_secret)
    try:
        d = parse_date(day)
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de fecha inválido, usa YYYY-MM-DD")
    slots = await available_slots(session, d)
    if not slots:
        return {"available": False, "message": f"No hay horarios libres el {day}."}
    return {"available": True, "slots": slots}


@router.post("/agent/book")
async def agent_book(
    payload: AgentBookRequest, session: AsyncSession = Depends(get_session), x_agent_secret: str | None = Header(default=None)
):
    await _check_agent_secret(session, x_agent_secret)
    try:
        start = datetime.combine(parse_date(payload.date), parse_time(payload.time))
    except ValueError:
        raise HTTPException(status_code=400, detail="Fecha u hora inválida (usa YYYY-MM-DD y HH:MM)")
    if start < now_local():
        return {"ok": False, "message": "Esa fecha/hora ya pasó."}
    if not await is_slot_free(session, start, payload.duration_minutes):
        return {"ok": False, "message": "Ese horario ya está ocupado, ofrece otro."}
    appt = Appointment(
        patient_name=payload.patient_name,
        phone=payload.phone,
        appointment_date=start,
        duration_minutes=payload.duration_minutes,
        notes=payload.notes,
        status="confirmed",
    )
    session.add(appt)
    await session.commit()
    await session.refresh(appt)
    return {"ok": True, "appointment_id": appt.id, "message": f"Cita confirmada para {payload.date} a las {payload.time}."}


@router.post("/agent/cancel")
async def agent_cancel(
    payload: AgentCancelRequest, session: AsyncSession = Depends(get_session), x_agent_secret: str | None = Header(default=None)
):
    await _check_agent_secret(session, x_agent_secret)
    on_date = parse_date(payload.date) if payload.date else None
    appt = await find_next_appointment(session, payload.phone, on_date)
    if not appt:
        return {"ok": False, "message": "No encontré una cita con ese número de teléfono."}
    appt.status = "cancelled"
    await session.commit()
    return {"ok": True, "message": "Cita cancelada."}


@router.post("/agent/reschedule")
async def agent_reschedule(
    payload: AgentRescheduleRequest, session: AsyncSession = Depends(get_session), x_agent_secret: str | None = Header(default=None)
):
    await _check_agent_secret(session, x_agent_secret)
    old_date = parse_date(payload.old_date) if payload.old_date else None
    appt = await find_next_appointment(session, payload.phone, old_date)
    if not appt:
        return {"ok": False, "message": "No encontré una cita con ese número de teléfono para reagendar."}
    try:
        new_start = datetime.combine(parse_date(payload.new_date), parse_time(payload.new_time))
    except ValueError:
        raise HTTPException(status_code=400, detail="Fecha u hora inválida (usa YYYY-MM-DD y HH:MM)")
    if not await is_slot_free(session, new_start, appt.duration_minutes):
        return {"ok": False, "message": "Ese nuevo horario ya está ocupado, ofrece otro."}
    appt.appointment_date = new_start
    await session.commit()
    return {"ok": True, "message": f"Cita reagendada para {payload.new_date} a las {payload.new_time}."}
