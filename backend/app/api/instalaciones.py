"""Instalaciones locales: el lado de la CENTRAL (docs/plan-fase-k.md).

- `router` (Plataforma › Instalaciones locales, solo el rol plataforma, con
  la sesión del dueño): dar de alta el servidor de un cliente, darle su
  código de activación, suspenderlo o revocarlo.
- `publico` (sin sesión; lo llaman los servidores de los clientes):
  `activar` cambia el código por un token y la primera licencia firmada;
  `latido` (cada hora, con el token) sube el uso y devuelve la licencia al
  día. Tope por IP en los dos: el código es corto y se puede adivinar
  probando.
"""

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_admin_session
from app.core.limitador import LimiteIntentos, ip_cliente, limitar_uso
from app.models import Instalacion, Tenant
from app.services import licencia_firmada as lf
from app.services import licensing

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/plataforma/instalaciones", tags=["plataforma"])
publico = APIRouter(prefix="/api/licencia", tags=["licencia"])

_POR_IP_ACTIVAR = LimiteIntentos(maximo=10, ventana=600, bloqueo=900)
_POR_IP_LATIDO = LimiteIntentos(maximo=60, ventana=600, bloqueo=600)
# Un latido que no llega en 2 h (se mandan cada hora) se muestra como «sin contacto».
EN_LINEA = timedelta(hours=2)
_MAX_USO = 30


def _solo_central() -> None:
    if settings.modo_instalacion == "local":
        raise HTTPException(status_code=404, detail="Esta instalación no es una central")


# --- Plataforma -----------------------------------------------------------------------


class InstalacionIn(BaseModel):
    empresa_id: int
    nombre: str = Field(..., min_length=2, max_length=80)


def _salida(inst: Instalacion, empresa: Tenant | None) -> dict:
    ahora = datetime.utcnow()
    return {
        "id": inst.id,
        "nombre": inst.nombre,
        "empresa_id": inst.empresa_id,
        "empresa": empresa.name if empresa else None,
        "estado": inst.estado,
        "codigo_vence": inst.codigo_vence,
        "activada_at": inst.activada_at,
        "ultimo_latido": inst.ultimo_latido,
        "en_linea": bool(inst.ultimo_latido and ahora - inst.ultimo_latido < EN_LINEA),
        "version": inst.version,
        "ip": inst.ip,
        "uso": inst.uso or {},
        "created_at": inst.created_at,
    }


async def _traer(session: AsyncSession, inst_id: int) -> Instalacion:
    inst = await session.get(Instalacion, inst_id)
    if not inst:
        raise HTTPException(status_code=404, detail="Instalación no encontrada")
    return inst


def _dar_codigo(inst: Instalacion) -> str:
    codigo = lf.nuevo_codigo()
    inst.codigo_hash = lf.hash_codigo(codigo)
    inst.codigo_vence = datetime.utcnow() + lf.VIGENCIA_CODIGO
    return codigo


