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

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import appointments as appointments_api, campaigns as campaigns_api, crm as crm_api
from app.core.claves_api import requiere_scope
from app.core.database import filtro_empresa, get_session, traer_propio
from app.models import Appointment, CallLog, Callback, Campaign, CampaignNumber, Contacto, Disposicion, Tenant, User
from app.schemas import AppointmentCreate, AppointmentOut, CampaignNumberIn, ContactoIn, ContactoUpdate
from app.services import agentes, consumo, crm, integraciones

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


# --- CRM: contactos, leads y callbacks (fase 6) ----------------------------------------------------


@router.get("/contactos", dependencies=[Depends(requiere_scope("contactos:leer"))])
async def buscar_contactos(
    telefono: str | None = Query(default=None, max_length=40),
    documento: str | None = Query(default=None, max_length=30),
    session: AsyncSession = Depends(get_session),
):
    """Por teléfono (cualquier formato: se compara por los últimos dígitos) o documento."""
    if not telefono and not documento:
        raise HTTPException(status_code=422, detail="Indica telefono o documento")
    q = select(Contacto).where(filtro_empresa(session, Contacto))
    if telefono:
        clave = crm.clave_telefono(telefono)
        if not clave:
            raise HTTPException(status_code=422, detail="El teléfono necesita dígitos")
        q = q.where(Contacto.telefono_clave == clave)
    if documento:
        q = q.where(Contacto.documento == documento.strip())
    filas = (await session.execute(q.limit(20))).scalars().all()
    bloqueadas = await crm_api._claves_en_no_llamar(session, {c.telefono_clave for c in filas})
    return [crm_api._contacto_out(c, c.telefono_clave in bloqueadas) for c in filas]


@router.post("/contactos", dependencies=[Depends(requiere_scope("contactos:escribir"))])
async def guardar_contacto(payload: ContactoIn, request: Request, response: Response, session: AsyncSession = Depends(get_session)):
    """Crea el contacto, o lo actualiza si ya hay uno con ese teléfono (lo que
    venga en el cuerpo pisa; lo que no venga se deja). 201 si lo creó."""
    await _operativa(request, session)
    clave = crm.clave_telefono(payload.telefono)
    existente = (
        await session.execute(select(Contacto).where(filtro_empresa(session, Contacto), Contacto.telefono_clave == clave).limit(1))
    ).scalar_one_or_none()
    if existente is None:
        response.status_code = status.HTTP_201_CREATED
        return {**await crm_api.crear_contacto(payload, session), "creado": True}
    cambios = ContactoUpdate(**payload.model_dump(exclude_unset=True))
    return {**await crm_api.editar_contacto(existente.id, cambios, session), "creado": False}


async def _lead_out(session: AsyncSession, lead: CampaignNumber) -> dict:
    disp = await session.get(Disposicion, lead.disposicion_id) if lead.disposicion_id else None
    pendientes = (
        await session.execute(select(Callback).where(Callback.lead_id == lead.id, Callback.estado == "pendiente").order_by(Callback.cuando))
    ).scalars().all()
    return {
        "id": lead.id, "campana_id": lead.campaign_id, "telefono": lead.phone, "contacto_id": lead.contacto_id,
        "estado": lead.status, "intentos": lead.attempts, "ultimo_error": lead.last_error,
        "ultimo_intento_at": lead.ultimo_intento_at, "proximo_intento_at": lead.proximo_intento_at,
        "disposicion": {"codigo": disp.codigo, "nombre": disp.nombre, "categoria": disp.categoria} if disp else None,
        "callbacks": [{"id": c.id, "cuando": c.cuando, "agente_id": c.agente_id, "nota": c.nota} for c in pendientes],
    }


@router.get("/leads/{lead_id}", dependencies=[Depends(requiere_scope("leads:leer"))])
async def lead(lead_id: int, session: AsyncSession = Depends(get_session)):
    fila = await traer_propio(session, CampaignNumber, lead_id)
    if fila is None:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    return await _lead_out(session, fila)


