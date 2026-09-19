"""Revocación de sesiones de un usuario.

Una sesión son dos cosas: el JWT corto (8 h) y los refresh tokens largos (30 d,
en la app móvil). Los refresh tokens se revocan marcando su fila. El JWT no se
puede "borrar", así que se invalida por fecha: `User.sesiones_desde` — todo JWT
emitido antes de ese instante deja de servir (ver core/auth.sesion_obligatoria).
"""
from datetime import datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RefreshToken, User


async def revocar_sesiones(session: AsyncSession, usuario: User) -> None:
    """Cierra TODAS las sesiones del usuario (no hace commit: lo hace quien llama).

    Se usa al cambiar o restablecer la contraseña, al desactivar la cuenta y
    cuando se detecta que un refresh token ya usado se presentó otra vez.
    """
    ahora = datetime.utcnow()
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == usuario.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=ahora)
    )
    usuario.sesiones_desde = ahora
