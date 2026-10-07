"""Prueba de humo contra la central real (FreeSWITCH de la empresa).

Las pruebas automáticas usan una central simulada: un detalle de FreeSWITCH
(una variable, el formato de `list members`, xml_curl caído) solo aparece con
llamadas de verdad. Esto hace llamadas `loopback/` dentro de la central, sin
salir al proveedor, y comprueba cada paso con lo que llega al backend (el
CDR, la fila del grupo):

- central: ESL responde y FreeSWITCH está arriba;
- proveedores: cada troncal con registro está registrada;
- teléfonos: cuántos hay conectados en el dominio de la empresa;
- voces: los avisos de voz en español existen;
- sin_ruta: una llamada a un número inventado entra por el contexto público,
  se cuelga y llega a «números sin ruta» (prueba el dialplan por xml_curl y
  el CDR de punta a punta);
- buzón (si se indica una extensión con buzón): deja un mensaje de prueba y
  comprueba que se guardó; después lo borra;
- grupo (si se indica uno): entra a la fila y comprueba que mod_callcenter
  lo tiene esperando; después cuelga. OJO: los agentes de ese grupo pueden
  oír timbrar unos segundos.

Las llamadas de prueba salen con un caller ID que empieza por PREFIJO: el
buzón no manda correo por ellas y se reconocen en el historial.

Uso: `python -m app.humo --empresa <slug> [--buzon 101] [--grupo 8000]` o
Plataforma › Empresas › «Probar la central».
"""

import asyncio
import logging
import random
import time
import uuid as uuidlib
from dataclasses import asdict, dataclass

from sqlalchemy import delete, select

from app.core import validacion
from app.core.database import async_session
from app.models import Extension, MensajeBuzon, NumeroSinRuta, Queue, SystemSettings, Tenant, Trunk
from app.services import esl, voice_prompts

logger = logging.getLogger(__name__)

PREFIJO = "9990"
ESPERA_CDR_SEG = 40
_AVISOS = ("buzon_saludo", "cola_aviso", "cola_delante_0", "dnd_no_disponible", "ivr_opcion_invalida")


@dataclass
class Paso:
    clave: str
    titulo: str
    estado: str  # ok | fallo | aviso | omitido
    detalle: str
    ms: int = 0


def _numero() -> str:
    return f"{PREFIJO}{random.randint(0, 999999):06d}"


async def _esperar(consulta, segundos: float | None = None, cada: float = 1.0):
    """Repite `consulta()` hasta que devuelva algo o se acabe el tiempo."""
    fin = time.monotonic() + (ESPERA_CDR_SEG if segundos is None else segundos)
    while True:
        resultado = await consulta()
        if resultado or time.monotonic() >= fin:
            return resultado
        await asyncio.sleep(cada)


async def _central(tenant_id: int) -> Paso:
    try:
        estado = await esl.api("status", tenant_id=tenant_id)
    except Exception as exc:
        return Paso("central", "Conexión con la central", "fallo", f"No responde por ESL: {exc}")
    if "UP" not in estado:
        return Paso("central", "Conexión con la central", "fallo", estado.strip()[:200])
    primera = estado.strip().splitlines()[0] if estado.strip() else ""
    return Paso("central", "Conexión con la central", "ok", primera[:160])


async def _proveedores(session, empresa: Tenant) -> Paso:
    from app.services.gateways import nombre_gateway

    troncales = (
        await session.execute(select(Trunk).where(Trunk.tenant_id == empresa.id, Trunk.enabled.is_(True)))
    ).scalars().all()
    if not troncales:
        return Paso("proveedores", "Proveedor de telefonía", "aviso", "La empresa no tiene proveedores activos")
    malos, buenos = [], []
    for t in troncales:
        try:
            estado = (await esl.gateway_status(nombre_gateway(t.name, empresa.slug), tenant_id=empresa.id)).get("state")
        except Exception as exc:
            malos.append(f"{t.name}: sin respuesta ({exc})")
            continue
        if estado in ("REGED", "NOREG"):
            buenos.append(f"{t.name}: {estado}")
        else:
            malos.append(f"{t.name}: {estado or 'desconocido'}")
    if malos:
        return Paso("proveedores", "Proveedor de telefonía", "fallo", "; ".join(malos + buenos))
    return Paso("proveedores", "Proveedor de telefonía", "ok", "; ".join(buenos))


