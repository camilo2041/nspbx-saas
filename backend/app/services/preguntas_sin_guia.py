"""Preguntas de «¿cómo hago…?» que ninguna guía respondió.

El panel y la app saben si ofrecieron una guía (la búsqueda local o el
`[[guia:id]]` de la IA); si no, mandan la pregunta. Aquí se queda solo si
pide cómo hacer algo, se le quitan números largos y correos, se normaliza
(minúsculas, sin tildes ni signos) y se cuenta: la lista de Plataforma dice
qué guía escribir después (frontend/lib/guias.ts, mobile/src/guias.ts).
"""

import re
import unicodedata
from datetime import datetime

from sqlalchemy import select

from app.core.database import async_session
from app.models import PreguntaSinGuia

# Lo que delata una pregunta de «cómo se hace» (ya sin tildes, en minúscula).
_COMO = re.compile(
    r"\b(como|donde|puedo|se puede|configur|crear?|agrega|cambi|activ|desactiv|subir|cargar|quiero|necesito|que hago|pasos)",
)
_CORREO = re.compile(r"\S+@\S+")
_DIGITOS = re.compile(r"\d{5,}")
_SIGNOS = re.compile(r"[^a-z0-9 ]+")


def _sin_tildes(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")


def limpiar(texto: str) -> str:
    return _DIGITOS.sub("#", _CORREO.sub("[correo]", (texto or "").strip()))[:300]


def clave(texto: str) -> str:
    t = _sin_tildes(limpiar(texto).lower())
    return " ".join(_SIGNOS.sub(" ", t).split())[:200]


def es_como(texto: str) -> bool:
    c = clave(texto)
    return 3 <= len(c.split()) <= 40 and bool(_COMO.search(c))


async def registrar(texto: str, origen: str) -> bool:
    """True si se anotó (era un «cómo hago»)."""
    if not es_como(texto):
        return False
    k = clave(texto)
    ahora = datetime.utcnow()
    async with async_session() as session:
        fila = (await session.execute(select(PreguntaSinGuia).where(PreguntaSinGuia.clave == k).with_for_update())).scalar_one_or_none()
        if fila is None:
            session.add(PreguntaSinGuia(clave=k, ejemplo=limpiar(texto), veces=1, origen=origen, primera_vez=ahora, ultima_vez=ahora))
        else:
            fila.veces += 1
            fila.ultima_vez = ahora
            fila.origen = origen
        await session.commit()
    return True
