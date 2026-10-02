"""Consola del agente (docs/plan-contact-center.md, fase 3).

Todo exige `agente:operar` y actúa SOLO sobre el propio agente: no hay ids
de usuario en estas rutas. Del cliente, el agente ve el lead que está
atendiendo (contacto, campos visibles para el agente, notas, sus llamadas
anteriores y el guion), no el CRM completo.
"""

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import usuario_actual
from app.core.database import get_session
from app.models import (
    AgenteVivo,
    CallLog,
    Callback,
    Campaign,
    CampaignNumber,
    CampoContacto,
    CodigoPausa,
    Contacto,
    Disposicion,
    Nota,
    User,
)
from app.services import agentes, templating

router = APIRouter(prefix="/api/agente", tags=["agente"])


class EntrarIn(BaseModel):
    campanas: list[int] = Field(..., min_length=1, max_length=20)


class PausaIn(BaseModel):
    codigo_pausa_id: int | None = None


class MarcarIn(BaseModel):
    campaign_id: int
    telefono: str | None = Field(default=None, max_length=40)
    lead_id: int | None = None


class DisponerIn(BaseModel):
    disposicion_id: int
    nota: str | None = Field(default=None, max_length=4000)
    callback_at: datetime | None = None
    callback_propio: bool = True


class NotaIn(BaseModel):
    texto: str = Field(..., min_length=1, max_length=4000)


def _error(exc: agentes.ErrorAgente) -> HTTPException:
    return HTTPException(status_code=exc.codigo, detail=exc.mensaje)


async def _mi_vivo(session: AsyncSession, usuario: User) -> AgenteVivo:
    vivo = await agentes.vivo_de(session, usuario.id)
    if vivo is None:
        raise HTTPException(status_code=409, detail="No has entrado a la consola de agente")
    return vivo


async def _lead(session: AsyncSession, vivo: AgenteVivo, usuario: User) -> dict | None:
    if vivo.lead_id is None:
        return None
    lead = await session.get(CampaignNumber, vivo.lead_id)
    if lead is None:
        return None
    campana = await session.get(Campaign, lead.campaign_id)
    contacto = await session.get(Contacto, lead.contacto_id) if lead.contacto_id else None
    variables: dict[str, str] = {}
    try:
        variables.update({k: str(v) for k, v in json.loads(lead.extra_data or "{}").items()})
    except (ValueError, AttributeError):
        pass
    datos_contacto = None
    notas: list[dict] = []
    if contacto is not None:
        visibles = {
            c.clave: c.nombre
            for c in (await session.execute(select(CampoContacto).where(CampoContacto.visible_agente.is_(True)))).scalars()
        }
        campos = {visibles[k]: v for k, v in (contacto.campos or {}).items() if k in visibles}
        datos_contacto = {
            "id": contacto.id,
            "nombre": contacto.nombre,
            "documento": contacto.documento,
            "telefono": contacto.telefono,
            "telefonos": contacto.telefonos or [],
            "email": contacto.email,
            "ciudad": contacto.ciudad,
            "direccion": contacto.direccion,
            "campos": campos,
        }
        # Sin nombre se deja {nombre} a la vista en el guion: mejor que
        # leer «Hola , …» sin darse cuenta de que falta el dato.
        if contacto.nombre:
            variables.setdefault("nombre", contacto.nombre)
            variables.setdefault("cliente", contacto.nombre)
        for clave, valor in (contacto.campos or {}).items():
            if clave in visibles:
                variables.setdefault(clave, str(valor))
        notas = [
            {"id": n.id, "texto": n.texto, "autor": n.autor, "created_at": n.created_at}
            for n in (
                await session.execute(
                    select(Nota).where(Nota.contacto_id == contacto.id).order_by(desc(Nota.id)).limit(20)
                )
            ).scalars()
        ]
    variables.setdefault("telefono", lead.phone)
    variables.setdefault("agente", usuario.full_name or usuario.username)
    anteriores = (
        await session.execute(
            select(CallLog)
            .where(CallLog.lead_id == lead.id, CallLog.uuid != (vivo.call_uuid or ""))
            .order_by(desc(CallLog.started_at))
            .limit(10)
        )
    ).scalars().all()
    disposiciones = {d.id: d.nombre for d in (await session.execute(select(Disposicion))).scalars()}
    return {
        "id": lead.id,
        "telefono": lead.phone,
        "intentos": lead.attempts,
        "variables": variables,
        "campana": {"id": campana.id, "nombre": campana.name, "metodo": campana.metodo} if campana else None,
        "guion": templating.render(campana.guion, variables) if campana and campana.guion else None,
        "contacto": datos_contacto,
        "notas": notas,
        "llamadas_anteriores": [
            {
                "started_at": c.started_at,
                "status": c.status,
                "billsec": c.billsec,
                "disposicion": disposiciones.get(c.disposicion_id) if c.disposicion_id else None,
            }
            for c in anteriores
        ],
    }


