"""La licencia en una instalación LOCAL (MODO_INSTALACION=local, docs/plan-fase-k.md).

El servidor del cliente corre una sola empresa (la 1). Su nombre, tipo,
módulos, plan, estado y topes no se editan acá: llegan firmados desde la
central y se aplican tal cual.

- Al arrancar: si todavía no hay licencia guardada, se importa la que dejó
  el instalador (`/run/secrets/licencia.json`). Sin ninguna, la empresa
  queda suspendida: una instalación sin activar no opera.
- Cada hora (el líder): latido a la central con el resumen de uso. Si
  responde, se guarda y aplica la licencia nueva. Si no, se vuelve a aplicar
  la guardada (deshace cualquier cambio hecho a mano en la base) y se anota
  el error.
- El vencimiento que se aplica es el MENOR entre el comercial y
  `valida_hasta`: sin latidos durante la gracia, la licencia vence sola.
"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

import httpx
from sqlalchemy import func, select

from app.core.clock import now_local
from app.core.config import settings
from app.core.database import async_session
from app.models import CallLog, Campaign, Extension, License, LicenciaLocal, Tenant, Trunk, User
from app.services import licencia_firmada as lf

logger = logging.getLogger(__name__)

EMPRESA_LOCAL = 1
ARCHIVO_INSTALADOR = Path("/run/secrets/licencia.json")
CADA_S = 3600
VERSION = "1.0.0"
_ESTADOS = {"active", "trial", "suspended"}


def es_local() -> bool:
    return settings.modo_instalacion == "local"


async def _fila(session) -> LicenciaLocal | None:
    return await session.get(LicenciaLocal, 1)


async def aplicar(session, documento: str, firma: str, token: str | None = None) -> dict:
    """Verifica, guarda y aplica una licencia. Devuelve el documento.

    Una licencia más vieja que la guardada no se acepta: reponer una
    respuesta antigua (de antes de una suspensión) no sirve para nada."""
    texto = documento
    doc = lf.verificar(texto, firma, settings.licencia_clave_publica)
    fila = await _fila(session)
    if fila is not None:
        anterior = json.loads(fila.documento)
        if doc["instalacion_id"] != anterior["instalacion_id"] and token is None:
            raise lf.LicenciaInvalida("La licencia es de otra instalación")
        if doc["emitida"] < anterior["emitida"]:
            raise lf.LicenciaInvalida("La licencia es más vieja que la guardada")
    if fila is None:
        if token is None:
            raise lf.LicenciaInvalida("No hay token de esta instalación: actívala con el instalador")
        fila = LicenciaLocal(id=1, instalacion_id=doc["instalacion_id"], token=token, documento=texto, firma=firma)
        session.add(fila)
    else:
        fila.instalacion_id = doc["instalacion_id"]
        fila.documento, fila.firma = texto, firma
        if token:
            fila.token = token
    fila.recibida_at = datetime.utcnow()
    fila.ultimo_error = None
    await _aplicar_a_la_empresa(session, doc)
    await session.commit()
    return doc


async def _aplicar_a_la_empresa(session, doc: dict) -> None:
    empresa = await session.get(Tenant, EMPRESA_LOCAL)
    datos = doc["empresa"]
    empresa.name = str(datos.get("nombre") or empresa.name)[:150]
    empresa.business_type = datos.get("business_type") or empresa.business_type
    empresa.modules = ",".join(m for m in datos.get("modules") or [] if isinstance(m, str))
    licencia = doc["licencia"]
    lic = (await session.execute(select(License).where(License.tenant_id == EMPRESA_LOCAL))).scalar_one_or_none()
    if lic is None:
        lic = License(tenant_id=EMPRESA_LOCAL, started_at=now_local())
        session.add(lic)
    lic.plan = str(licencia.get("plan") or "custom")[:30]
    lic.status = licencia.get("status") if licencia.get("status") in _ESTADOS else "suspended"
    vencimientos = [v for v in (lf.de_utc_iso(licencia.get("expires_at")), lf.de_utc_iso(doc["valida_hasta"])) if v]
    lic.expires_at = min(vencimientos)
    for recurso in lf.RECURSOS:
        setattr(lic, recurso, licencia.get(recurso))


async def suspender_sin_licencia(session) -> None:
    """Sin licencia válida guardada, la empresa no opera (ni con la prueba
    de 15 días que se crea por omisión en la nube)."""
    lic = (await session.execute(select(License).where(License.tenant_id == EMPRESA_LOCAL))).scalar_one_or_none()
    if lic is None:
        lic = License(tenant_id=EMPRESA_LOCAL, plan="custom", started_at=now_local())
        session.add(lic)
    lic.status = "suspended"
    await session.commit()


async def al_arrancar() -> None:
    """Importa la licencia del instalador o reaplica la guardada."""
    if not es_local():
        return
    async with async_session() as session:
        if settings.dominio_local:
            empresa = await session.get(Tenant, EMPRESA_LOCAL)
            if empresa.sip_domain != settings.dominio_local:
                empresa.sip_domain = settings.dominio_local
                await session.commit()
        fila = await _fila(session)
        if fila is None and ARCHIVO_INSTALADOR.exists():
            try:
                datos = json.loads(ARCHIVO_INSTALADOR.read_text())
                await aplicar(session, datos["documento"], datos["firma"], token=datos["token"])
                logger.warning("Licencia del instalador importada (instalación %s)", datos.get("instalacion_id"))
                return
            except Exception as exc:
                logger.error("No se pudo importar la licencia del instalador: %s", exc)
        await reaplicar(session)


async def reaplicar(session) -> bool:
    """Vuelve a verificar y aplicar la licencia guardada. False si no hay una válida."""
    fila = await _fila(session)
    if fila is None:
        await suspender_sin_licencia(session)
        return False
    try:
        doc = lf.verificar(fila.documento, fila.firma, settings.licencia_clave_publica)
    except lf.LicenciaInvalida as exc:
        logger.error("La licencia guardada no es válida: %s", exc)
        await suspender_sin_licencia(session)
        return False
    await _aplicar_a_la_empresa(session, doc)
    await session.commit()
    return True


async def uso(session) -> dict[str, int]:
    """Solo cantidades: nada de números, nombres ni grabaciones."""
    inicio_mes = now_local().replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    async def contar(modelo) -> int:
        return (await session.execute(select(func.count(modelo.id)))).scalar() or 0

    salientes = (
        await session.execute(
            select(func.count(CallLog.id), func.coalesce(func.sum(CallLog.billsec), 0)).where(
                CallLog.started_at >= inicio_mes, CallLog.direction == "outbound", CallLog.via_trunk.is_(True)
            )
        )
    ).one()
    entrantes = (
        await session.execute(
            select(func.count(CallLog.id)).where(CallLog.started_at >= inicio_mes, CallLog.direction == "inbound")
        )
    ).scalar() or 0
    return {
        "extensiones": await contar(Extension),
        "usuarios": await contar(User),
        "troncales": await contar(Trunk),
        "campanas": await contar(Campaign),
        "llamadas_salientes_mes": int(salientes[0] or 0),
        "minutos_salientes_mes": int((salientes[1] or 0) // 60),
        "llamadas_entrantes_mes": int(entrantes),
    }


async def latir(cliente: httpx.AsyncClient | None = None) -> bool:
    """Un latido. True si la central respondió con una licencia válida."""
    async with async_session() as session:
        fila = await _fila(session)
        if fila is None:
            await suspender_sin_licencia(session)
            return False
        fila.ultimo_intento_at = datetime.utcnow()
        cuerpo = {"version": VERSION, "uso": await uso(session)}
        token = fila.token
        await session.commit()
    error = None
    try:
        propio = cliente is None
        cliente = cliente or httpx.AsyncClient(timeout=20)
        try:
            r = await cliente.post(f"{settings.central_url.rstrip('/')}/api/licencia/latido", json=cuerpo,
                                   headers={"Authorization": f"Bearer {token}"})
        finally:
            if propio:
                await cliente.aclose()
        if r.status_code == 200:
            datos = r.json()
            async with async_session() as session:
                await aplicar(session, datos["documento"], datos["firma"])
            return True
        error = f"La central respondió {r.status_code}"
        if r.status_code == 401:
            error = "La central no reconoce esta instalación (¿se reinstaló con otro código?)"
    except lf.LicenciaInvalida as exc:
        error = str(exc)
    except Exception as exc:
        error = f"Sin conexión con la central: {exc.__class__.__name__}"
    logger.warning("Latido a la central: %s", error)
    async with async_session() as session:
        fila = await _fila(session)
        fila.ultimo_error = error[:300]
        await session.commit()
        await reaplicar(session)
    return False


async def estado(session) -> dict:
    """Lo que muestra el panel de la instalación local."""
    fila = await _fila(session)
    if fila is None:
        return {"modo": "local", "activada": False}
    try:
        doc = lf.verificar(fila.documento, fila.firma, settings.licencia_clave_publica)
    except lf.LicenciaInvalida as exc:
        return {"modo": "local", "activada": True, "valida": False, "error": str(exc)}
    sin_contacto_h = (datetime.utcnow() - fila.recibida_at).total_seconds() / 3600
    return {
        "modo": "local",
        "activada": True,
        "valida": True,
        "instalacion_id": fila.instalacion_id,
        "empresa": doc["empresa"]["nombre"],
        "plan": doc["licencia"]["plan"],
        "estado": doc["licencia"]["status"],
        "vence": lf.de_utc_iso(doc["licencia"].get("expires_at")),
        "valida_hasta": lf.de_utc_iso(doc["valida_hasta"]),
        "ultimo_contacto": fila.recibida_at,
        "ultimo_intento": fila.ultimo_intento_at,
        "ultimo_error": fila.ultimo_error,
        "horas_sin_contacto": round(sin_contacto_h, 1),
    }


class Latido:
    """El latido de cada hora (solo en el líder, solo en modo local)."""

    def __init__(self):
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if es_local() and self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        await asyncio.sleep(30)
        while True:
            try:
                await latir()
            except Exception:
                logger.exception("Error en el latido de la licencia")
            await asyncio.sleep(CADA_S)


latido = Latido()
