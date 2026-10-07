"""Festivos y fechas especiales de cada empresa.

- **Festivos de Colombia** (services/horario_marcacion.festivos, Ley 51 de
  1983): con «cerrar en festivos» en Ajustes, cuentan como cerrado en lo que
  tiene horario de atención: rutas entrantes, el bloque Horario del IVR y el
  widget de llamada web. Las campañas ya no marcan en festivos desde antes.
- **Fechas especiales** (tabla fechas_especiales): un día cerrado («Cierre
  por inventario») o con otra franja («24 de diciembre, 08:00-12:00»). Valen
  siempre, también para las campañas.

Lo que no tiene horario (24/7) no se cierra por un festivo: si una ruta no
pide horario, la empresa atiende siempre.

El dialplan se arma en cada llamada y el marcador corre seguido, así que los
datos viven en memoria (`_CACHE`) y se refrescan cada VIGENCIA_S desde la
base (`refrescar`), sin una consulta por llamada.
"""

import time as reloj
from dataclasses import dataclass, field
from datetime import date, datetime, time

from sqlalchemy import select

from app.services.horario_marcacion import festivos as festivos_nacionales, leer_franja

VIGENCIA_S = 60


@dataclass
class _Empresa:
    cerrar_festivos: bool = False
    especiales: dict[date, tuple[str, tuple[time, time] | None]] = field(default_factory=dict)


_CACHE: dict[int, _Empresa] = {}
_cargado_at = 0.0


async def refrescar(forzar: bool = False) -> None:
    """Relee de la base (sesión del dueño: todas las empresas)."""
    global _cargado_at
    if not forzar and reloj.monotonic() - _cargado_at < VIGENCIA_S:
        return
    from app.core.database import async_session
    from app.models import FechaEspecial, SystemSettings

    nuevo: dict[int, _Empresa] = {}
    async with async_session() as s:
        for tid, cerrar in (await s.execute(select(SystemSettings.tenant_id, SystemSettings.festivos_cerrado))).all():
            if tid is not None:
                nuevo.setdefault(tid, _Empresa()).cerrar_festivos = bool(cerrar)
        hoy = date.today()
        filas = (
            await s.execute(select(FechaEspecial).where(FechaEspecial.fecha >= date(hoy.year - 1, 1, 1)))
        ).scalars().all()
    for f in filas:
        try:
            franja = leer_franja(f.franja)
        except ValueError:
            franja = None
        nuevo.setdefault(f.tenant_id, _Empresa()).especiales[f.fecha] = (f.nombre, franja)
    _CACHE.clear()
    _CACHE.update(nuevo)
    _cargado_at = reloj.monotonic()


def invalidar() -> None:
    global _cargado_at
    _cargado_at = 0.0


def especial(tenant_id: int | None, d: date) -> tuple[str, tuple[time, time] | None] | None:
    """(nombre, franja o None si cierra todo el día) de una fecha especial."""
    e = _CACHE.get(tenant_id or 0)
    return e.especiales.get(d) if e else None


def motivo_cierre(tenant_id: int | None, momento: datetime) -> str | None:
    """Por qué está cerrado ahora por calendario (un festivo o una fecha
    especial), o None si el calendario no cierra (manda el horario normal).
    Una fecha especial con franja abre solo en esa franja."""
    e = _CACHE.get(tenant_id or 0)
    if e is None:
        return None
    d = momento.date()
    if d in e.especiales:
        nombre, franja = e.especiales[d]
        if franja is None or not (franja[0] <= momento.time() < franja[1]):
            return nombre
        return None
    if e.cerrar_festivos and d in festivos_nacionales(d.year):
        return "Festivo"
    return None


def abierto(horario: str | None, tenant_id: int | None, momento: datetime | None = None) -> bool:
    """El horario de atención de siempre (webcall.is_open), más el calendario:
    un festivo (si la empresa cierra en festivos) o una fecha especial. Sin
    horario configurado es 24/7 y el calendario no lo cierra."""
    from app.core.clock import now_local
    from app.services import webcall

    momento = momento or now_local()
    if not horario or not webcall.parse_schedule(horario):
        return True
    d = momento.date()
    e = _CACHE.get(tenant_id or 0)
    if e is not None and d in e.especiales:
        _, franja = e.especiales[d]
        return franja is not None and franja[0] <= momento.time() < franja[1]
    if motivo_cierre(tenant_id, momento):
        return False
    return webcall.is_open(horario, momento)


def proximos_nacionales(desde: date, cuantos: int = 8) -> list[date]:
    fechas = sorted(f for anio in (desde.year, desde.year + 1) for f in festivos_nacionales(anio) if f >= desde)
    return fechas[:cuantos]
