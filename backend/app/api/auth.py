"""Inicio de sesión y datos de la sesión propia."""

import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pydantic import BaseModel

from app.core import permissions
from app.core.auth import usuario_actual
from app.core.database import get_admin_session, get_session
from app.core.security import crear_token, hash_password, verificar_password
from app.models import SystemSettings, User
from app.schemas import CambiarPasswordRequest, LoginRequest, SesionOut, UserOut
from app.services import esl, turn

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def usuario_out(u: User) -> UserOut:
    datos = UserOut.model_validate(u)
    datos.extension_number = u.extension.number if u.extension else None
    return datos


def _sesion(u: User) -> SesionOut:
    # La empresa viaja dentro del token: es lo que permite atar cada
    # petición a su aislamiento sin consultar la base primero (ver
    # security.crear_token y core/auth.sesion_obligatoria).
    token, vida = crear_token(u.id, u.role, u.tenant_id)
    return SesionOut(
        token=token,
        expira_en=vida,
        usuario=usuario_out(u),
        permisos=sorted(permissions.permisos_de(u.role)),
    )


@router.post("/login", response_model=SesionOut)
async def login(payload: LoginRequest, session: AsyncSession = Depends(get_admin_session)):
    """Única puerta que consulta `users` sin estar atada a una empresa.

    Usa la sesión del DUEÑO, que no pasa por Row-Level Security, porque
    acá todavía no se sabe a qué empresa pertenece quien escribió el
    usuario: esa misma fila es la que lo dice. Con la sesión normal, la
    política no encontraría empresa, la consulta devolvería vacío y
    cualquier intento de entrar terminaría en "usuario o contraseña
    incorrectos" — aun con la contraseña bien.

    Es una excepción deliberada y acotada: busca por `username`, que es
    único en toda la plataforma, y no expone ningún dato de negocio.
    """
    usuario = (
        (await session.execute(select(User).where(User.username == payload.username.strip().lower())))
        .unique()
        .scalar_one_or_none()
    )

    # Se verifica la contraseña incluso si el usuario no existe, contra un
    # hash de descarte. Sin esto, un usuario inexistente responde al
    # instante y uno real tarda lo que tarda el PBKDF2: esa diferencia de
    # tiempo permite averiguar qué usuarios existen.
    hash_referencia = usuario.password_hash if usuario else _HASH_DESCARTE
    correcta = await asyncio.to_thread(verificar_password, payload.password, hash_referencia)

    if not usuario or not correcta:
        logger.info("Intento de acceso fallido para '%s'", payload.username)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario o contraseña incorrectos")
    if not usuario.enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Esta cuenta está desactivada")

    usuario.last_login_at = datetime.utcnow()
    await session.commit()
    await session.refresh(usuario)
    logger.info("Sesión iniciada: %s (%s)", usuario.username, usuario.role)
    return _sesion(usuario)


@router.get("/me", response_model=SesionOut)
async def yo(usuario: User = Depends(usuario_actual)):
    """Renueva el token y devuelve permisos al día.

    La interfaz lo llama al cargar: así un cambio de rol se aplica al
    recargar la página, sin esperar a que caduque la sesión.
    """
    return _sesion(usuario)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def cambiar_password(
    payload: CambiarPasswordRequest,
    usuario: User = Depends(usuario_actual),
    session: AsyncSession = Depends(get_session),
):
    """Cambio de contraseña propia. Exige la actual aunque haya sesión
    abierta: si alguien deja el equipo desbloqueado, que no pueda quedarse
    con la cuenta."""
    if not await asyncio.to_thread(verificar_password, payload.password_actual, usuario.password_hash):
        raise HTTPException(status_code=400, detail="La contraseña actual no es correcta")
    if payload.password_actual == payload.password_nueva:
        raise HTTPException(status_code=400, detail="La contraseña nueva debe ser distinta de la actual")

    fresco = await session.get(User, usuario.id)
    fresco.password_hash = await asyncio.to_thread(hash_password, payload.password_nueva)
    await session.commit()


@router.get("/mi-entorno")
async def mi_entorno(
    usuario: User = Depends(usuario_actual), session: AsyncSession = Depends(get_session)
):
    """Lo justo para que el softphone se registre: la extensión PROPIA y
    la dirección del servidor SIP.

    Existe para que el softphone no tenga que pedir /api/extensions ni
    /api/system/settings. Esas dos respuestas traen todas las claves SIP y
    las API keys de los proveedores de IA; un asesor solo necesita su
    línea, y esto es exactamente eso.
    """
    if not permissions.puede(usuario.role, permissions.SOFTPHONE_USAR):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tu rol no usa el softphone")

    ajustes = await session.get(SystemSettings, 1)
    extension = None
    if usuario.extension:
        # Si FreeSWITCH no responde, que el softphone igual cargue en
        # "no molestar apagado" en vez de romper toda la pantalla — el
        # botón de DND ya se encarga de avisar si falla al tocarlo.
        try:
            dnd = await esl.dnd_status(usuario.extension.number)
        except Exception:
            dnd = False
        extension = {
            "id": usuario.extension.id,
            "number": usuario.extension.number,
            "password": usuario.extension.password,
            "caller_id_name": usuario.extension.caller_id_name,
            "enabled": usuario.extension.enabled,
            "dnd": dnd,
        }
    return {
        "extension": extension,
        # Se calculan por pedido y no se guardan: llevan firma con
        # vencimiento, así que una lista cacheada quedaría inservible.
        "ice_servers": turn.ice_servers(usuario.extension.number if usuario.extension else usuario.username),
        "fs_domain": ajustes.fs_domain if ajustes else None,
        "sip_ws_url": ajustes.sip_ws_url if ajustes else None,
        "sip_server_ip": ajustes.sip_server_ip if ajustes else None,
        "sip_server_port": ajustes.sip_server_port if ajustes else None,
    }


class DndRequest(BaseModel):
    enabled: bool


@router.post("/dnd")
async def poner_dnd(payload: DndRequest, usuario: User = Depends(usuario_actual)):
    """Prender o apagar "no molestar" desde el botón del softphone —
    mismo efecto que marcar *78/*79 desde cualquier teléfono, ver
    app/services/config_generator.py:_append_dnd_feature_codes.

    Solo la extensión PROPIA: no hay forma de silenciar el teléfono de
    otra persona desde acá, ni siquiera para un admin.
    """
    if not usuario.extension:
        raise HTTPException(status_code=400, detail="Tu usuario no tiene una extensión asignada")
    try:
        await esl.dnd_set(usuario.extension.number, payload.enabled)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"FreeSWITCH no disponible: {exc}")
    return {"ok": True, "dnd": payload.enabled}


# Hash de una contraseña que nadie tiene, solo para gastar el mismo tiempo
# que una verificación real cuando el usuario no existe.
_HASH_DESCARTE = hash_password("nspbx-usuario-inexistente")
