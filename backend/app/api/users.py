"""Alta, baja y modificación de usuarios. Solo para administradores."""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import usuario_out
from app.core import permissions
from app.core.auth import requiere, usuario_actual
from app.core import validacion
from app.core.database import get_session, tenant_de_sesion, traer_propio
from app.core.security import hash_password
from app.services.sesiones import revocar_sesiones
from app.models import Extension, Tenant, User
from app.services import licensing
from app.services.numeracion import numero_en_uso, siguiente_libre
from app.schemas import UserCreate, UserOut, UserUpdate

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/users",
    tags=["users"],
    dependencies=[Depends(requiere(permissions.USUARIOS_GESTIONAR))],
)


async def _validar_extension(session: AsyncSession, rol: str, extension_id: int | None) -> None:
    """Un asesor sin extensión no puede atender llamadas ni ver las suyas,
    así que no se permite crearlo a medias."""
    if extension_id is None:
        if rol in permissions.REQUIERE_EXTENSION:
            raise HTTPException(status_code=400, detail="Un asesor necesita una extensión asignada")
        return
    if not await traer_propio(session, Extension, extension_id):
        raise HTTPException(status_code=400, detail="La extensión indicada no existe")


async def _extension_libre(session: AsyncSession, extension_id: int | None, excepto: int | None = None) -> None:
    """Dos personas compartiendo extensión rompen el filtro de "mis
    llamadas" y el softphone: la segunda registra sobre la primera."""
    if extension_id is None:
        return
    q = select(User).where(User.extension_id == extension_id)
    if excepto is not None:
        q = q.where(User.id != excepto)
    otro = (await session.execute(q)).unique().scalars().first()
    if otro:
        raise HTTPException(
            status_code=400, detail=f"Esa extensión ya está asignada a {otro.full_name}"
        )


@router.get("", response_model=list[UserOut])
async def listar(session: AsyncSession = Depends(get_session)):
    filas = (await session.execute(select(User).order_by(User.full_name))).unique().scalars().all()
    return [usuario_out(u) for u in filas]


@router.get("/roles")
async def roles(usuario: User = Depends(usuario_actual)):
    """Catálogo de roles con su descripción, para que la interfaz no
    tenga que repetir estos textos.

    Los permisos que lista son los EFECTIVOS de esta empresa, no los de
    fábrica: si se personalizaron (ver /api/role-permissions), lo que se
    muestra al asignar un rol tiene que coincidir con lo que ese rol podrá
    hacer de verdad."""
    return [
        {
            "value": rol,
            "label": permissions.ETIQUETAS[rol],
            "description": permissions.DESCRIPCIONES[rol],
            "requiere_extension": rol in permissions.REQUIERE_EXTENSION,
            "permisos": sorted(permissions.permisos_de(rol, usuario.tenant_id)),
        }
        # "plataforma" no se ofrece: no es asignable desde un panel de empresa
        # (ver _ROLES_PATRON en los esquemas).
        for rol in permissions.ROLES
        if rol != permissions.PLATAFORMA
    ]


async def _crear_extension(session: AsyncSession, payload: UserCreate) -> Extension:
    """La extensión de «Agregar persona»: mismas reglas que crearla desde
    Extensiones (licencia, cupo del plan, número libre), con clave segura
    generada y el nombre de la persona como identificador de llamada."""
    tid = tenant_de_sesion(session)
    if tid is not None:
        empresa = await session.get(Tenant, tid)
        if empresa and not empresa.has_module("pbx"):
            raise HTTPException(status_code=403, detail="Tu plan no incluye la central telefónica")
        lic = await licensing.obtener(session, tid)
        st = licensing.estado(lic)
        if st != "ok":
            raise HTTPException(status_code=402, detail=f"La licencia de tu empresa está {st}. Renovala para seguir operando.")
        if not await licensing.hay_cupo(session, lic, "max_extensions", await licensing.contar_extensiones(session, tid)):
            raise HTTPException(status_code=402, detail="Alcanzaste el límite de extensiones de tu plan. Mejora la licencia para agregar más.")
    numero = payload.numero_extension or await siguiente_libre(session)
    if uso := await numero_en_uso(session, numero):
        raise HTTPException(status_code=409, detail=f"El número {numero} ya lo usa {uso}")
    # El nombre va en el identificador de llamada solo si pasa la misma
    # validación que en Extensiones (sin comillas ni caracteres de control).
    nombre = payload.full_name.strip()[:80]
    ext = Extension(
        number=numero,
        password=validacion.generar_clave_sip(),
        caller_id_name=nombre if validacion.NOMBRE_VISIBLE_RE.fullmatch(nombre) else None,
    )
    session.add(ext)
    await session.flush()
    return ext


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def crear(payload: UserCreate, session: AsyncSession = Depends(get_session)):
    if payload.crear_extension and payload.extension_id is None:
        extension_id = (await _crear_extension(session, payload)).id
    else:
        extension_id = payload.extension_id
        await _validar_extension(session, payload.role, extension_id)
        await _extension_libre(session, extension_id)

    datos = payload.model_dump(exclude={"password", "crear_extension", "numero_extension"})
    datos["extension_id"] = extension_id
    usuario = User(**datos, password_hash=await asyncio.to_thread(hash_password, payload.password))
    session.add(usuario)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise HTTPException(status_code=400, detail="Ese nombre de usuario ya existe")
    await session.refresh(usuario)
    logger.info("Usuario creado: %s (%s)", usuario.username, usuario.role)
    return usuario_out(usuario)