async def _estado(session: AsyncSession, usuario: User) -> dict:
    await agentes.asegurar_catalogos(session, usuario.tenant_id)
    vivo = await agentes.vivo_de(session, usuario.id, bloquear=False)
    pausas = (await session.execute(select(CodigoPausa).where(CodigoPausa.activo.is_(True)).order_by(CodigoPausa.orden))).scalars().all()
    disposiciones = (
        await session.execute(select(Disposicion).where(Disposicion.activa.is_(True)).order_by(Disposicion.orden))
    ).scalars().all()
    asignadas = await agentes.campanas_asignadas(session, usuario.id)
    ahora = datetime.utcnow()
    callbacks = (
        await session.execute(
            select(Callback, CampaignNumber.phone, Contacto.nombre)
            .join(CampaignNumber, CampaignNumber.id == Callback.lead_id)
            .outerjoin(Contacto, Contacto.id == Callback.contacto_id)
            .where(
                Callback.estado == "pendiente",
                or_(Callback.agente_id == usuario.id,
                    Callback.agente_id.is_(None) & Callback.campaign_id.in_([c.id for c in asignadas] or [0])),
            )
            .order_by(Callback.cuando)
            .limit(30)
        )
    ).all()
    return {
        "agente": {**agentes.foto(vivo), "token_audio": vivo.token_audio, "extension": vivo.extension} if vivo else None,
        "campanas": [{"id": c.id, "nombre": c.name, "metodo": c.metodo, "status": c.status} for c in asignadas],
        "pausas": [{"id": p.id, "codigo": p.codigo, "nombre": p.nombre, "max_minutos": p.max_minutos} for p in pausas],
        "disposiciones": [
            {"id": d.id, "codigo": d.codigo, "nombre": d.nombre, "categoria": d.categoria, "color": d.color}
            for d in disposiciones
        ],
        "lead": await _lead(session, vivo, usuario) if vivo else None,
        "callbacks": [
            {
                "id": cb.id,
                "lead_id": cb.lead_id,
                "campaign_id": cb.campaign_id,
                "telefono": telefono,
                "nombre": nombre,
                "cuando": cb.cuando,
                "nota": cb.nota,
                "propio": cb.agente_id == usuario.id,
                "vencido": cb.cuando <= ahora,
            }
            for cb, telefono, nombre in callbacks
        ],
    }


async def _hacer(session: AsyncSession, usuario: User, accion) -> dict:
    """Ejecuta una acción sobre el agente, guarda y devuelve el estado."""
    try:
        await accion()
    except agentes.ErrorAgente as exc:
        await session.rollback()
        raise _error(exc) from None
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from None
    await session.commit()
    return await _estado(session, usuario)


@router.get("/estado")
async def estado(session: AsyncSession = Depends(get_session), usuario: User = Depends(usuario_actual)):
    resultado = await _estado(session, usuario)
    await session.commit()  # los catálogos de ejemplo, si se acaban de crear
    return resultado


@router.post("/entrar")
async def entrar(payload: EntrarIn, session: AsyncSession = Depends(get_session), usuario: User = Depends(usuario_actual)):
    return await _hacer(session, usuario, lambda: agentes.entrar(session, usuario, payload.campanas))


@router.post("/salir")
async def salir(session: AsyncSession = Depends(get_session), usuario: User = Depends(usuario_actual)):
    async def accion():
        await agentes.salir(session, await _mi_vivo(session, usuario))

    return await _hacer(session, usuario, accion)


