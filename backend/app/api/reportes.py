"""Reportes del contact center (services/reportes.py), con `reportes:ver`.

Mismo filtro en todos: `desde` y `hasta` son días locales (incluidos), y
`formato=csv` devuelve el archivo para Excel en vez del JSON. Ver o bajar un
reporte queda en la auditoría (core/auditoria.py): el de cumplimiento lleva
teléfonos de terceros.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import usuario_actual
from app.core.database import get_session, tenant_de_sesion, traer_propio
from app.models import ReporteProgramado, User
from app.services import reportes, reportes_programados

router = APIRouter(prefix="/api/reportes", tags=["reportes"])


def _rango(desde: date, hasta: date) -> reportes.Rango:
    try:
        return reportes.rango_utc(desde, hasta)
    except reportes.RangoInvalido as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _responder(tipo: str, datos: dict, formato: str, r: reportes.Rango, seccion: str | None = None):
    if formato != "csv":
        return {**datos, "desde": r.desde.isoformat(), "hasta": r.hasta.isoformat()}
    try:
        texto = reportes.csv_de(tipo, datos, seccion)
    except reportes.RangoInvalido as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    nombre = f"{tipo}{'-' + seccion if seccion else ''}_{r.desde.isoformat()}_{r.hasta.isoformat()}.csv"
    return Response(texto, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


_FORMATO = Query(default="json", pattern="^(json|csv)$")


@router.get("/agentes")
async def agentes(
    desde: date,
    hasta: date,
    campaign_id: int | None = None,
    user_id: int | None = None,
    formato: str = _FORMATO,
    session: AsyncSession = Depends(get_session),
):
    r = _rango(desde, hasta)
    return _responder("agentes", await reportes.agentes(session, r, campaign_id, user_id), formato, r)


@router.get("/campanas")
async def campanas(
    desde: date, hasta: date, campaign_id: int | None = None, formato: str = _FORMATO, session: AsyncSession = Depends(get_session)
):
    r = _rango(desde, hasta)
    return _responder("campanas", await reportes.campanas(session, r, campaign_id), formato, r)


@router.get("/disposiciones")
async def disposiciones(
    desde: date,
    hasta: date,
    agrupar: str = Query(default="campana", pattern="^(campana|agente|lista)$"),
    campaign_id: int | None = None,
    formato: str = _FORMATO,
    session: AsyncSession = Depends(get_session),
):
    r = _rango(desde, hasta)
    return _responder("disposiciones", await reportes.disposiciones(session, r, agrupar, campaign_id), formato, r)


@router.get("/cumplimiento")
async def cumplimiento(
    desde: date,
    hasta: date,
    max_contactos_semana: int = Query(default=1, ge=1, le=20),
    solo_cobranza: bool = True,
    seccion: str = Query(default="abandono", pattern="^(abandono|contactos_semana|fuera_de_horario)$"),
    formato: str = _FORMATO,
    session: AsyncSession = Depends(get_session),
):
    r = _rango(desde, hasta)
    datos = await reportes.cumplimiento(session, r, max_contactos_semana, solo_cobranza)
    return _responder("cumplimiento", datos, formato, r, seccion if formato == "csv" else None)


# --- Programados por correo -------------------------------------------------------------------------

MAX_PROGRAMADOS = 20


class Filtros(BaseModel):
    campaign_id: int | None = None
    agrupar: str | None = Field(default=None, pattern="^(campana|agente|lista)$")
    max_contactos_semana: int | None = Field(default=None, ge=1, le=20)
    solo_cobranza: bool | None = None


def _destinatarios(v: str | None) -> str | None:
    if v is None:
        return v
    return ", ".join(reportes_programados.leer_destinatarios(v))


class ProgramadoIn(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=80)
    tipo: str = Field(..., pattern="^(agentes|campanas|disposiciones|cumplimiento)$")
    frecuencia: str = Field(..., pattern="^(diaria|semanal|mensual)$")
    hora: int = Field(default=7, ge=0, le=23)
    destinatarios: str = Field(..., max_length=2000)
    filtros: Filtros = Field(default_factory=Filtros)
    activo: bool = True

    @field_validator("destinatarios")
    @classmethod
    def _v_dest(cls, v):
        return _destinatarios(v)


class ProgramadoUpdate(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=80)
    tipo: str | None = Field(default=None, pattern="^(agentes|campanas|disposiciones|cumplimiento)$")
    frecuencia: str | None = Field(default=None, pattern="^(diaria|semanal|mensual)$")
    hora: int | None = Field(default=None, ge=0, le=23)
    destinatarios: str | None = Field(default=None, max_length=2000)
    filtros: Filtros | None = None
    activo: bool | None = None

    @field_validator("destinatarios")
    @classmethod
    def _v_dest(cls, v):
        return _destinatarios(v)


def _prog_out(r: ReporteProgramado) -> dict:
    return {
        "id": r.id, "nombre": r.nombre, "tipo": r.tipo, "frecuencia": r.frecuencia, "hora": r.hora,
        "destinatarios": r.destinatarios, "filtros": r.filtros or {}, "activo": r.activo,
        "ultimo_envio_at": r.ultimo_envio_at, "ultimo_periodo": r.ultimo_periodo, "ultimo_error": r.ultimo_error,
    }


async def _programado(session: AsyncSession, programado_id: int) -> ReporteProgramado:
    r = await traer_propio(session, ReporteProgramado, programado_id)
    if r is None:
        raise HTTPException(status_code=404, detail="Reporte programado no encontrado")
    return r


@router.get("/programados")
async def listar_programados(session: AsyncSession = Depends(get_session)):
    filas = (await session.execute(select(ReporteProgramado).order_by(ReporteProgramado.id))).scalars().all()
    return {"correo_configurado": reportes_programados.correo_configurado(), "programados": [_prog_out(r) for r in filas]}


@router.post("/programados", status_code=status.HTTP_201_CREATED)
async def crear_programado(payload: ProgramadoIn, session: AsyncSession = Depends(get_session), usuario: User = Depends(usuario_actual)):
    if len((await session.execute(select(ReporteProgramado.id))).all()) >= MAX_PROGRAMADOS:
        raise HTTPException(status_code=400, detail=f"Máximo {MAX_PROGRAMADOS} reportes programados")
    datos = payload.model_dump()
    datos["filtros"] = payload.filtros.model_dump(exclude_none=True)
    r = ReporteProgramado(tenant_id=tenant_de_sesion(session), creado_por=usuario.id, **datos)
    session.add(r)
    await session.commit()
    return _prog_out(r)


@router.put("/programados/{programado_id}")
async def editar_programado(programado_id: int, payload: ProgramadoUpdate, session: AsyncSession = Depends(get_session)):
    r = await _programado(session, programado_id)
    cambios = payload.model_dump(exclude_unset=True)
    if "filtros" in cambios:
        cambios["filtros"] = payload.filtros.model_dump(exclude_none=True) if payload.filtros else {}
    for clave, valor in cambios.items():
        setattr(r, clave, valor)
    if {"tipo", "frecuencia", "filtros"} & cambios.keys():
        # Otro reporte: el período que ya salió no cuenta para este.
        r.ultimo_periodo = None
    r.ultimo_error = None
    await session.commit()
    return _prog_out(r)


@router.delete("/programados/{programado_id}", status_code=status.HTTP_204_NO_CONTENT)
async def borrar_programado(programado_id: int, session: AsyncSession = Depends(get_session)):
    r = await _programado(session, programado_id)
    await session.delete(r)
    await session.commit()


@router.post("/programados/{programado_id}/enviar")
async def enviar_ya(programado_id: int, session: AsyncSession = Depends(get_session)):
    """Manda ahora el último período cerrado (para probar los destinatarios)."""
    r = await _programado(session, programado_id)
    if not reportes_programados.correo_configurado():
        raise HTTPException(status_code=409, detail="El correo saliente no está configurado en el servidor")
    tenant_id, rid = r.tenant_id, r.id
    await session.commit()
    try:
        etiqueta = await reportes_programados.enviar(tenant_id, rid, forzar=True)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"No se pudo enviar: {exc}")
    return {"ok": True, "periodo": etiqueta}