async def _ultimo_admin(session: AsyncSession, excepto: int) -> bool:
    activos = (
        await session.execute(
            select(func.count(User.id)).where(
                User.role == permissions.ADMIN, User.enabled.is_(True), User.id != excepto
            )
        )
    ).scalar() or 0
    return activos == 0


@router.put("/{user_id}", response_model=UserOut)
async def actualizar(
    user_id: int,
    payload: UserUpdate,
    session: AsyncSession = Depends(get_session),
    quien: User = Depends(usuario_actual),
):
    usuario = await traer_propio(session, User, user_id)
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    cambios = payload.model_dump(exclude_unset=True)
    rol_final = cambios.get("role", usuario.role)
    ext_final = cambios.get("extension_id", usuario.extension_id)

    # Dejar el sistema sin ningún administrador activo lo vuelve
    # inadministrable: nadie podría volver a crear usuarios ni tocar
    # ajustes, y habría que arreglarlo a mano en la base de datos.
    quita_admin = usuario.role == permissions.ADMIN and (
        rol_final != permissions.ADMIN or cambios.get("enabled") is False
    )
    if quita_admin and await _ultimo_admin(session, user_id):
        raise HTTPException(
            status_code=400,
            detail="Es el único administrador activo. Asigna otro antes de cambiar este.",
        )

    await _validar_extension(session, rol_final, ext_final)
    await _extension_libre(session, ext_final, excepto=user_id)

    cerrar_sesiones = False
    if "password" in cambios:
        usuario.password_hash = await asyncio.to_thread(hash_password, cambios.pop("password"))
        cerrar_sesiones = True  # restablecer la clave corta todas sus sesiones
    if cambios.get("enabled") is False and usuario.enabled:
        cerrar_sesiones = True
    for campo, valor in cambios.items():
        setattr(usuario, campo, valor)
    if cerrar_sesiones:
        await revocar_sesiones(session, usuario)

    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise HTTPException(status_code=400, detail="No se pudo guardar el usuario")
    await session.refresh(usuario)
    logger.info("Usuario %s actualizado por %s", usuario.username, quien.username)
    return usuario_out(usuario)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def eliminar(
    user_id: int,
    session: AsyncSession = Depends(get_session),
    quien: User = Depends(usuario_actual),
):
    usuario = await traer_propio(session, User, user_id)
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if usuario.id == quien.id:
        raise HTTPException(status_code=400, detail="No puedes eliminar tu propia cuenta")
    if usuario.role == permissions.ADMIN and await _ultimo_admin(session, user_id):
        raise HTTPException(status_code=400, detail="Es el único administrador activo")

    await session.delete(usuario)
    await session.commit()
    logger.info("Usuario %s eliminado por %s", usuario.username, quien.username)


@router.post("/{user_id}/cerrar-sesiones", status_code=status.HTTP_204_NO_CONTENT)
async def cerrar_sesiones_de(
    user_id: int,
    session: AsyncSession = Depends(get_session),
    quien: User = Depends(usuario_actual),
):
    """Saca a un usuario de todos sus equipos (app y panel) sin cambiarle la
    contraseña: un celular de la empresa que se perdió, alguien que se va."""
    usuario = await traer_propio(session, User, user_id)
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    await revocar_sesiones(session, usuario)
    await session.commit()
    logger.warning("Sesiones de %s cerradas por %s", usuario.username, quien.username)


@router.post("/{user_id}/mfa/reset", response_model=UserOut)
async def restablecer_mfa(
    user_id: int,
    session: AsyncSession = Depends(get_session),
    quien: User = Depends(usuario_actual),
):
    """Para quien perdió el teléfono y los códigos de recuperación: borra
    su verificación en dos pasos y cierra sus sesiones. Si su rol la exige,
    la vuelve a configurar al entrar. No sirve sobre la propia cuenta: así
    una sesión robada no puede quitarse el segundo paso."""
    usuario = await traer_propio(session, User, user_id)
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if usuario.id == quien.id:
        raise HTTPException(status_code=400, detail="No puedes restablecer tu propia verificación en dos pasos")
    usuario.mfa_enabled = False
    usuario.mfa_secret = None
    usuario.mfa_recovery = None
    usuario.mfa_last_step = None
    await revocar_sesiones(session, usuario)
    await session.commit()
    await session.refresh(usuario)
    logger.warning("Verificación en dos pasos de %s restablecida por %s", usuario.username, quien.username)
    return usuario_out(usuario)
