"""Estado de las defensas del servidor: qué está bloqueando fail2ban.

Solo lectura, a propósito — ver el docstring de services/fail2ban.py.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import validacion
from app.core.database import get_session
from app.models import Extension
from app.services import fail2ban

router = APIRouter(prefix="/api/security", tags=["security"])


def _salida(b: fail2ban.Bloqueo) -> dict:
    return {
        "jail": b.jail,
        "ip": b.ip,
        "desde": b.desde,
        "hasta": b.hasta,
        "segundos": b.segundos,
        "veces": b.veces,
        "vigente": b.vigente,
    }


@router.get("/bans")
async def bans(limite: int = Query(default=100, ge=1, le=500)):
    """Bloqueos vigentes e histórico reciente.

    `disponible` en false significa que no se pudo leer la base de
    fail2ban: o no está instalado, o falta montarla en el contenedor. Se
    devuelve como dato y no como error para que la pantalla pueda decir
    qué hacer en vez de mostrar una lista vacía, que se confunde con
    "no hay ataques".
    """
    return {
        "disponible": fail2ban.disponible(),
        "vigentes": [_salida(b) for b in fail2ban.bloqueos()],
        "historico": [_salida(b) for b in fail2ban.historico(limite)],
    }


@router.get("/claves-debiles")
async def claves_debiles(session: AsyncSession = Depends(get_session)):
    """Extensiones de la empresa con una contraseña SIP que no pasaría la
    validación actual. Las anteriores a la validación no se cambian solas
    (desregistraría teléfonos sin aviso): esta lista dice cuáles cambiar."""
    exts = (await session.execute(select(Extension).order_by(Extension.number))).scalars().all()
    return [
        {"id": e.id, "number": e.number, "motivo": motivo}
        for e in exts
        if (motivo := validacion.problema_clave_sip(e.password, e.number))
    ]
