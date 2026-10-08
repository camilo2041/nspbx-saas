"""Estado de los respaldos de la plataforma, para el panel y las métricas.

Los respaldos tienen tres capas y solo la primera corre dentro del backend:

1. El volcado diario de Postgres (workers/maintenance.py) en /backups.
2. La copia externa CIFRADA (scripts/backup-offsite.sh, cron del servidor):
   el volcado + grabaciones + audios de los bots, cifrado y subido con rclone
   o rsync. Deja el paquete en /backups/offsite.
3. El simulacro de restauración (scripts/simulacro-restauracion.sh, cron
   mensual): restaura en un Postgres descartable, nunca en el de producción,
   y anota una línea en /backups/simulacros.log.

El backend no repite 2 ni 3 (lo harían peor: sin cifrar, o sobre la base de
producción); solo lee lo que dejan y avisa si se atrasan.
"""

import re
from datetime import datetime
from pathlib import Path

from app.core.config import settings

OFFSITE_MAX_HORAS = 48
SIMULACRO_MAX_DIAS = 35
_LINEA = re.compile(r"^(\S+)\s+(OK|FALLO)\s+(.*)$")


def _carpeta() -> Path:
    return Path(settings.backups_dir)


def ultimo_volcado() -> Path | None:
    archivos = sorted(_carpeta().glob("nspbx-*.sql.gz")) if _carpeta().is_dir() else []
    return archivos[-1] if archivos else None


def copia_externa(ahora: datetime | None = None) -> dict:
    """El último paquete cifrado que dejó backup-offsite.sh."""
    ahora = ahora or datetime.now()
    carpeta = _carpeta() / "offsite"
    paquetes = sorted(carpeta.glob("nspbx-*.tar.gz.enc"), key=lambda a: a.stat().st_mtime) if carpeta.is_dir() else []
    if not paquetes:
        return {"hay": False, "archivo": None, "at": None, "horas": None, "al_dia": False}
    ultimo = paquetes[-1]
    at = datetime.fromtimestamp(ultimo.stat().st_mtime)
    horas = round((ahora - at).total_seconds() / 3600, 1)
    return {"hay": True, "archivo": ultimo.name, "at": at.isoformat(timespec="minutes"), "horas": horas,
            "al_dia": horas <= OFFSITE_MAX_HORAS}


def simulacro(ahora: datetime | None = None) -> dict:
    """La última línea de simulacros.log: «<fecha ISO> OK|FALLO detalle»."""
    registro = _carpeta() / "simulacros.log"
    vacio = {"hay": False, "ok": None, "at": None, "dias": None, "detalle": None, "al_dia": False}
    try:
        lineas = [r for r in registro.read_text(errors="replace").splitlines() if r.strip()]
    except OSError:
        return vacio
    if not lineas:
        return vacio
    m = _LINEA.match(lineas[-1].strip())
    if not m:
        return {**vacio, "hay": True, "detalle": lineas[-1][:200]}
    try:
        at = datetime.fromisoformat(m.group(1))
    except ValueError:
        return {**vacio, "hay": True, "detalle": lineas[-1][:200]}
    ahora = ahora or datetime.now(at.tzinfo)
    dias = (ahora - at).days
    ok = m.group(2) == "OK"
    return {"hay": True, "ok": ok, "at": at.isoformat(timespec="minutes"), "dias": dias,
            "detalle": m.group(3)[:200], "al_dia": ok and dias <= SIMULACRO_MAX_DIAS}
