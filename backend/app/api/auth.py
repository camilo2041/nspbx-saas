"""Inicio de sesión y datos de la sesión propia."""

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from pydantic import BaseModel, Field

from app.core import limitador, permissions
from app.core.auth import usuario_actual
from app.core.config import settings
from app.core.database import get_admin_session, get_session
from app.core.security import (
    crear_token,
    generar_refresh_token,
    hash_password,
    hash_refresh_token,
    verificar_password,
)
from app.models import DeviceToken, RefreshToken, Tenant, User
from app.schemas import (
    CambiarPasswordRequest,
    DeviceTokenIn,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    SesionOut,
    UserOut,
)
from app.services import esl, push, turn
from app.services.sesiones import revocar_sesiones

# Un refresh token recién rotado puede llegar dos veces por una carrera legítima
# (doble toque, reintento de red); pasado este margen se considera robo.
REUSO_TOLERANCIA_S = 30
from app.services.ajustes import ajustes_de

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def usuario_out(u: User) -> UserOut:
    datos = UserOut.model_validate(u)
    datos.extension_number = u.extension.number if u.extension else None
    return datos


async def _modulos_de(session: AsyncSession, u: User) -> list[str]:
    """Los módulos habilitados de la empresa del usuario (voicebot/pbx).
    La plataforma no tiene empresa → lista vacía."""
    if not u.tenant_id:
        return []
    ten = await session.get(Tenant, u.tenant_id)
    return ten.modules_list if ten else []


def _sesion(u: User, modulos: list[str] | None = None, refresh_token: str | None = None) -> SesionOut:
    # La empresa viaja dentro del token: es lo que permite atar cada
    # petición a su aislamiento sin consultar la base primero (ver
    # security.crear_token y core/auth.sesion_obligatoria).
    token, vida = crear_token(u.id, u.role, u.tenant_id)
    return SesionOut(
        token=token,
        expira_en=vida,
        usuario=usuario_out(u),
        permisos=sorted(permissions.permisos_de(u.role)),
        modulos=modulos or [],
        refresh_token=refresh_token,
    )


async def _nuevo_refresh_token(
    session: AsyncSession, user_id: int, platform: str | None = None
) -> str:
    """Crea y guarda un refresh token nuevo para `user_id`, devuelve el
    texto plano (lo único que ve el cliente)."""
    token, token_hash, vence = generar_refresh_token()
    session.add(
        RefreshToken(
            user_id=user_id,
            token_hash=token_hash,
            platform=platform,
            expires_at=vence.replace(tzinfo=None),
        )
    )
    await session.commit()
    return token


@router.post("/login", response_model=SesionOut)
async def login(payload: LoginRequest, request: Request, session: AsyncSession = Depends(get_admin_session)):
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
    nombre = payload.username.strip().lower()[:100]
    ip = limitador.ip_cliente(request)
    # Antes de tocar la base o gastar un PBKDF2: quien ya está bloqueado no obtiene ni una pista.
    limitador.exigir_libre(ip, nombre)
    usuario = (
        (await session.execute(select(User).where(User.username == nombre)))
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
        limitador.registrar_fallo(ip, nombre)
        logger.info("Intento de acceso fallido para '%s' desde %s", payload.username[:100], ip)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario o contraseña incorrectos")
    limitador.registrar_exito(ip, nombre)
    if not usuario.enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Esta cuenta está desactivada")
    if usuario.tenant_id is not None:
        empresa = await session.get(Tenant, usuario.tenant_id)
        if not empresa or not empresa.enabled:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="La empresa está desactivada")

    usuario.last_login_at = datetime.utcnow()
    await session.commit()
    await session.refresh(usuario)

    # El login queda atado al subdominio del panel desde el que se entra.
    # Cada empresa tiene su subdominio (ver Tenant.subdomain): si entrás
    # por "consultorio-andino.<base>" y tu cuenta es de otra empresa, no
    # podés iniciar sesión ahí. Si el subdominio no pertenece a ninguna
    # empresa (el dominio base, "www", etc.), se ignora.
    sub = (payload.subdomain or "").strip().lower()
    if sub and sub not in ("www", "localhost", "127.0.0.1"):
        ten = (
            await session.execute(select(Tenant).where(Tenant.subdomain == sub))
        ).scalar_one_or_none()
        # El usuario de PLATAFORMA (sin empresa) no está atado a ningún
        # subdominio: puede entrar desde cualquier lado para administrar
        # las empresas. El resto DEBE pertenecer a la empresa del
        # subdominio.
        if ten and usuario.tenant_id is not None and usuario.tenant_id != ten.id:
            logger.info(
                "Login rechazado por subdominio: %s intentó entrar por '%s' (empresa %s)",
                payload.username, sub, ten.id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Esta cuenta no pertenece a la empresa de este dominio",
            )

    logger.info("Sesión iniciada: %s (%s)", usuario.username, usuario.role)
    refresh = await _nuevo_refresh_token(session, usuario.id)
    return _sesion(usuario, await _modulos_de(session, usuario), refresh_token=refresh)


