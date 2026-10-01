"""API pública, versión 1 — para integrar sistemas de la empresa.

Se autentica con una clave de API (`Authorization: Bearer nspbx_…` o
`X-API-Key`), nunca con la sesión del panel; ver core/claves_api.py. Cada
endpoint exige un permiso de la clave. Lo que hace cada uno es lo mismo que
el endpoint equivalente del panel (mismas validaciones, misma política de
salientes), reutilizándolo: la API no es una puerta trasera con reglas
propias.

Versionada: un cambio incompatible va a /api/v2, y /api/v1 sigue
respondiendo igual mientras haya integraciones que lo usen.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import appointments as appointments_api, campaigns as campaigns_api
from app.core.claves_api import requiere_scope
from app.core.database import filtro_empresa, get_session
from app.models import Appointment, CallLog, Tenant
from app.schemas import AppointmentCreate, AppointmentOut, CampaignNumberIn
from app.services import consumo

router = APIRouter(prefix="/api/v1", tags=["api-v1"])


async def _operativa(request: Request, session: AsyncSession, modulo: str | None = None) -> None:
    """Lo que en el panel hacen `requiere_modulo` y `licencia_operativa`."""
    from app.services.licensing import estado, obtener

    tenant_id = request.state.api_key.tenant_id
    if modulo:
        ten = await session.get(Tenant, tenant_id)
        if not ten or not ten.has_module(modulo):
            raise HTTPException(status_code=403, detail="La empresa no tiene este módulo activo")
    st = estado(await obtener(session, tenant_id))
    if st != "ok":
        raise HTTPException(status_code=402, detail=f"La licencia de la empresa está {st}")


def _llamada(c: CallLog) -> dict:
    return {
        "id": c.id, "uuid": c.uuid, "direccion": c.direction, "estado": c.status,
        "origen": c.caller_number, "destino": c.callee_number,
        "duracion": c.duration, "hablado": c.billsec, "por_troncal": c.via_trunk,
        "campana_id": c.campaign_id, "tiene_grabacion": bool(c.recording_path),
        "inicio": c.started_at, "contestada": c.answered_at, "fin": c.ended_at,
    }


@router.get("/llamadas", dependencies=[Depends(requiere_scope("llamadas:leer"))])
async def llamadas(
    desde: datetime | None = None,
    hasta: datetime | None = None,
    despues_de: int = Query(default=0, ge=0, description="Paginación: id de la última llamada recibida"),
    limite: int = Query(default=100, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
):
    consulta = select(CallLog).where(filtro_empresa(session, CallLog), CallLog.id > despues_de)
    if desde:
        consulta = consulta.where(CallLog.started_at >= desde)
    if hasta:
        consulta = consulta.where(CallLog.started_at < hasta)
    filas = (await session.execute(consulta.order_by(CallLog.id).limit(limite))).scalars().all()
    return {"datos": [_llamada(c) for c in filas], "siguiente": filas[-1].id if len(filas) == limite else None}


@router.get("/citas", response_model=list[AppointmentOut], dependencies=[Depends(requiere_scope("citas:leer"))])
async def citas(
    desde: datetime | None = None,
    hasta: datetime | None = None,
    limite: int = Query(default=500, ge=1, le=2000),
    session: AsyncSession = Depends(get_session),
):
    consulta = select(Appointment).where(filtro_empresa(session, Appointment))
    if desde:
        consulta = consulta.where(Appointment.appointment_date >= desde)
    if hasta:
        consulta = consulta.where(Appointment.appointment_date < hasta)
    return (await session.execute(consulta.order_by(Appointment.appointment_date).limit(limite))).scalars().all()


@router.post(
    "/citas", response_model=AppointmentOut, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(requiere_scope("citas:escribir"))],
)
async def crear_cita(payload: AppointmentCreate, request: Request, session: AsyncSession = Depends(get_session)):
    await _operativa(request, session)
    return await appointments_api.create_appointment(payload, session)


@router.post(
    "/campanas/{campaign_id}/numeros", status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(requiere_scope("campanas:escribir"))],
)
async def cargar_numeros(
    campaign_id: int, payload: CampaignNumberIn, request: Request, session: AsyncSession = Depends(get_session)
):
    await _operativa(request, session, modulo="voicebot")
    return await campaigns_api.add_numbers(campaign_id, payload, session)


@router.get("/consumo", dependencies=[Depends(requiere_scope("consumo:leer"))])
async def consumo_del_mes(request: Request, mes: str | None = None, session: AsyncSession = Depends(get_session)):
    try:
        return await consumo.resumen(session, request.state.api_key.tenant_id, mes)
    except consumo.MesInvalido as e:
        raise HTTPException(status_code=422, detail=str(e))