@router.get("/campanas/{campaign_id}/leads", dependencies=[Depends(requiere_scope("leads:leer"))])
async def leads_de_campana(
    campaign_id: int,
    telefono: str | None = Query(default=None, max_length=40),
    cambiados_desde: datetime | None = Query(default=None, description="Solo los intentados o dispuestos desde esta fecha (UTC)"),
    despues_de: int = Query(default=0, ge=0, description="Paginación: id del último lead recibido"),
    limite: int = Query(default=200, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
):
    if await traer_propio(session, Campaign, campaign_id) is None:
        raise HTTPException(status_code=404, detail="Campaña no encontrada")
    q = select(CampaignNumber).where(CampaignNumber.campaign_id == campaign_id, CampaignNumber.id > despues_de)
    if telefono:
        q = q.where(crm.clave_sql(CampaignNumber.phone) == crm.clave_telefono(telefono))
    if cambiados_desde:
        q = q.where(CampaignNumber.ultimo_intento_at >= cambiados_desde.replace(tzinfo=None))
    filas = (await session.execute(q.order_by(CampaignNumber.id).limit(limite))).scalars().all()
    return {"datos": [await _lead_out(session, f) for f in filas], "siguiente": filas[-1].id if len(filas) == limite else None}


class CallbackV1(BaseModel):
    lead_id: int
    cuando: datetime = Field(..., description="Con zona (ISO 8601); sin zona se toma como UTC")
    agente_id: int | None = Field(default=None, description="Solo ese agente; vacío = cualquiera de la campaña")
    nota: str | None = Field(default=None, max_length=4000)


@router.post("/callbacks", status_code=status.HTTP_201_CREATED, dependencies=[Depends(requiere_scope("callbacks:escribir"))])
async def agendar_callback(payload: CallbackV1, request: Request, session: AsyncSession = Depends(get_session)):
    """Igual que el callback que agenda un agente al disponer: el lead vuelve a
    la cola con prioridad en esa fecha (y para ese agente, si se indica)."""
    await _operativa(request, session)
    tenant_id = request.state.api_key.tenant_id
    lead = await traer_propio(session, CampaignNumber, payload.lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    # En la base todo va en UTC sin zona.
    cuando = payload.cuando.astimezone(timezone.utc).replace(tzinfo=None) if payload.cuando.tzinfo else payload.cuando
    ahora = datetime.utcnow()
    if cuando <= ahora:
        raise HTTPException(status_code=422, detail="La fecha tiene que ser futura")
    if cuando > ahora + timedelta(days=180):
        raise HTTPException(status_code=422, detail="No más de 6 meses adelante")
    if lead.status == "no_llamar":
        raise HTTPException(status_code=409, detail="Ese lead está en no llamar")
    if payload.agente_id is not None:
        agente = await traer_propio(session, User, payload.agente_id)
        if agente is None or not agente.enabled:
            raise HTTPException(status_code=404, detail="Agente no encontrado")
    lead.status = "pending"
    lead.proximo_intento_at = cuando
    lead.agente_id = payload.agente_id
    lead.prioridad = max(lead.prioridad or 0, agentes.PRIORIDAD_CALLBACK)
    cb = Callback(tenant_id=tenant_id, lead_id=lead.id, campaign_id=lead.campaign_id, contacto_id=lead.contacto_id,
                  agente_id=payload.agente_id, cuando=cuando, estado="pendiente", nota=(payload.nota or "").strip() or None)
    session.add(cb)
    await integraciones.emitir_seguro(session, tenant_id, "callback.creado", {
        "lead_id": lead.id, "campana_id": lead.campaign_id, "contacto_id": lead.contacto_id, "telefono": lead.phone,
        "cuando": cuando.isoformat() + "Z", "agente_id": payload.agente_id, "nota": cb.nota, "origen": "api",
    })
    await session.commit()
    return {"id": cb.id, "lead_id": lead.id, "cuando": cuando, "agente_id": cb.agente_id, "estado": cb.estado}
