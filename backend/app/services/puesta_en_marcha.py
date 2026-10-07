"""Puesta en marcha de una empresa: los pasos para dejar la central
funcionando, en el orden en que se hacen, con lo que el sistema ve en vivo.

Quien entra por primera vez ve más de veinte opciones de menú (troncales,
rutas, colas…) y no sabe por dónde empezar ni qué le falta. Como la lista
de «primeros pasos» de Aircall o Talkdesk: cada paso se marca solo cuando
está hecho, dice qué falta y lleva a la pantalla donde se arregla.
"""

import logging

from sqlalchemy import func, select

from app.models import CallLog, Campaign, Extension, InboundRoute, Queue, SystemSettings, Tenant, Trunk, User
from app.services import esl, licensing
from app.services.gateways import nombre_gateway

logger = logging.getLogger(__name__)


def _paso(clave: str, titulo: str, hecho: bool, detalle: str, enlace: str, accion: str, opcional: bool = False) -> dict:
    return {
        "clave": clave, "titulo": titulo, "hecho": hecho, "detalle": detalle,
        "enlace": enlace, "accion": accion, "opcional": opcional,
    }


async def _contar(session, modelo, *condiciones) -> int:
    return (await session.execute(select(func.count()).select_from(modelo).where(*condiciones))).scalar_one()


async def _proveedor_conectado(troncales: list[Trunk], slug: str, tenant_id: int) -> bool | None:
    """True si alguna troncal está registrada (o activa sin registro).
    None si no se pudo preguntar a FreeSWITCH."""
    try:
        for t in troncales:
            estado = (await esl.gateway_status(nombre_gateway(t.name, slug), tenant_id=tenant_id)).get("state")
            if estado in ("REGED", "NOREG"):
                return True
        return False
    except Exception as exc:
        logger.info("Puesta en marcha: no se pudo consultar las troncales: %s", exc)
        return None


async def _telefonos_conectados(dominio: str, tenant_id: int) -> int | None:
    """Teléfonos o softphones registrados en el dominio de la empresa."""
    try:
        cuerpo = await esl.api("show registrations", tenant_id=tenant_id)
    except Exception as exc:
        logger.info("Puesta en marcha: no se pudo consultar los registros: %s", exc)
        return None
    # CSV: reg_user,realm,token,url,…
    return sum(1 for linea in cuerpo.splitlines()[1:] if linea.split(",")[1:2] == [dominio])


async def revisar(session, tenant_id: int) -> dict:
    empresa = await session.get(Tenant, tenant_id)
    ajustes = (await session.execute(select(SystemSettings).where(SystemSettings.tenant_id == tenant_id).limit(1))).scalar_one_or_none()
    dominio = (ajustes.fs_domain if ajustes and ajustes.fs_domain else None) or (empresa.sip_domain if empresa else "")
    pasos: list[dict] = []

    st = licensing.estado(await licensing.obtener(session, tenant_id))
    if st != "ok":
        pasos.append(_paso(
            "licencia", "Licencia al día", False,
            f"La licencia de la empresa está {st}: mientras tanto no se puede crear ni cambiar nada, ni llamar. "
            "La renueva el operador de la plataforma.",
            "", "",
        ))

    troncales = list((await session.execute(select(Trunk).where(Trunk.tenant_id == tenant_id, Trunk.enabled.is_(True)))).scalars())
    if not troncales:
        pasos.append(_paso(
            "proveedor", "Conecta tu proveedor de telefonía", False,
            "Es la línea por la que entran y salen las llamadas (Claro, Tigo, ETB, Movistar…). Necesitas el usuario y la "
            "clave que te dio el proveedor.",
            "/trunks", "Conectar proveedor",
        ))
    else:
        conectado = await _proveedor_conectado(troncales, empresa.slug if empresa else "", tenant_id)
        pasos.append(_paso(
            "proveedor",
            "Conecta tu proveedor de telefonía",
            conectado is not False,
            "Conectado." if conectado else (
                "No se pudo comprobar ahora; revisa el estado en la pantalla del proveedor."
                if conectado is None else
                "Está creado, pero el proveedor no lo acepta todavía: revisa usuario, clave y servidor."
            ),
            "/trunks", "Ver proveedor",
        ))

    extensiones = await _contar(session, Extension, Extension.tenant_id == tenant_id, Extension.enabled.is_(True))
    con_extension = await _contar(session, User, User.tenant_id == tenant_id, User.enabled.is_(True), User.extension_id.is_not(None))
    pasos.append(_paso(
        "equipo", "Crea a tu equipo", con_extension > 0,
        f"{con_extension} persona(s) con teléfono." if con_extension else (
            "Ya hay extensiones, pero ninguna persona tiene una asignada: en Usuarios, edita a la persona y asígnale una."
            if extensiones else
            "Cada persona que atiende o hace llamadas necesita un usuario y una extensión (su número interno)."
        ),
        "/users" if extensiones else "/extensions", "Agregar personas",
    ))

    telefonos = await _telefonos_conectados(dominio, tenant_id) if dominio else None
    pasos.append(_paso(
        "telefono", "Conecta un teléfono", bool(telefonos) or telefonos is None,
        f"{telefonos} teléfono(s) conectado(s) ahora." if telefonos else (
            "No se pudo comprobar ahora." if telefonos is None else
            "Abre el Softphone del panel (o la app móvil) con una persona que tenga extensión, y pulsa Conectar."
        ),
        "/softphone", "Abrir softphone",
    ))

    entrantes = await _contar(session, InboundRoute, InboundRoute.tenant_id == tenant_id, InboundRoute.enabled.is_(True))
    pasos.append(_paso(
        "entrante", "Recibe llamadas en tu número", entrantes > 0,
        f"{entrantes} número(s) entrante(s) configurado(s)." if entrantes else
        "Di a dónde va una llamada cuando alguien marca tu número: a una persona, a un grupo o al voizbot.",
        "/inbound-routes", "Configurar número",
    ))

    llamadas = await _contar(session, CallLog, CallLog.tenant_id == tenant_id, CallLog.status == "answered")
    pasos.append(_paso(
        "prueba", "Haz tu primera llamada", llamadas > 0,
        "Ya hubo llamadas contestadas." if llamadas else
        "Desde el Softphone, marca tu celular. Si suena y se oye bien, la central está lista.",
        "/softphone", "Llamar",
    ))

    colas = await _contar(session, Queue, Queue.tenant_id == tenant_id, Queue.enabled.is_(True))
    pasos.append(_paso(
        "grupo", "Arma un grupo de atención", colas > 0,
        f"{colas} grupo(s) de atención." if colas else
        "Para que una llamada suene en varias personas a la vez (ventas, soporte…).",
        "/queues", "Crear grupo", opcional=True,
    ))

    if empresa and "voicebot" in empresa.modules_list:
        campanas = await _contar(session, Campaign, Campaign.tenant_id == tenant_id)
        pasos.append(_paso(
            "campana", "Crea tu primera campaña", campanas > 0,
            f"{campanas} campaña(s)." if campanas else
            "Para llamar a una lista de clientes con tus agentes o con un voizbot.",
            "/campaigns", "Crear campaña", opcional=True,
        ))

    obligatorios = [p for p in pasos if not p["opcional"]]
    return {
        "pasos": pasos,
        "hechos": sum(1 for p in pasos if p["hecho"]),
        "total": len(pasos),
        "listo": all(p["hecho"] for p in obligatorios),
    }