async def _telefonos(dominio: str, tenant_id: int) -> Paso:
    from app.services.puesta_en_marcha import _telefonos_conectados

    n = await _telefonos_conectados(dominio, tenant_id)
    if n is None:
        return Paso("telefonos", "Teléfonos conectados", "fallo", "No se pudo consultar los registros")
    if n == 0:
        return Paso("telefonos", "Teléfonos conectados", "aviso", "Ningún teléfono ni softphone conectado")
    return Paso("telefonos", "Teléfonos conectados", "ok", f"{n} conectado(s) en {dominio}")


def _voces() -> Paso:
    faltan = [k for k in _AVISOS if voice_prompts.prompt_path(k) is None]
    if faltan:
        return Paso("voces", "Avisos de voz en español", "aviso",
                    f"Faltan {', '.join(faltan)}: suenan con la voz de respaldo hasta que se generen")
    return Paso("voces", "Avisos de voz en español", "ok", "Todos los avisos están generados")


async def _sin_ruta(tenant_id: int) -> Paso:
    titulo = "Llamada a un número sin ruta (dialplan y CDR)"
    numero = _numero()
    try:
        # Entra por el contexto público, como una llamada del proveedor; el
        # dialplan la cuelga (UNALLOCATED_NUMBER), así que el originate falla.
        await esl.bgapi(
            f"originate {{origination_caller_id_number={_numero()},ignore_early_media=true}}"
            f"loopback/{numero}/public &park()",
            tenant_id=tenant_id,
        )
    except Exception as exc:
        return Paso("sin_ruta", titulo, "fallo", f"No se pudo originar: {exc}")

    async def buscar():
        async with async_session() as s:
            return (await s.execute(select(NumeroSinRuta).where(NumeroSinRuta.numero == numero))).scalar_one_or_none()

    fila = await _esperar(buscar)
    if fila is None:
        return Paso("sin_ruta", titulo, "fallo",
                    f"El CDR de la llamada a {numero} no llegó en {ESPERA_CDR_SEG} s: revisa json_cdr y el secreto de FreeSWITCH")
    async with async_session() as s:
        await s.execute(delete(NumeroSinRuta).where(NumeroSinRuta.id == fila.id))
        await s.commit()
    return Paso("sin_ruta", titulo, "ok", "La central pidió el dialplan, colgó la llamada y el CDR llegó")


