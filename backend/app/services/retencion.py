"""Retención de lo que se habló, además del audio (workers/maintenance.py).

La retención de grabaciones de Ajustes borraba el audio pero dejaba para
siempre lo que se dijo: la transcripción y el resumen de la llamada y la
transcripción del mensaje de voz. Ahora corren con la misma cantidad de
días. Las llamadas marcadas «Conservar» quedan fuera de las dos limpiezas.

También calcula lo que se va a borrar pronto, para avisarlo en Ajustes.
"""

from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import or_, select, update

from app.core.config import settings
from app.models import CallLog, MensajeBuzon

AVISO_DIAS = 7


async def rutas_conservadas(session) -> set[Path]:
    """Los archivos locales de las grabaciones marcadas «Conservar»."""
    from app.api.calls import _local_recording_path

    filas = (await session.execute(select(CallLog.recording_path).where(CallLog.conservar.is_(True), CallLog.recording_path.is_not(None)))).scalars()
    return {_local_recording_path(r) for r in filas}


async def purgar_transcripciones(session, por_empresa: dict[int, int], ahora: datetime | None = None) -> int:
    ahora = ahora or datetime.utcnow()
    total = 0
    for tenant_id, dias in por_empresa.items():
        corte = ahora - timedelta(days=max(1, int(dias)))
        r = await session.execute(
            update(CallLog)
            .where(CallLog.tenant_id == tenant_id, CallLog.started_at < corte, CallLog.conservar.is_(False),
                   or_(CallLog.transcripcion.is_not(None), CallLog.summary.is_not(None)))
            .values(transcripcion=None, summary=None)
        )
        m = await session.execute(
            update(MensajeBuzon)
            .where(MensajeBuzon.tenant_id == tenant_id, MensajeBuzon.created_at < corte, MensajeBuzon.transcripcion.is_not(None))
            .values(transcripcion=None)
        )
        total += (r.rowcount or 0) + (m.rowcount or 0)
    await session.commit()
    return total


def proximas(tenant_id: int, dias: int, conservadas: set[Path], ahora: datetime | None = None) -> dict:
    """Grabaciones de la empresa que la retención borrará en los próximos AVISO_DIAS días."""
    ahora = ahora or datetime.utcnow()
    carpeta = Path(settings.recordings_dir) / f"t{int(tenant_id)}"
    desde = ahora - timedelta(days=max(1, int(dias)))
    hasta = desde + timedelta(days=AVISO_DIAS)
    archivos, bytes_ = 0, 0
    if carpeta.is_dir():
        for f in carpeta.glob("**/*.wav"):
            try:
                st = f.stat()
            except OSError:
                continue
            if f.name == "saludo.wav" or f.resolve() in conservadas:
                continue
            if desde <= datetime.utcfromtimestamp(st.st_mtime) < hasta:
                archivos += 1
                bytes_ += st.st_size
    return {"dias": dias, "aviso_dias": AVISO_DIAS, "archivos": archivos, "mb": round(bytes_ / 1024 / 1024, 1)}