@router.post("/refresh", response_model=SesionOut)
async def refrescar(payload: RefreshRequest, session: AsyncSession = Depends(get_admin_session)):
    """Cambia un refresh token por una sesión nueva, sin pedir contraseña.

    Es lo que usa la app móvil para no obligar a loguearse cada 8 horas
    (el JWT normal, ver core/security.HORAS_DE_SESION). Corre con la
    sesión del DUEÑO por el mismo motivo que /login: todavía no se sabe
    la empresa hasta leer a quién pertenece el token.

    El token viejo se revoca acá mismo (rotación): si alguien más lo
    tuviera copiado, dejaría de servir apenas el dueño legítimo lo usa una
    vez, en vez de seguir siendo válido hasta que venza solo.
    """
    token_hash = hash_refresh_token(payload.refresh_token)
    fila = (
        # FOR UPDATE: dos renovaciones simultáneas con el mismo token se
        # serializan; la segunda ve el token ya revocado en vez de sacar otro
        # par válido (antes las dos pasaban y el token viejo "se duplicaba").
        await session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update()
        )
    ).scalar_one_or_none()

    ahora = datetime.now(timezone.utc).replace(tzinfo=None)
    if fila and fila.revoked_at is not None and (ahora - fila.revoked_at).total_seconds() > REUSO_TOLERANCIA_S:
        # Un token ya rotado que vuelve a aparecer pasada la tolerancia: alguien
        # lo copió. No se sabe quién, así que se cierran todas las sesiones de
        # esa cuenta; el dueño legítimo vuelve a entrar con su contraseña.
        dueno = await session.get(User, fila.user_id)
        if dueno:
            await revocar_sesiones(session, dueno)
            await session.commit()
            logger.warning("Refresh token reutilizado: sesiones de '%s' cerradas", dueno.username)
    if not fila or fila.revoked_at is not None or fila.expires_at < ahora:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesión inválida o vencida")

    usuario = await session.get(User, fila.user_id)
    if not usuario or not usuario.enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Esta cuenta está desactivada")
    if usuario.tenant_id is not None:
        empresa = await session.get(Tenant, usuario.tenant_id)
        if not empresa or not empresa.enabled:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="La empresa está desactivada")

    fila.revoked_at = ahora
    nuevo = await _nuevo_refresh_token(session, usuario.id, fila.platform)
    return _sesion(usuario, await _modulos_de(session, usuario), refresh_token=nuevo)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def cerrar_sesion(payload: LogoutRequest, session: AsyncSession = Depends(get_admin_session)):
    """Revoca el refresh token de la app móvil. Idempotente: si ya estaba
    vencido o revocado, o no existe, no es un error — el resultado que le
    importa a quien llama (poder cerrar sesión) ya se cumplió."""
    token_hash = hash_refresh_token(payload.refresh_token)
    fila = (
        await session.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    ).scalar_one_or_none()
    if fila and fila.revoked_at is None:
        fila.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await session.commit()


@router.get("/me", response_model=SesionOut)
async def yo(
    usuario: User = Depends(usuario_actual),
    session: AsyncSession = Depends(get_session),
):
    """Renueva el token y devuelve permisos al día.

    La interfaz lo llama al cargar: así un cambio de rol se aplica al
    recargar la página, sin esperar a que caduque la sesión.
    """
    return _sesion(usuario, await _modulos_de(session, usuario))


@router.post("/password", response_model=SesionOut)
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
    # Cambiar la contraseña cierra las sesiones de TODOS los demás dispositivos
    # (quien la tuviera robada pierde el acceso). El dispositivo actual sigue:
    # recibe una sesión nueva en la respuesta.
    await revocar_sesiones(session, fresco)
    await session.commit()
    await session.refresh(fresco)
    nuevo_refresh = await _nuevo_refresh_token(session, fresco.id)
    return _sesion(fresco, await _modulos_de(session, fresco), refresh_token=nuevo_refresh)


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

    ajustes = await ajustes_de(session)
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


