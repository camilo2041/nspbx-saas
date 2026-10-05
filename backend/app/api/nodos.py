"""Servidores FreeSWITCH de la plataforma (opción A, docs/escala.md §4).

Solo el rol plataforma (`empresas:gestionar`), con la sesión del dueño: los
servidores no son de ninguna empresa. Acá se dan de alta los adicionales y se
decide en cuál vive cada empresa. El principal es el de siempre (FS_ESL_HOST)
y no se edita acá.
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import validacion
from app.core.database import get_admin_session
from app.models import AgenteVivo, NodoFreeswitch, Tenant, Trunk
from app.services import esl, gateways
from app.services.nodos import directorio

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/plataforma/nodos", tags=["plataforma"])


def _validar(campo: str, regex, valor: str | None) -> str | None:
    if valor is None:
        return None
    try:
        return validacion.exigir(regex, valor.strip(), campo)
    except Exception as exc:
        raise ValueError(str(getattr(exc, "detail", exc)))


class NodoIn(BaseModel):
    nombre: str = Field(..., min_length=2, max_length=40)
    esl_host: str = Field(..., max_length=255)
    esl_port: int = Field(default=8021, ge=1, le=65535)
    esl_password: str = Field(..., min_length=8, max_length=200)
    sip_host: str = Field(..., max_length=255)
    capacidad_agentes: int = Field(default=200, ge=1, le=5000)
    activo: bool = True

    @field_validator("nombre")
    @classmethod
    def _n(cls, v):
        return _validar("Nombre", validacion.NOMBRE_RE, v)

    @field_validator("esl_host", "sip_host")
    @classmethod
    def _h(cls, v):
        return _validar("Servidor", validacion.HOST_RE, v)


class NodoUpdate(BaseModel):
    esl_host: str | None = Field(default=None, max_length=255)
    esl_port: int | None = Field(default=None, ge=1, le=65535)
    esl_password: str | None = Field(default=None, min_length=8, max_length=200)
    sip_host: str | None = Field(default=None, max_length=255)
    capacidad_agentes: int | None = Field(default=None, ge=1, le=5000)
    activo: bool | None = None

    @field_validator("esl_host", "sip_host")
    @classmethod
    def _h(cls, v):
        return _validar("Servidor", validacion.HOST_RE, v)


class AsignarIn(BaseModel):
    nodo_id: int | None = None
    # Mover una empresa con agentes conectados les corta las sesiones.
    forzar: bool = False


async def _estado_en_vivo(nodo_id: int | None) -> dict:
    try:
        cliente = await asyncio.wait_for(esl.get_client(nodo_id), timeout=3)
        cuerpo = await asyncio.wait_for(cliente.api("status"), timeout=3)
    except Exception as exc:
        return {"conectado": False, "error": str(exc)[:200]}
    import re

    m = re.search(r"(\d+) session\(s\) - peak (\d+)", cuerpo)
    v = re.search(r"FreeSWITCH \(Version (.+?)\)", cuerpo)
    return {"conectado": True, "canales": int(m.group(1)) if m else None, "pico": int(m.group(2)) if m else None,
            "version": v.group(1) if v else None}


async def _apagado() -> dict:
    return {"conectado": False, "error": "Desactivado"}


async def _resumen(session: AsyncSession) -> tuple[dict, dict]:
    empresas = dict((await session.execute(select(Tenant.nodo_id, func.count()).group_by(Tenant.nodo_id))).all())
    agentes = dict(
        (
            await session.execute(
                select(Tenant.nodo_id, func.count()).join(AgenteVivo, AgenteVivo.tenant_id == Tenant.id).group_by(Tenant.nodo_id)
            )
        ).all()
    )
    return empresas, agentes


def _out(n: NodoFreeswitch | None, empresas: dict, agentes: dict, vivo: dict) -> dict:
    if n is None:
        from app.core.runtime_settings import runtime_settings

        return {"id": None, "nombre": "principal", "esl_host": runtime_settings.fs_esl_host, "esl_port": runtime_settings.fs_esl_port,
                "sip_host": None, "capacidad_agentes": None, "activo": True, "principal": True,
                "empresas": empresas.get(None, 0), "agentes_conectados": agentes.get(None, 0), **vivo}
    return {"id": n.id, "nombre": n.nombre, "esl_host": n.esl_host, "esl_port": n.esl_port, "sip_host": n.sip_host,
            "capacidad_agentes": n.capacidad_agentes, "activo": n.activo, "principal": False,
            "empresas": empresas.get(n.id, 0), "agentes_conectados": agentes.get(n.id, 0), **vivo}


@router.get("")
async def listar(session: AsyncSession = Depends(get_admin_session)):
    """Todos los servidores con su estado en vivo (canales en curso, agentes
    conectados de sus empresas)."""
    await directorio.refrescar(forzar=True)
    nodos = (await session.execute(select(NodoFreeswitch).order_by(NodoFreeswitch.nombre))).scalars().all()
    empresas, agentes = await _resumen(session)
    vivos = await asyncio.gather(_estado_en_vivo(None), *(_estado_en_vivo(n.id) if n.activo else _apagado() for n in nodos))
    return [_out(None, empresas, agentes, vivos[0])] + [_out(n, empresas, agentes, v) for n, v in zip(nodos, vivos[1:])]


@router.post("", status_code=status.HTTP_201_CREATED)
async def crear(payload: NodoIn, session: AsyncSession = Depends(get_admin_session)):
    if (await session.execute(select(NodoFreeswitch.id).where(NodoFreeswitch.nombre == payload.nombre))).first():
        raise HTTPException(status_code=409, detail="Ya hay un servidor con ese nombre")
    n = NodoFreeswitch(**payload.model_dump())
    session.add(n)
    await session.commit()
    directorio.invalidar()
    gateways.ensure_dirs(n.nombre)
    return _out(n, {}, {}, {})


async def _nodo(session: AsyncSession, nodo_id: int) -> NodoFreeswitch:
    n = await session.get(NodoFreeswitch, nodo_id)
    if n is None:
        raise HTTPException(status_code=404, detail="Servidor no encontrado")
    return n


@router.put("/{nodo_id}")
async def editar(nodo_id: int, payload: NodoUpdate, session: AsyncSession = Depends(get_admin_session)):
    n = await _nodo(session, nodo_id)
    for clave, valor in payload.model_dump(exclude_none=True).items():
        setattr(n, clave, valor)
    await session.commit()
    directorio.invalidar()
    empresas, agentes = await _resumen(session)
    return _out(n, empresas, agentes, {})


@router.delete("/{nodo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def borrar(nodo_id: int, session: AsyncSession = Depends(get_admin_session)):
    n = await _nodo(session, nodo_id)
    if (await session.execute(select(Tenant.id).where(Tenant.nodo_id == nodo_id).limit(1))).first():
        raise HTTPException(status_code=409, detail="Tiene empresas: muévelas a otro servidor antes de borrarlo")
    await session.delete(n)
    await session.commit()
    directorio.invalidar()


@router.post("/{nodo_id}/probar")
async def probar(nodo_id: int, session: AsyncSession = Depends(get_admin_session)):
    await _nodo(session, nodo_id)
    await directorio.refrescar(forzar=True)
    return await _estado_en_vivo(nodo_id)


@router.put("/empresas/{tenant_id}")
async def asignar(tenant_id: int, payload: AsignarIn, session: AsyncSession = Depends(get_admin_session)):
    """Mueve una empresa de servidor: sus troncales pasan a la carpeta del
    servidor nuevo y se registran ahí. Sus teléfonos tienen que registrarse en
    el servidor nuevo (DNS de su dominio SIP)."""
    empresa = await session.get(Tenant, tenant_id)
    if empresa is None:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    destino = None
    if payload.nodo_id is not None:
        destino = await _nodo(session, payload.nodo_id)
        if not destino.activo:
            raise HTTPException(status_code=409, detail="Ese servidor está desactivado")
    if empresa.nodo_id == payload.nodo_id:
        return {"ok": True, "cambio": False}
    conectados = (await session.execute(select(func.count()).select_from(AgenteVivo).where(AgenteVivo.tenant_id == tenant_id))).scalar_one()
    if conectados and not payload.forzar:
        raise HTTPException(status_code=409, detail=f"La empresa tiene {conectados} agente(s) conectados: muévela fuera de la jornada o confirma")
    anterior = await session.get(NodoFreeswitch, empresa.nodo_id) if empresa.nodo_id else None
    nombre_ant, nombre_nuevo = (anterior.nombre if anterior else None), (destino.nombre if destino else None)
    troncales = (await session.execute(select(Trunk).where(Trunk.tenant_id == tenant_id))).scalars().all()
    empresa.nodo_id = payload.nodo_id
    await session.commit()
    for t in troncales:
        nombre_gw = gateways.nombre_gateway(t.name, empresa.slug)
        if t.enabled:
            try:
                gateways.write_gateway_file(t, empresa.slug, nombre_nuevo)
            except ValueError as exc:
                logger.error("Troncal %s no se pudo escribir en %s: %s", t.id, nombre_nuevo or "principal", exc)
        gateways.remove_gateway_file(nombre_gw, nombre_ant)
    directorio.invalidar()
    await directorio.refrescar(forzar=True)
    avisos = []
    for nodo_id in {anterior.id if anterior else None, payload.nodo_id}:
        try:
            await esl.api("sofia profile external rescan", nodo=nodo_id)
        except Exception as exc:
            avisos.append(f"No se pudo recargar las troncales en {directorio.nombre(nodo_id)}: {exc}")
    sip = destino.sip_host if destino else "el servidor principal"
    avisos.append(f"Los teléfonos de {empresa.name} tienen que registrarse en {sip} (DNS del dominio {empresa.sip_domain}).")
    return {"ok": True, "cambio": True, "avisos": avisos}
