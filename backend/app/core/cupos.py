"""Topes de uso compartidos entre réplicas (tabla `cupos_uso`).

Para lo que cuesta plata por pregunta (el asistente, el simulador de bots):
con el tope en memoria de cada proceso, dos réplicas dejaban pasar el doble.
Ventana fija: se cuenta por clave en la ventana actual (epoch // duración)
con un solo UPSERT atómico, sin carreras entre réplicas.

Los intentos fallidos de inicio de sesión siguen en memoria
(core/limitador.py): ahí el tope por réplica sigue frenando a quien prueba
claves, y no se le agrega una escritura en la base a cada intento.
"""

import time

from fastapi import HTTPException, status
from sqlalchemy import text

from app.core.database import async_session

_SQL = text(
    "INSERT INTO cupos_uso (clave, ventana, conteo) VALUES (:clave, :ventana, 1) "
    "ON CONFLICT (clave) DO UPDATE SET "
    "conteo = CASE WHEN cupos_uso.ventana = EXCLUDED.ventana THEN cupos_uso.conteo + 1 ELSE 1 END, "
    "ventana = EXCLUDED.ventana "
    "RETURNING conteo"
)


async def consumir(clave: str, maximo: int, ventana_seg: int = 60, ahora: float | None = None) -> int:
    """Cuenta un uso. 0 si entra en el tope; si no, los segundos que faltan
    para la próxima ventana."""
    ahora = time.time() if ahora is None else ahora
    ventana = int(ahora // ventana_seg)
    async with async_session() as session:
        conteo = (await session.execute(_SQL, {"clave": clave[:120], "ventana": ventana})).scalar_one()
        await session.commit()
    if conteo <= maximo:
        return 0
    return max(1, int((ventana + 1) * ventana_seg - ahora) + 1)


async def exigir(clave: str, maximo: int, ventana_seg: int = 60, mensaje: str = "Demasiadas solicitudes seguidas; espera un momento") -> None:
    espera = await consumir(clave, maximo, ventana_seg)
    if espera:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, mensaje, headers={"Retry-After": str(espera)})


async def purgar() -> None:
    """Las claves de ventanas de hace más de una hora. Supone ventanas de un
    minuto (las de hoy); una más larga solo se reiniciaría antes de tiempo."""
    async with async_session() as session:
        await session.execute(
            text("DELETE FROM cupos_uso WHERE ventana < :limite"), {"limite": int((time.time() - 3600) // 60)}
        )
        await session.commit()