class ProbarPushIn(BaseModel):
    segundos: int = Field(default=15, ge=0, le=60)


@router.post("/probar-push")
async def probar_push(
    payload: ProbarPushIn,
    usuario: User = Depends(usuario_actual),
    session: AsyncSession = Depends(get_session),
):
    """Manda al teléfono de quien pide una llamada de PRUEBA por push, tras unos segundos.

    Sirve para comprobar de punta a punta, sin que nadie llame, que el aviso despierta la app con
    la pantalla apagada: se pulsa, se bloquea el teléfono y a los N segundos debe sonar. El
    resultado real de Firebase/Apple se devuelve para poder leer el motivo si falla."""
    dispositivos = (
        await session.execute(select(DeviceToken).where(DeviceToken.user_id == usuario.id))
    ).scalars().all()
    if not dispositivos:
        raise HTTPException(
            status_code=409,
            detail="Este teléfono todavía no registró el aviso de llamadas. Cierra sesión y vuelve a entrar con la "
            "app ya configurada con Firebase (Android) o Apple (iPhone).",
        )
    if not push.android_configurado() and not (settings.apns_key_id and settings.apns_auth_key):
        raise HTTPException(status_code=503, detail="El servidor no tiene configurados los avisos (Firebase/Apple).")

    evento = {
        "eventId": str(uuid.uuid4()),
        "serverCallId": str(uuid.uuid4()),
        "hasVideo": False,
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "caller": {"id": "prueba", "displayName": "Prueba de NSPBX", "phoneNumber": None},
        "metadata": {"prueba": True},
    }

    async def _enviar_luego() -> None:
        await asyncio.sleep(payload.segundos)
        for d in dispositivos:
            try:
                if d.token_type == "APNS_VOIP":
                    await push.enviar_voip_ios(d.token, evento)
                elif d.token_type == "FCM":
                    motivo = await push.enviar_push_android(d.token, evento)
                    if motivo:
                        logger.warning("Prueba de push a %s falló: %s", usuario.username, motivo)
            except Exception:
                logger.exception("Prueba de push: error con un dispositivo")

    if payload.segundos == 0:
        await _enviar_luego()
    else:
        asyncio.create_task(_enviar_luego())
    return {"ok": True, "dispositivos": len(dispositivos), "segundos": payload.segundos}


@router.post("/dispositivo", status_code=status.HTTP_204_NO_CONTENT)
async def registrar_dispositivo(
    payload: DeviceTokenIn,
    usuario: User = Depends(usuario_actual),
    session: AsyncSession = Depends(get_session),
):
    """Guarda (o reemplaza) el push token del teléfono de la app móvil,
    para poder despertarla con un push de voz cuando entre una llamada a
    su extensión (ver services/push.py). Una fila por usuario+plataforma:
    volver a registrar simplemente actualiza el token vigente."""
    existente = (
        await session.execute(
            select(DeviceToken).where(
                DeviceToken.user_id == usuario.id, DeviceToken.platform == payload.platform
            )
        )
    ).scalar_one_or_none()
    if existente:
        existente.token = payload.token
        existente.token_type = payload.token_type
        existente.extension_id = usuario.extension_id
    else:
        session.add(
            DeviceToken(
                user_id=usuario.id,
                extension_id=usuario.extension_id,
                platform=payload.platform,
                token=payload.token,
                token_type=payload.token_type,
            )
        )
    await session.commit()


@router.delete("/dispositivo/{platform}", status_code=status.HTTP_204_NO_CONTENT)
async def desregistrar_dispositivo(
    platform: str,
    usuario: User = Depends(usuario_actual),
    session: AsyncSession = Depends(get_session),
):
    """Borra el push token al cerrar sesión en la app: sin esto, alguien
    que cierra sesión seguiría recibiendo pushes de llamadas que ya no
    puede ver en ninguna pantalla."""
    await session.execute(
        delete(DeviceToken).where(DeviceToken.user_id == usuario.id, DeviceToken.platform == platform)
    )
    await session.commit()


# Hash de una contraseña que nadie tiene, solo para gastar el mismo tiempo
# que una verificación real cuando el usuario no existe.
_HASH_DESCARTE = hash_password("nspbx-usuario-inexistente")