@router.get("")
async def listar(session: AsyncSession = Depends(get_admin_session)):
    _solo_central()
    filas = (await session.execute(select(Instalacion, Tenant).join(Tenant, Tenant.id == Instalacion.empresa_id)
                                   .order_by(Instalacion.id))).all()
    return {
        # Sin clave privada la central no puede emitir licencias: el panel lo avisa.
        "central_lista": bool(settings.licencia_clave_privada),
        "gracia_horas": settings.licencia_gracia_horas,
        "instalaciones": [_salida(i, t) for i, t in filas],
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def crear(payload: InstalacionIn, session: AsyncSession = Depends(get_admin_session)):
    """El código se muestra UNA vez: la central solo guarda su hash."""
    _solo_central()
    empresa = await session.get(Tenant, payload.empresa_id)
    if not empresa:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    inst = Instalacion(empresa_id=empresa.id, nombre=payload.nombre.strip(), estado="pendiente")
    codigo = _dar_codigo(inst)
    session.add(inst)
    await session.commit()
    await session.refresh(inst)
    logger.warning("Instalación local %s creada para la empresa %s", inst.id, empresa.slug)
    return {**_salida(inst, empresa), "codigo": codigo}


@router.post("/{inst_id}/codigo")
async def nuevo_codigo(inst_id: int, session: AsyncSession = Depends(get_admin_session)):
    """Otro código (el anterior se perdió o venció, o se reinstala el servidor).
    Al activarse con él, el token anterior deja de valer."""
    _solo_central()
    inst = await _traer(session, inst_id)
    if inst.estado == "revocada":
        raise HTTPException(status_code=400, detail="Una instalación revocada no se puede volver a activar")
    codigo = _dar_codigo(inst)
    await session.commit()
    return {**_salida(inst, await session.get(Tenant, inst.empresa_id)), "codigo": codigo}


async def _cambiar_estado(session: AsyncSession, inst_id: int, desde: tuple[str, ...], hacia: str) -> dict:
    _solo_central()
    inst = await _traer(session, inst_id)
    if inst.estado not in desde:
        raise HTTPException(status_code=400, detail=f"No se puede pasar de «{inst.estado}» a «{hacia}»")
    inst.estado = hacia
    if hacia == "revocada":
        inst.codigo_hash = None
        inst.codigo_vence = None
    await session.commit()
    logger.warning("Instalación local %s: %s", inst.id, hacia)
    return _salida(inst, await session.get(Tenant, inst.empresa_id))


@router.post("/{inst_id}/suspender")
async def suspender(inst_id: int, session: AsyncSession = Depends(get_admin_session)):
    """En el próximo latido recibe su licencia suspendida y deja de operar
    (los teléfonos siguen sonando; ver docs/plan-fase-k.md)."""
    return await _cambiar_estado(session, inst_id, ("activa",), "suspendida")


@router.post("/{inst_id}/reactivar")
async def reactivar(inst_id: int, session: AsyncSession = Depends(get_admin_session)):
    return await _cambiar_estado(session, inst_id, ("suspendida",), "activa")


@router.post("/{inst_id}/revocar")
async def revocar(inst_id: int, session: AsyncSession = Depends(get_admin_session)):
    """Para siempre. Conserva el token a propósito: así su próximo latido
    recibe la licencia suspendida en vez de quedarse con la última buena
    hasta que venza la gracia."""
    return await _cambiar_estado(session, inst_id, ("pendiente", "activa", "suspendida"), "revocada")


@router.delete("/{inst_id}", status_code=status.HTTP_204_NO_CONTENT)
async def borrar(inst_id: int, session: AsyncSession = Depends(get_admin_session)):
    _solo_central()
    inst = await _traer(session, inst_id)
    if inst.estado not in ("pendiente", "revocada"):
        raise HTTPException(status_code=400, detail="Primero revócala: una instalación en uso no se borra")
    await session.delete(inst)
    await session.commit()


# --- Lo que llaman los servidores de los clientes -------------------------------------


class ActivarIn(BaseModel):
    codigo: str = Field(..., min_length=8, max_length=40)
    version: str | None = Field(default=None, max_length=40)


class LatidoIn(BaseModel):
    version: str | None = Field(default=None, max_length=40)
    # Solo cantidades: {"extensiones": 12, "minutos_salientes_mes": 3400, …}.
    uso: dict[str, int] = Field(default_factory=dict)


async def emitir(session: AsyncSession, inst: Instalacion) -> dict:
    """La licencia firmada de `inst`, al día con su empresa y su plan."""
    empresa = await session.get(Tenant, inst.empresa_id)
    lic = await licensing.obtener(session, empresa.id)
    limites = {r: licensing.limite(lic, r) for r in lf.RECURSOS}
    doc = lf.documento(inst, empresa, lic, settings.licencia_gracia_horas, limites)
    try:
        return lf.firmar(doc, settings.licencia_clave_privada)
    except lf.LicenciaInvalida as exc:
        logger.error("No se pudo firmar la licencia de la instalación %s: %s", inst.id, exc)
        raise HTTPException(status_code=503, detail="La central no puede emitir licencias todavía. Avisa a soporte.")


@publico.post("/activar")
async def activar(payload: ActivarIn, request: Request, session: AsyncSession = Depends(get_admin_session)):
    _solo_central()
    ip = ip_cliente(request)
    limitar_uso(_POR_IP_ACTIVAR, ip, "Demasiados intentos de activación; espera unos minutos")
    inst = (
        await session.execute(select(Instalacion).where(Instalacion.codigo_hash == lf.hash_codigo(payload.codigo)))
    ).scalar_one_or_none()
    if not inst or inst.estado == "revocada":
        raise HTTPException(status_code=404, detail="Código de activación no válido. Revísalo o pide uno nuevo.")
    if not inst.codigo_vence or inst.codigo_vence < datetime.utcnow():
        raise HTTPException(status_code=410, detail="El código de activación venció. Pide uno nuevo.")
    token = lf.nuevo_token()
    inst.token_hash = lf.hash_secreto(token)
    inst.codigo_hash = None
    inst.codigo_vence = None
    if inst.estado == "pendiente":
        inst.estado = "activa"
    inst.activada_at = inst.ultimo_latido = datetime.utcnow()
    inst.version = payload.version
    inst.ip = ip[:64]
    firmada = await emitir(session, inst)
    await session.commit()
    logger.warning("Instalación local %s activada desde %s", inst.id, ip)
    return {"instalacion_id": inst.id, "token": token, **firmada}


@publico.post("/latido")
async def latido(payload: LatidoIn, request: Request, session: AsyncSession = Depends(get_admin_session)):
    _solo_central()
    ip = ip_cliente(request)
    limitar_uso(_POR_IP_LATIDO, ip)
    cabecera = request.headers.get("Authorization", "")
    token = cabecera[7:].strip() if cabecera.startswith("Bearer ") else ""
    inst = None
    if token:
        inst = (
            await session.execute(select(Instalacion).where(Instalacion.token_hash == lf.hash_secreto(token)))
        ).scalar_one_or_none()
    if not inst:
        raise HTTPException(status_code=401, detail="Instalación no reconocida")
    inst.ultimo_latido = datetime.utcnow()
    inst.version = payload.version
    inst.ip = ip[:64]
    inst.uso = {str(k)[:40]: int(v) for k, v in list(payload.uso.items())[:_MAX_USO]}
    firmada = await emitir(session, inst)
    await session.commit()
    return firmada
