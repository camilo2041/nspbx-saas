"""Catálogos del contact center: códigos de pausa y disposiciones.

Los ejemplos se crean solos la primera vez (services/agentes.py); acá cada
empresa los adapta. Exige gestionar campañas. Un código o una disposición
en uso no se borra (quedan en la bitácora y en el historial): se desactiva.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session, tenant_de_sesion, traer_propio
from app.models import CodigoPausa, Disposicion
from app.services import agentes

router = APIRouter(prefix="/api/contact-center", tags=["contact-center"])

_CODIGO = Field(..., pattern=r"^[A-Z][A-Z0-9_]{0,19}$")


class PausaIn(BaseModel):
    codigo: str = _CODIGO
    nombre: str = Field(..., min_length=1, max_length=60)
    pagada: bool = True
    max_minutos: int | None = Field(default=None, ge=1, le=600)
    activo: bool = True
    orden: int = Field(default=0, ge=0, le=1000)


class PausaUpdate(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=60)
    pagada: bool | None = None
    max_minutos: int | None = Field(default=None, ge=1, le=600)
    activo: bool | None = None
    orden: int | None = Field(default=None, ge=0, le=1000)


class DisposicionIn(BaseModel):
    codigo: str = _CODIGO
    nombre: str = Field(..., min_length=1, max_length=60)
    categoria: str = Field(..., pattern="^(" + "|".join(agentes.CATEGORIAS) + ")$")
    contacto_humano: bool = True
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    activa: bool = True
    orden: int = Field(default=0, ge=0, le=1000)


class DisposicionUpdate(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=60)
    categoria: str | None = Field(default=None, pattern="^(" + "|".join(agentes.CATEGORIAS) + ")$")
    contacto_humano: bool | None = None
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    activa: bool | None = None
    orden: int | None = Field(default=None, ge=0, le=1000)


def _empresa(session: AsyncSession) -> int:
    tid = tenant_de_sesion(session)
    if tid is None:
        raise HTTPException(status_code=403, detail="El contact center es de cada empresa")
    return tid


def _pausa_out(p: CodigoPausa) -> dict:
    return {"id": p.id, "codigo": p.codigo, "nombre": p.nombre, "pagada": p.pagada, "max_minutos": p.max_minutos,
            "activo": p.activo, "orden": p.orden}


def _disp_out(d: Disposicion) -> dict:
    return {"id": d.id, "codigo": d.codigo, "nombre": d.nombre, "categoria": d.categoria,
            "contacto_humano": d.contacto_humano, "color": d.color, "activa": d.activa, "orden": d.orden}


@router.get("/pausas")
async def listar_pausas(session: AsyncSession = Depends(get_session)):
    await agentes.asegurar_catalogos(session, _empresa(session))
    await session.commit()
    filas = (await session.execute(select(CodigoPausa).order_by(CodigoPausa.orden, CodigoPausa.id))).scalars()
    return [_pausa_out(p) for p in filas]


@router.post("/pausas", status_code=status.HTTP_201_CREATED)
async def crear_pausa(payload: PausaIn, session: AsyncSession = Depends(get_session)):
    tid = _empresa(session)
    if (await session.execute(select(CodigoPausa.id).where(CodigoPausa.codigo == payload.codigo))).first():
        raise HTTPException(status_code=409, detail="Ya existe un código de pausa con ese código")
    pausa = CodigoPausa(tenant_id=tid, **payload.model_dump())
    session.add(pausa)
    await session.commit()
    return _pausa_out(pausa)


@router.put("/pausas/{pausa_id}")
async def editar_pausa(pausa_id: int, payload: PausaUpdate, session: AsyncSession = Depends(get_session)):
    pausa = await traer_propio(session, CodigoPausa, pausa_id)
    if not pausa:
        raise HTTPException(status_code=404, detail="Código de pausa no encontrado")
    for campo, valor in payload.model_dump(exclude_unset=True).items():
        setattr(pausa, campo, valor)
    await session.commit()
    return _pausa_out(pausa)


@router.get("/disposiciones")
async def listar_disposiciones(session: AsyncSession = Depends(get_session)):
    await agentes.asegurar_catalogos(session, _empresa(session))
    await session.commit()
    filas = (await session.execute(select(Disposicion).order_by(Disposicion.orden, Disposicion.id))).scalars()
    return [_disp_out(d) for d in filas]


@router.post("/disposiciones", status_code=status.HTTP_201_CREATED)
async def crear_disposicion(payload: DisposicionIn, session: AsyncSession = Depends(get_session)):
    tid = _empresa(session)
    if (await session.execute(select(Disposicion.id).where(Disposicion.codigo == payload.codigo))).first():
        raise HTTPException(status_code=409, detail="Ya existe una disposición con ese código")
    disp = Disposicion(tenant_id=tid, **payload.model_dump())
    session.add(disp)
    await session.commit()
    return _disp_out(disp)


@router.put("/disposiciones/{disposicion_id}")
async def editar_disposicion(disposicion_id: int, payload: DisposicionUpdate, session: AsyncSession = Depends(get_session)):
    disp = await traer_propio(session, Disposicion, disposicion_id)
    if not disp:
        raise HTTPException(status_code=404, detail="Disposición no encontrada")
    for campo, valor in payload.model_dump(exclude_unset=True).items():
        setattr(disp, campo, valor)
    await session.commit()
    return _disp_out(disp)
