"""Derechos del titular de los datos (Ley 1581 de 2012) y borrado de empresas.

La persona cuyos datos guarda una empresa (el paciente, el deudor, quien
llamó) puede pedir conocerlos y que se supriman. La empresa es la
responsable del tratamiento; la plataforma le da cómo cumplir:

- `datos_del_titular`: todo lo que la empresa tiene de un teléfono.
- `suprimir_titular`: lo borra. Lo que es de la persona (citas, deudas,
  promesas, números de campaña) se elimina; los registros de llamadas y de
  consumo se conservan ANONIMIZADOS, porque son la base de la facturación
  y de las métricas, y sin el número, el nombre, el resumen ni la
  grabación ya no identifican a nadie.

Las dos corren con la sesión de la empresa (RLS + filtro explícito): no
alcanzan a otra empresa aunque el mismo teléfono exista allí.

Lo que no se borra acá y por qué:
- El registro de auditoría es de solo agregar; guarda los teléfonos
  enmascarados (ver core/auditoria.py) y lo elimina la retención.
- Las copias de seguridad: vencen con su propia retención (ver
  docs/seguridad-y-robustez.md, fase 4).
"""

import logging
import shutil
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import delete, or_, select, update

from app.core.config import settings
from app.core.database import filtro_empresa
from app.models import AiCallUsage, Appointment, CallLog, CampaignNumber, Debt, PaymentPromise
from app.services.appointments import MIN_DIGITOS_TELEFONO, condicion_telefono, solo_digitos

logger = logging.getLogger(__name__)

ANONIMIZADO = "anonimizado"

# Tabla -> (modelo, columnas con el teléfono). Lo que se elimina entero.
_SE_ELIMINAN = {
    "citas": (Appointment, ("phone",)),
    "deudas": (Debt, ("phone",)),
    "promesas_de_pago": (PaymentPromise, ("phone",)),
    "numeros_de_campana": (CampaignNumber, ("phone",)),
}


class TelefonoInvalido(ValueError):
    pass


def _condicion(modelo, columnas, telefono):
    condiciones = [condicion_telefono(getattr(modelo, c), telefono) for c in columnas]
    if any(c is None for c in condiciones):
        raise TelefonoInvalido("El teléfono no tiene dígitos suficientes para identificar a una persona")
    return or_(*condiciones)


def _fila(obj, sin: tuple[str, ...] = ()) -> dict:
    salida = {}
    for col in obj.__table__.columns:
        if col.key == "tenant_id" or col.key in sin:
            continue
        valor = getattr(obj, col.key)
        if isinstance(valor, (datetime, date)):
            valor = valor.isoformat()
        salida[col.key] = valor
    return salida


async def _filas(session, modelo, columnas, telefono):
    consulta = select(modelo).where(_condicion(modelo, columnas, telefono), filtro_empresa(session, modelo))
    return (await session.execute(consulta.order_by(modelo.id))).unique().scalars().all()


async def datos_del_titular(session, telefono: str) -> dict:
    """Todo lo que la empresa de la sesión guarda asociado a `telefono`."""
    datos = {}
    for nombre, (modelo, columnas) in _SE_ELIMINAN.items():
        datos[nombre] = [_fila(f) for f in await _filas(session, modelo, columnas, telefono)]
    llamadas = await _filas(session, CallLog, ("caller_number", "callee_number"), telefono)
    # La ruta interna del archivo no le sirve a nadie fuera; se dice si hay
    # grabación y el panel la entrega por /api/calls/{id}/recording.
    datos["llamadas"] = [
        {**_fila(f, sin=("recording_path",)), "tiene_grabacion": bool(f.recording_path)} for f in llamadas
    ]
    datos["conversaciones_voicebot"] = [
        _fila(f) for f in await _filas(session, AiCallUsage, ("phone",), telefono)
    ]
    return datos


def _borrar_grabacion(recording_path: str | None) -> bool:
    if not recording_path:
        return False
    from app.api.calls import _local_recording_path

    archivo = _local_recording_path(recording_path)
    if archivo.is_file():
        archivo.unlink()
        return True
    return False


async def suprimir_titular(session, telefono: str) -> dict:
    """Elimina o anonimiza todo lo asociado a `telefono` en la empresa de la
    sesión. Devuelve cuántas filas tocó en cada tabla. No hace commit."""
    cuentas = {}
    # Primero las promesas: las deudas las referencian.
    for nombre in ("promesas_de_pago", "citas", "deudas", "numeros_de_campana"):
        modelo, columnas = _SE_ELIMINAN[nombre]
        ids = [f.id for f in await _filas(session, modelo, columnas, telefono)]
        if ids:
            await session.execute(
                delete(modelo).where(modelo.id.in_(ids), filtro_empresa(session, modelo)).execution_options(
                    synchronize_session=False
                )
            )
        cuentas[nombre] = len(ids)

    llamadas = await _filas(session, CallLog, ("caller_number", "callee_number"), telefono)
    grabaciones = 0
    for c in llamadas:
        if _borrar_grabacion(c.recording_path):
            grabaciones += 1
        if condicion_coincide(c.caller_number, telefono):
            c.caller_number = ANONIMIZADO
            c.caller_name = None
        if condicion_coincide(c.callee_number, telefono):
            c.callee_number = ANONIMIZADO
        c.recording_path = None
        c.summary = None
    cuentas["llamadas_anonimizadas"] = len(llamadas)
    cuentas["grabaciones_borradas"] = grabaciones

    conversaciones = await _filas(session, AiCallUsage, ("phone",), telefono)
    if conversaciones:
        await session.execute(
            update(AiCallUsage)
            .where(AiCallUsage.id.in_([f.id for f in conversaciones]), filtro_empresa(session, AiCallUsage))
            .values(phone=None, action_patient_name=None)
            .execution_options(synchronize_session=False)
        )
    cuentas["conversaciones_anonimizadas"] = len(conversaciones)
    await session.flush()
    return cuentas


def condicion_coincide(guardado: str | None, telefono: str) -> bool:
    """Lo mismo que `condicion_telefono`, en Python, para un valor ya leído."""
    d, g = solo_digitos(telefono), solo_digitos(guardado)
    return len(d) >= MIN_DIGITOS_TELEFONO and g.endswith(d[-10:])


def borrar_archivos_de_empresa(tenant_id: int, bot_ids: list[int]) -> None:
    """Grabaciones y audios de voizbot de una empresa que se borra. La base
    se lleva sus filas en cascada; los archivos no estaban atados a nada."""
    from app.services import greetings
    from app.services.config_generator import carpeta_grabaciones

    base = Path(settings.recordings_dir)
    carpeta = base / carpeta_grabaciones(tenant_id)
    if carpeta.is_dir() and not carpeta.is_symlink():
        shutil.rmtree(carpeta, ignore_errors=True)
    for f in base.glob(f"queue_t{int(tenant_id)}_*"):
        f.unlink(missing_ok=True)
    for bot_id in bot_ids:
        greetings.remove_greeting(bot_id)
        greetings.remove_all_node_audio(bot_id)
    logger.info("Archivos de la empresa %s borrados (%s voizbots)", tenant_id, len(bot_ids))
