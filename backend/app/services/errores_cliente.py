"""Errores del panel (navegador) y de la app móvil, en un solo lugar.

Antes, un error en el navegador de un agente o en su teléfono solo se veía
en la consola de ese equipo: nadie se enteraba. Ahora el panel y la app lo
mandan a POST /api/errores, se agrupa por firma (origen + mensaje + primera
línea de la pila, sin números) y Plataforma ve cuántas veces pasa, a
cuántos usuarios y desde cuándo.

Lo que llega se recorta y se le quitan tokens y números largos (pueden ser
teléfonos o documentos): sirve para arreglar el código, no para guardar
datos de clientes.
"""

import hashlib
import re
from datetime import datetime

from sqlalchemy import select

from app.core.database import async_session
from app.models import ErrorCliente

ORIGENES = ("panel", "app")
_JWT = re.compile(r"eyJ[\w-]+\.[\w-]+\.[\w-]+")
_BEARER = re.compile(r"(?i)bearer\s+\S+")
_PARAM = re.compile(r"(?i)\b(token|secret|password|clave|key|code)=[^&\s\"']+")
_DIGITOS = re.compile(r"\d{7,}")
_NUMEROS = re.compile(r"\d+")


def limpiar(texto: str | None, maximo: int) -> str:
    t = str(texto or "")
    t = _JWT.sub("[token]", t)
    t = _BEARER.sub("Bearer [token]", t)
    t = _PARAM.sub(lambda m: f"{m.group(1)}=[oculto]", t)
    t = _DIGITOS.sub("[número]", t)
    return t[:maximo]


def firma(origen: str, mensaje: str, pila: str | None) -> str:
    """Igual para el mismo fallo aunque cambien ids, líneas o números."""
    primera = next((r.strip() for r in (pila or "").splitlines() if r.strip() and r.strip() != mensaje.strip()), "")
    base = f"{origen}|{_NUMEROS.sub('#', mensaje)}|{_NUMEROS.sub('#', primera)}"
    return hashlib.sha256(base.encode()).hexdigest()


async def registrar(origen: str, mensaje: str, pila: str | None, ruta: str | None, version: str | None,
                    tenant_id: int | None, usuario: str | None) -> ErrorCliente:
    mensaje = limpiar(mensaje, 300) or "(sin mensaje)"
    pila = limpiar(pila, 4000) or None
    ruta = limpiar((ruta or "").split("?")[0], 200) or None
    clave = firma(origen, mensaje, pila)
    ahora = datetime.utcnow()
    async with async_session() as session:
        fila = (await session.execute(select(ErrorCliente).where(ErrorCliente.firma == clave).with_for_update())).scalar_one_or_none()
        if fila is None:
            fila = ErrorCliente(firma=clave, origen=origen, mensaje=mensaje, pila=pila, ruta=ruta, version=(version or "")[:60] or None,
                                empresa_id=tenant_id, usuario=usuario, veces=1, usuarios=1, primera_vez=ahora, ultima_vez=ahora)
            session.add(fila)
        else:
            fila.veces += 1
            if usuario and usuario != fila.usuario:
                fila.usuarios += 1
                fila.usuario = usuario
            fila.ultima_vez = ahora
            fila.ruta = ruta or fila.ruta
            fila.version = (version or "")[:60] or fila.version
            # Volvió a pasar: ya no está resuelto.
            fila.resuelto = False
        await session.commit()
        await session.refresh(fila)
        return fila