@router.post("/audio")
async def reconectar_audio(session: AsyncSession = Depends(get_session), usuario: User = Depends(usuario_actual)):
    async def accion():
        await agentes.reconectar_audio(session, await _mi_vivo(session, usuario))

    return await _hacer(session, usuario, accion)


@router.post("/listo")
async def listo(session: AsyncSession = Depends(get_session), usuario: User = Depends(usuario_actual)):
    async def accion():
        await agentes.listo(session, await _mi_vivo(session, usuario))

    return await _hacer(session, usuario, accion)


@router.post("/pausa")
async def pausa(payload: PausaIn, session: AsyncSession = Depends(get_session), usuario: User = Depends(usuario_actual)):
    async def accion():
        await agentes.pausar(session, await _mi_vivo(session, usuario), payload.codigo_pausa_id)

    return await _hacer(session, usuario, accion)


@router.post("/marcar")
async def marcar(payload: MarcarIn, session: AsyncSession = Depends(get_session), usuario: User = Depends(usuario_actual)):
    async def accion():
        telefono = (payload.telefono or "").strip().replace(" ", "").replace("-", "") or None
        await agentes.marcar(session, await _mi_vivo(session, usuario), payload.campaign_id, telefono, payload.lead_id)

    return await _hacer(session, usuario, accion)


@router.post("/colgar")
async def colgar(session: AsyncSession = Depends(get_session), usuario: User = Depends(usuario_actual)):
    async def accion():
        await agentes.colgar(session, await _mi_vivo(session, usuario))

    return await _hacer(session, usuario, accion)


@router.post("/siguiente")
async def siguiente(session: AsyncSession = Depends(get_session), usuario: User = Depends(usuario_actual)):
    async def accion():
        if await agentes.siguiente(session, await _mi_vivo(session, usuario)) is None:
            raise agentes.ErrorAgente("No hay leads disponibles ahora en tus campañas de vista previa", 404)

    return await _hacer(session, usuario, accion)


@router.post("/saltar")
async def saltar(session: AsyncSession = Depends(get_session), usuario: User = Depends(usuario_actual)):
    async def accion():
        await agentes.saltar(session, await _mi_vivo(session, usuario))

    return await _hacer(session, usuario, accion)


@router.post("/disponer")
async def disponer(payload: DisponerIn, session: AsyncSession = Depends(get_session), usuario: User = Depends(usuario_actual)):
    async def accion():
        await agentes.disponer(
            session, await _mi_vivo(session, usuario), usuario, payload.disposicion_id,
            payload.nota, payload.callback_at, payload.callback_propio,
        )

    return await _hacer(session, usuario, accion)


@router.post("/nota")
async def nota(payload: NotaIn, session: AsyncSession = Depends(get_session), usuario: User = Depends(usuario_actual)):
    """Nota sobre el cliente que el agente está atendiendo."""
    async def accion():
        vivo = await _mi_vivo(session, usuario)
        lead = await session.get(CampaignNumber, vivo.lead_id) if vivo.lead_id else None
        if lead is None or lead.contacto_id is None:
            raise agentes.ErrorAgente("No estás atendiendo a ningún cliente")
        session.add(Nota(tenant_id=vivo.tenant_id, contacto_id=lead.contacto_id, user_id=usuario.id,
                         autor=usuario.full_name or usuario.username, texto=payload.texto.strip()))

    return await _hacer(session, usuario, accion)


@router.post("/callbacks/{callback_id}/llamar")
async def llamar_callback(callback_id: int, session: AsyncSession = Depends(get_session), usuario: User = Depends(usuario_actual)):
    """Marca ya un callback (propio o de cualquiera de sus campañas)."""
    async def accion():
        # Primero el callback (404 si no es de la empresa o es de otro
        # agente), después el estado del agente.
        cb = await session.get(Callback, callback_id)
        if cb is None or cb.tenant_id != usuario.tenant_id or cb.estado != "pendiente" or cb.agente_id not in (None, usuario.id):
            raise agentes.ErrorAgente("Callback no encontrado", 404)
        vivo = await _mi_vivo(session, usuario)
        await agentes.marcar(session, vivo, cb.campaign_id, lead_id=cb.lead_id)
        cb.estado = "hecho"

    return await _hacer(session, usuario, accion)

