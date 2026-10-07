"""Recibe los errores del panel y de la app (services/errores_cliente.py).

Con sesión: no es una ruta abierta. Cualquier rol puede mandar los suyos,
con un tope por usuario para que un bucle de errores no llene la tabla.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core import cupos
from app.core.auth import usuario_actual
from app.models import User
from app.services import errores_cliente

router = APIRouter(prefix="/api/errores", tags=["errores"])

POR_MINUTO = 20


class ErrorIn(BaseModel):
    origen: str = Field(pattern="^(panel|app)$")
    mensaje: str = Field(max_length=2000)
    pila: str | None = Field(default=None, max_length=20000)
    ruta: str | None = Field(default=None, max_length=500)
    version: str | None = Field(default=None, max_length=100)


@router.post("", status_code=204)
async def recibir(datos: ErrorIn, usuario: User = Depends(usuario_actual)):
    await cupos.exigir(f"errores:{usuario.id}", POR_MINUTO, 60, "Demasiados errores seguidos")
    await errores_cliente.registrar(datos.origen, datos.mensaje, datos.pila, datos.ruta, datos.version,
                                    usuario.tenant_id, usuario.username)
