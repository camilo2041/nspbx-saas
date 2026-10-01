"""Gestión de las claves de la API pública (ver core/claves_api.py).

Solo el administrador de la empresa. La clave completa se devuelve UNA vez,
al crearla; después solo se ve su prefijo.
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import claves_api
from app.core.database import filtro_empresa, get_session, tenant_de_sesion, traer_propio
from app.models import ApiKey

router = APIRouter(prefix="/api/claves-api", tags=["claves-api"])

MAX_CLAVES_ACTIVAS = 20


class ClaveCrear(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    scopes: list[str] = Field(min_length=1)
    # Vacío = no vence.
    dias_validez: int | None = Field(default=None, ge=1, le=3650)

    @field_validator("scopes")
    @classmethod
    def _conocidos(cls, v: list[str]) -> list[str]:
        desconocidos = sorted(set(v) - set(claves_api.ESCOPOS))
        if desconocidos:
            raise ValueError(f"Permisos desconocidos: {', '.join(desconocidos)}")
        return sorted(set(v))


def _salida(k: ApiKey) -> dict:
    return {
        "id": k.id, "name": k.name, "prefix": k.prefix, "scopes": k.scope_list,
        "created_by": k.created_by, "created_at": k.created_at, "expires_at": k.expires_at,
        "revoked_at": k.revoked_at, "last_used_at": k.last_used_at,
    }


@router.get("/escopos")
async def escopos():
    return claves_api.ESCOPOS


@router.get("")
async def listar(session: AsyncSession = Depends(get_session)):
    filas = (
        await session.execute(select(ApiKey).where(filtro_empresa(session, ApiKey)).order_by(ApiKey.id.desc()))
    ).scalars().all()
    return [_salida(k) for k in filas]


@router.post("", status_code=status.HTTP_201_CREATED)
async def crear(payload: ClaveCrear, request: Request, session: AsyncSession = Depends(get_session)):
    activas = (
        await session.execute(
            select(func.count(ApiKey.id)).where(filtro_empresa(session, ApiKey), ApiKey.revoked_at.is_(None))
        )
    ).scalar_one()
    if activas >= MAX_CLAVES_ACTIVAS:
        raise HTTPException(status_code=409, detail=f"Máximo {MAX_CLAVES_ACTIVAS} claves activas; revoca alguna")
    clave, prefijo, hash_ = claves_api.generar()
    usuario = request.state.usuario
    fila = ApiKey(
        tenant_id=tenant_de_sesion(session), name=payload.name, prefix=prefijo, key_hash=hash_,
        scopes=",".join(payload.scopes), created_by=f"{usuario.username} ({usuario.role})",
        expires_at=datetime.utcnow() + timedelta(days=payload.dias_validez) if payload.dias_validez else None,
    )
    session.add(fila)
    await session.commit()
    await session.refresh(fila)
    return {**_salida(fila), "clave": clave}


@router.delete("/{key_id}")
async def revocar(key_id: int, session: AsyncSession = Depends(get_session)):
    fila = await traer_propio(session, ApiKey, key_id)
    if not fila:
        raise HTTPException(status_code=404, detail="Clave no encontrada")
    if fila.revoked_at is None:
        fila.revoked_at = datetime.utcnow()
        await session.commit()
        await session.refresh(fila)
    return _salida(fila)
