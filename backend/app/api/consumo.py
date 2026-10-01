"""Consumo mensual de la empresa (ver services/consumo.py)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session, tenant_de_sesion
from app.services import consumo

router = APIRouter(prefix="/api/consumo", tags=["consumo"])


def _empresa(session) -> int:
    tid = tenant_de_sesion(session)
    if tid is None:
        raise HTTPException(status_code=404, detail="Sin empresa")
    return tid


def csv_respuesta(contenido: str, nombre: str) -> Response:
    return Response(
        contenido, media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


@router.get("")
async def del_mes(mes: str | None = None, session: AsyncSession = Depends(get_session)):
    try:
        return await consumo.resumen(session, _empresa(session), mes)
    except consumo.MesInvalido as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/csv")
async def historial_csv(meses: int = Query(default=12, ge=1, le=36), session: AsyncSession = Depends(get_session)):
    tid = _empresa(session)
    filas = [await consumo.resumen(session, tid, m) for m in consumo.meses_anteriores(meses)]
    return csv_respuesta(consumo.a_csv(filas), "consumo.csv")
