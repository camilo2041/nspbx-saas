"""Supervisor y wallboard (docs/plan-contact-center.md, fase 5).

Ver (`supervision:ver`): agentes y campañas en vivo y el resumen del
wallboard. Intervenir (`supervision:intervenir`): escuchar, susurrar e
intervenir, forzar pausa o salida, nivel de marcación en caliente, pausar o
reanudar una campaña y los tokens del wallboard.

Todo lo que cambia algo es POST/PUT/DELETE bajo /api/: queda en la auditoría
con quién, a quién (el id en la ruta) y cuándo, sin código extra.

El wallboard de una TV sin usuario entra por `/api/wallboard` con un token de
solo lectura en la cabecera X-Wallboard-Token (nunca en la URL: la ruta de
una URL termina en los logs de los proxies).
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import permissions
from app.core.auth import requiere, usuario_actual
from app.core.database import async_session, get_session, sesion_de_empresa, traer_propio
from app.models import Campaign, CampaignNumber, Tenant, TokenWallboard, User
from app.services import supervision
from app.services.supervision import ErrorSupervision, monitoreo

router = APIRouter(prefix="/api/supervision", tags=["supervision"])
publico = APIRouter(tags=["supervision"])

_INTERVENIR = [Depends(requiere(permissions.SUPERVISION_INTERVENIR))]


class MonitorearIn(BaseModel):
    modo: str = Field(..., pattern="^(escuchar|susurrar|intervenir)$")


class PausaIn(BaseModel):
    codigo_pausa_id: int | None = None


class SacarIn(BaseModel):
    cortar_llamada: bool = False


class NivelIn(BaseModel):
    nivel_marcacion: float | None = Field(default=None, ge=1.0, le=5.0)
    nivel_max: float | None = Field(default=None, ge=1.0, le=5.0)
    abandono_objetivo: float | None = Field(default=None, ge=0.5, le=10.0)


class TokenIn(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=80)
    dias: int = Field(default=30, ge=1, le=supervision.DURACION_MAX_WALLBOARD.days)


def _error(exc: ErrorSupervision) -> HTTPException:
    return HTTPException(status_code=exc.codigo, detail=exc.mensaje)


def _monitor_out(m: supervision.Monitor | None) -> dict | None:
    if m is None:
        return None
    # El token es para que el softphone del panel conteste solo esta llamada.
    return {"agente_id": m.agente_id, "modo": m.modo, "contestado": m.contestado, "token": m.token}


# --- En vivo -------------------------------------------------------------------------------------


@router.get("/agentes")
async def agentes_en_vivo(session: AsyncSession = Depends(get_session)):
    return await supervision.agentes_en_vivo(session)


@router.get("/campanas")
async def campanas_en_vivo(session: AsyncSession = Depends(get_session)):
    return await supervision.campanas_en_vivo(session)


@router.get("/resumen")
async def resumen(session: AsyncSession = Depends(get_session), usuario: User = Depends(usuario_actual)):
    if usuario.tenant_id is None:
        raise HTTPException(status_code=403, detail="El wallboard es de cada empresa")
    return await supervision.resumen(session, usuario.tenant_id)


# --- Monitoreo -----------------------------------------------------------------------------------


@router.get("/monitoreo", dependencies=_INTERVENIR)
async def mi_monitoreo(session: AsyncSession = Depends(get_session), usuario: User = Depends(usuario_actual)):
    return _monitor_out(await monitoreo.de_supervisor(session, usuario.id) if usuario.tenant_id else None)


@router.post("/agentes/{user_id}/monitorear", dependencies=_INTERVENIR)
async def monitorear(user_id: int, payload: MonitorearIn, session: AsyncSession = Depends(get_session),
                     usuario: User = Depends(usuario_actual)):
    try:
        m = await monitoreo.iniciar(session, usuario, user_id, payload.modo)
    except ErrorSupervision as exc:
        raise _error(exc)
    await session.commit()
    return _monitor_out(m)


@router.post("/monitoreo/modo", dependencies=_INTERVENIR)
async def cambiar_modo(payload: MonitorearIn, session: AsyncSession = Depends(get_session), usuario: User = Depends(usuario_actual)):
    m = await monitoreo.de_supervisor(session, usuario.id) if usuario.tenant_id else None
    if m is None:
        raise HTTPException(status_code=404, detail="No estás monitoreando a nadie")
    try:
        await monitoreo.cambiar_modo(session, m, payload.modo)
    except ErrorSupervision as exc:
        raise _error(exc)
    await session.commit()
    return _monitor_out(m)


@router.post("/monitoreo/colgar", dependencies=_INTERVENIR)
async def dejar_de_monitorear(session: AsyncSession = Depends(get_session), usuario: User = Depends(usuario_actual)):
    m = await monitoreo.de_supervisor(session, usuario.id) if usuario.tenant_id else None
    if m is not None:
        await monitoreo.detener(session, m)
        await session.commit()
    return {"ok": True}


# --- Acciones sobre el agente ----------------------------------------------------------------------


@router.post("/agentes/{user_id}/pausa", dependencies=_INTERVENIR)
async def forzar_pausa(user_id: int, payload: PausaIn, session: AsyncSession = Depends(get_session)):
    try:
        vivo = await supervision.forzar_pausa(session, user_id, payload.codigo_pausa_id)
    except ErrorSupervision as exc:
        raise _error(exc)
    pendiente = vivo.pausa_pendiente_id is not None
    await session.commit()
    return {"ok": True, "pendiente": pendiente}


@router.post("/agentes/{user_id}/sacar", dependencies=_INTERVENIR)
async def sacar(user_id: int, payload: SacarIn, session: AsyncSession = Depends(get_session)):
    try:
        await supervision.sacar(session, user_id, payload.cortar_llamada)
    except ErrorSupervision as exc:
        raise _error(exc)
    await session.commit()
    return {"ok": True}


# --- Campañas en caliente ---------------------------------------------------------------------------


async def _campana(session: AsyncSession, campaign_id: int) -> Campaign:
    campana = await traer_propio(session, Campaign, campaign_id)
    if campana is None:
        raise HTTPException(status_code=404, detail="Campaña no encontrada")
    return campana


@router.put("/campanas/{campaign_id}/nivel", dependencies=_INTERVENIR)
async def cambiar_nivel(campaign_id: int, payload: NivelIn, session: AsyncSession = Depends(get_session)):
    campana = await _campana(session, campaign_id)
    cambios = payload.model_dump(exclude_none=True)
    if not cambios:
        raise HTTPException(status_code=400, detail="Nada que cambiar")
    for clave, valor in cambios.items():
        setattr(campana, clave, valor)
    if "nivel_marcacion" in cambios:
        campana.nivel_actual = None
    await session.commit()
    return {"ok": True, **{k: getattr(campana, k) for k in ("nivel_marcacion", "nivel_max", "abandono_objetivo")}}


@router.post("/campanas/{campaign_id}/pausar", dependencies=_INTERVENIR)
async def pausar_campana(campaign_id: int, session: AsyncSession = Depends(get_session)):
    """Deja de lanzar llamadas nuevas; las que están en curso siguen."""
    campana = await _campana(session, campaign_id)
    campana.status = "paused"
    await session.commit()
    return {"ok": True, "status": campana.status}


@router.post("/campanas/{campaign_id}/reanudar", dependencies=_INTERVENIR)
async def reanudar_campana(campaign_id: int, session: AsyncSession = Depends(get_session)):
    campana = await _campana(session, campaign_id)
    if campana.metodo in ("manual", "vista_previa", "voizbot"):
        raise HTTPException(status_code=400, detail="Esta campaña no marca sola: no hay qué reanudar")
    hay = (
        await session.execute(
            select(CampaignNumber.id).where(CampaignNumber.campaign_id == campaign_id, CampaignNumber.status == "pending").limit(1)
        )
    ).first()
    if not hay:
        raise HTTPException(status_code=400, detail="No hay números pendientes")
    campana.status = "running"
    campana.started_at = campana.started_at or datetime.utcnow()
    campana.finished_at = None
    await session.commit()
    return {"ok": True, "status": campana.status}


# --- Tokens del wallboard ------------------------------------------------------------------------------


def _token_out(t: TokenWallboard) -> dict:
    ahora = datetime.utcnow()
    return {
        "id": t.id,
        "nombre": t.nombre,
        "vence": t.vence.isoformat(),
        "vigente": t.revocado_at is None and t.vence > ahora,
        "revocado_at": t.revocado_at.isoformat() if t.revocado_at else None,
        "ultimo_uso_at": t.ultimo_uso_at.isoformat() if t.ultimo_uso_at else None,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


@router.get("/wallboard/tokens")
async def listar_tokens(session: AsyncSession = Depends(get_session)):
    filas = (await session.execute(select(TokenWallboard).order_by(TokenWallboard.id.desc()))).scalars().all()
    return [_token_out(t) for t in filas]


@router.post("/wallboard/tokens", status_code=status.HTTP_201_CREATED, dependencies=_INTERVENIR)
async def crear_token(payload: TokenIn, session: AsyncSession = Depends(get_session), usuario: User = Depends(usuario_actual)):
    if usuario.tenant_id is None:
        raise HTTPException(status_code=403, detail="El wallboard es de cada empresa")
    token, huella = supervision.nuevo_token()
    fila = TokenWallboard(tenant_id=usuario.tenant_id, nombre=payload.nombre.strip(), token_hash=huella,
                          creado_por=usuario.id, vence=datetime.utcnow() + timedelta(days=payload.dias))
    session.add(fila)
    await session.commit()
    # Única vez que se ve el token: se guarda solo su hash.
    return {**_token_out(fila), "token": token}


@router.delete("/wallboard/tokens/{token_id}", dependencies=_INTERVENIR)
async def revocar_token(token_id: int, session: AsyncSession = Depends(get_session)):
    fila = await traer_propio(session, TokenWallboard, token_id)
    if fila is None:
        raise HTTPException(status_code=404, detail="Token no encontrado")
    fila.revocado_at = fila.revocado_at or datetime.utcnow()
    await session.commit()
    return {"ok": True}


# --- Wallboard sin usuario --------------------------------------------------------------------------------

_NO_VALIDO = HTTPException(status_code=401, detail="Token de wallboard no válido o vencido")


@publico.get("/api/wallboard")
async def wallboard(x_wallboard_token: str | None = Header(default=None)):
    if not x_wallboard_token or len(x_wallboard_token) > 100:
        raise _NO_VALIDO
    ahora = datetime.utcnow()
    # Sesión del dueño solo para encontrar el token por su hash (todavía no
    # se sabe de qué empresa es); los datos se leen con la de la empresa.
    async with async_session() as dueno:
        fila = (
            await dueno.execute(select(TokenWallboard).where(TokenWallboard.token_hash == supervision.hash_token(x_wallboard_token)))
        ).scalar_one_or_none()
        if fila is None or fila.revocado_at is not None or fila.vence <= ahora:
            raise _NO_VALIDO
        empresa = await dueno.get(Tenant, fila.tenant_id)
        if empresa is None or not empresa.enabled:
            raise _NO_VALIDO
        if fila.ultimo_uso_at is None or ahora - fila.ultimo_uso_at > timedelta(minutes=1):
            fila.ultimo_uso_at = ahora
            await dueno.commit()
        tenant_id, nombre = fila.tenant_id, empresa.name
    async with sesion_de_empresa(tenant_id) as session:
        datos = await supervision.resumen(session, tenant_id)
    return {**datos, "empresa": nombre}

