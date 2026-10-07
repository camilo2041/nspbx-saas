"""Festivos y fechas especiales de la empresa (services/festivos.py)."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session, tenant_de_sesion, traer_propio
from app.models import FechaEspecial
from app.services import festivos
from app.services.ajustes import ajustes_de
from app.services.horario_marcacion import leer_franja

router = APIRouter(prefix="/api/festivos", tags=["festivos"])


class CalendarioIn(BaseModel):
    cerrar_festivos: bool


class FechaIn(BaseModel):
    fecha: date
    nombre: str = Field(min_length=1, max_length=80)
    franja: str | None = Field(default=None, max_length=11)

    @field_validator("franja")
    @classmethod
    def _franja(cls, v: str | None) -> str | None:
        v = (v or "").strip() or None
        if v is not None:
            leer_franja(v)  # ValueError con el mensaje para la persona
        return v


def _fecha_out(f: FechaEspecial) -> dict:
    return {"id": f.id, "fecha": f.fecha, "nombre": f.nombre, "franja": f.franja}


def _empresa(session) -> int:
    tid = tenant_de_sesion(session)
    if tid is None:
        raise HTTPException(status_code=403, detail="El calendario es de cada empresa")
    return tid


@router.get("")
async def calendario(session: AsyncSession = Depends(get_session)):
    tid = _empresa(session)
    ajustes = await ajustes_de(session, tid)
    hoy = date.today()
    especiales = (
        await session.execute(select(FechaEspecial).where(FechaEspecial.fecha >= hoy).order_by(FechaEspecial.fecha))
    ).scalars().all()
    return {
        "cerrar_festivos": bool(getattr(ajustes, "festivos_cerrado", False)),
        "nacionales": festivos.proximos_nacionales(hoy),
        "especiales": [_fecha_out(f) for f in especiales],
    }


@router.put("")
async def guardar_calendario(datos: CalendarioIn, session: AsyncSession = Depends(get_session)):
    tid = _empresa(session)
    ajustes = await ajustes_de(session, tid)
    if ajustes is None:
        raise HTTPException(status_code=404, detail="La empresa no tiene ajustes")
    ajustes.festivos_cerrado = datos.cerrar_festivos
    await session.commit()
    festivos.invalidar()
    return {"cerrar_festivos": datos.cerrar_festivos}


@router.post("/especiales", status_code=status.HTTP_201_CREATED)
async def agregar_fecha(datos: FechaIn, session: AsyncSession = Depends(get_session)):
    tid = _empresa(session)
    ya = (await session.execute(select(FechaEspecial).where(FechaEspecial.fecha == datos.fecha))).scalar_one_or_none()
    if ya is not None:
        raise HTTPException(status_code=409, detail="Esa fecha ya está en el calendario")
    f = FechaEspecial(tenant_id=tid, fecha=datos.fecha, nombre=datos.nombre.strip(), franja=datos.franja)
    session.add(f)
    await session.commit()
    festivos.invalidar()
    return _fecha_out(f)


@router.delete("/especiales/{fecha_id}", status_code=status.HTTP_204_NO_CONTENT)
async def quitar_fecha(fecha_id: int, session: AsyncSession = Depends(get_session)):
    f = await traer_propio(session, FechaEspecial, fecha_id)
    if f is None:
        raise HTTPException(status_code=404, detail="Fecha no encontrada")
    await session.delete(f)
    await session.commit()
    festivos.invalidar()