async def _buzon(empresa: Tenant, contexto: str, extension: str) -> Paso:
    titulo = f"Buzón de voz de la {extension}"
    quien = _numero()
    try:
        await esl.bgapi(
            f"originate {{origination_caller_id_number={quien},origination_caller_id_name=Prueba,"
            f"ignore_early_media=true}}loopback/*99{extension}/{contexto} "
            "&playback(tone_stream://%(15000,0,440))",
            tenant_id=empresa.id,
        )
    except Exception as exc:
        return Paso("buzon", titulo, "fallo", f"No se pudo originar: {exc}")

    async def buscar():
        async with async_session() as s:
            return (
                await s.execute(select(MensajeBuzon).where(MensajeBuzon.tenant_id == empresa.id,
                                                           MensajeBuzon.caller_number == quien))
            ).scalar_one_or_none()

    mensaje = await _esperar(buscar, ESPERA_CDR_SEG * 3 // 2)
    if mensaje is None:
        return Paso("buzon", titulo, "fallo",
                    "No llegó el mensaje: revisa que la central pueda escribir en la carpeta de grabaciones y que el CDR llegue")
    from app.services import buzon

    local = buzon.ruta_local(mensaje.ruta, empresa.id)
    async with async_session() as s:
        await s.execute(delete(MensajeBuzon).where(MensajeBuzon.id == mensaje.id))
        await s.commit()
    if local is not None:
        try:
            local.unlink(missing_ok=True)
        except OSError:
            pass
    return Paso("buzon", titulo, "ok", f"Grabó un mensaje de {mensaje.duracion} s y se guardó (ya se borró)")


async def _grupo(empresa: Tenant, contexto: str, dominio: str, cola: Queue) -> Paso:
    from app.services import posicion_colas
    from app.services.queues_sync import _queue_key

    titulo = f"Grupo {cola.name} ({cola.extension})"
    quien = _numero()
    canal = str(uuidlib.uuid4())
    qkey = _queue_key(cola.name, dominio)
    try:
        await esl.bgapi(
            f"originate {{origination_uuid={canal},origination_caller_id_number={quien},"
            f"origination_caller_id_name=Prueba}}loopback/{cola.extension}/{contexto} &park()",
            tenant_id=empresa.id,
        )
    except Exception as exc:
        return Paso("grupo", titulo, "fallo", f"No se pudo originar: {exc}")

    async def en_fila():
        try:
            salida = await esl.api(f"callcenter_config queue list members {qkey}", tenant_id=empresa.id)
        except Exception:
            return None
        return quien in salida and salida

    try:
        salida = await _esperar(en_fila, 15)
        agentes = ""
        try:
            agentes = await esl.api(f"callcenter_config queue list agents {qkey}", tenant_id=empresa.id)
        except Exception:
            pass
    finally:
        try:
            await esl.api(f"uuid_kill {canal}", tenant_id=empresa.id)
        except Exception:
            pass
    if not salida:
        return Paso("grupo", titulo, "fallo",
                    "La llamada no apareció esperando en el grupo: revisa que el grupo esté cargado en mod_callcenter")
    libres = sum(1 for l in agentes.splitlines() if "|Available|" in l and "|Waiting|" in l)
    esperando = len(posicion_colas.esperando(salida))
    return Paso("grupo", titulo, "ok", f"Entró a la fila ({esperando} esperando); {libres} agente(s) libre(s)")


async def probar(tenant_id: int, extension_buzon: str | None = None, grupo: str | None = None) -> dict:
    """Corre los pasos y devuelve {empresa, pasos, ok}. No lanza: cada paso
    dice su propio fallo."""
    inicio = time.monotonic()
    async with async_session() as session:
        empresa = await session.get(Tenant, tenant_id)
        if empresa is None:
            raise ValueError("Empresa no encontrada")
        ajustes = (
            await session.execute(select(SystemSettings).where(SystemSettings.tenant_id == tenant_id).limit(1))
        ).scalar_one_or_none()
        dominio = (ajustes.fs_domain if ajustes and ajustes.fs_domain else None) or empresa.sip_domain
        contexto = empresa.dialplan_context
        cola = None
        if grupo:
            cola = (
                await session.execute(select(Queue).where(Queue.tenant_id == tenant_id, Queue.extension == grupo))
            ).scalar_one_or_none()
        ext = None
        if extension_buzon:
            ext = (
                await session.execute(
                    select(Extension).where(Extension.tenant_id == tenant_id, Extension.number == extension_buzon)
                )
            ).scalar_one_or_none()

        pasos: list[Paso] = []

        async def medir(corrutina):
            t = time.monotonic()
            paso = await corrutina
            paso.ms = int((time.monotonic() - t) * 1000)
            pasos.append(paso)
            return paso

        central = await medir(_central(tenant_id))
        if central.estado == "fallo":
            pasos.append(Paso("resto", "El resto de la prueba", "omitido", "Sin conexión con la central no se puede seguir"))
        else:
            await medir(_proveedores(session, empresa))
            await medir(_telefonos(dominio, tenant_id))
            pasos.append(_voces())
            await medir(_sin_ruta(tenant_id))
            if extension_buzon:
                if ext is None or not ext.voicemail or not validacion.EXTENSION_RE.fullmatch(ext.number):
                    pasos.append(Paso("buzon", f"Buzón de voz de la {extension_buzon}", "fallo",
                                      "Esa extensión no existe en la empresa o no tiene buzón"))
                else:
                    await medir(_buzon(empresa, contexto, ext.number))
            if grupo:
                if cola is None or not cola.enabled:
                    pasos.append(Paso("grupo", f"Grupo {grupo}", "fallo", "Ese grupo no existe en la empresa o está apagado"))
                else:
                    await medir(_grupo(empresa, contexto, dominio, cola))
    return {
        "empresa": empresa.name,
        "ok": all(p.estado != "fallo" for p in pasos),
        "segundos": round(time.monotonic() - inicio, 1),
        "pasos": [asdict(p) for p in pasos],
    }
