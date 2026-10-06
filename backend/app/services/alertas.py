"""Alertas de tráfico saliente anómalo, por empresa.

El fraude telefónico típico es de madrugada y en ráfaga: alguien adivina
la clave de una extensión y marca destinos caros durante horas. El cupo
diario de minutos lo corta; estas alertas sirven para enterarse ANTES de
llegar al cupo, y para lo que el cupo no ve (destinos nuevos).

Avisan, no cortan. Una campaña nueva también es un pico, y cortarla por
una sospecha pararía una operación legítima. El corte duro lo dan el cupo
diario y los interruptores (ver services/salientes.py).

Se revisa cada pocos minutos desde workers/maintenance.py, con la sesión
del dueño (todas las empresas). Cada alerta queda en `security_alerts`
(la empresa la ve en Seguridad; la plataforma, en Empresas) y, si está
configurado, se manda a ALERTAS_WEBHOOK_URL.
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import case, func, select

from app.core.clock import business_tz
from app.core.config import settings
from app.models import CallLog, License, SecurityAlert, Tenant
from app.services import licensing, salientes

logger = logging.getLogger(__name__)

# Pico: la última hora supera MULTIPLICADOR veces el promedio de esa misma
# hora en los DIAS_BASE días anteriores, y además PISO_MINUTOS (para no
# alertar por pasar de 1 a 4 minutos en una empresa chica).
MULTIPLICADOR = 3
DIAS_BASE = 7
PISO_MINUTOS = 30
# Madrugada: más de esto entre las 00:00 y las 05:00 locales.
MADRUGADA_MINUTOS = 10
# Destino nuevo: un prefijo internacional (primeros dígitos tras 00/011/+)
# que no se usó en los últimos DIAS_HISTORIAL días.
DIAS_HISTORIAL = 30
DIGITOS_DESTINO = 4
# Aviso de cupo: a partir de esta fracción del cupo diario.
FRACCION_CUPO = 0.8
# Una alerta del mismo tipo para la misma empresa, como mucho cada tanto.
SILENCIO = timedelta(hours=6)


def _prefijo_destino(numero: str | None) -> str | None:
    n = salientes.normalizar(numero)
    for p in salientes.PREFIJOS_INTERNACIONALES:
        if n.startswith(p):
            resto = n[len(p):]
            return resto[:DIGITOS_DESTINO] if resto.isdigit() and resto else None
    return None


async def _minutos(session, desde: datetime, hasta: datetime) -> dict[int, float]:
    filas = (
        await session.execute(
            select(CallLog.tenant_id, func.coalesce(func.sum(CallLog.billsec), 0))
            .where(CallLog.via_trunk.is_(True), CallLog.started_at >= desde, CallLog.started_at < hasta)
            .group_by(CallLog.tenant_id)
        )
    ).all()
    return {tid: seg / 60 for tid, seg in filas}


async def detectar(session, ahora: datetime | None = None) -> list[tuple[int, str, str]]:
    """Lo anómalo en este momento: [(tenant_id, tipo, detalle)].

    `ahora` es UTC naive, la escala de `CallLog.started_at`."""
    ahora = ahora or datetime.utcnow()
    hallazgos: list[tuple[int, str, str]] = []
    hace_una_hora = ahora - timedelta(hours=1)
    ultima = await _minutos(session, hace_una_hora, ahora)

    # Pico respecto de la misma hora de días anteriores.
    base: dict[int, float] = defaultdict(float)
    for dias in range(1, DIAS_BASE + 1):
        corrido = timedelta(days=dias)
        for tid, m in (await _minutos(session, hace_una_hora - corrido, ahora - corrido)).items():
            base[tid] += m / DIAS_BASE
    for tid, m in ultima.items():
        umbral = max(PISO_MINUTOS, MULTIPLICADOR * base.get(tid, 0))
        if m > umbral:
            hallazgos.append(
                (tid, "pico", f"{m:.0f} min salientes en la última hora (lo habitual a esta hora: {base.get(tid, 0):.0f} min)")
            )

    # Madrugada, en la hora del negocio.
    hora_local = ahora.replace(tzinfo=timezone.utc).astimezone(business_tz()).hour
    if hora_local < 5:
        for tid, m in ultima.items():
            if m > MADRUGADA_MINUTOS:
                hallazgos.append((tid, "madrugada", f"{m:.0f} min salientes en la última hora, de madrugada"))

    # Destinos internacionales nuevos.
    recientes = (
        await session.execute(
            select(CallLog.tenant_id, CallLog.callee_number).where(
                CallLog.via_trunk.is_(True), CallLog.started_at >= hace_una_hora
            )
        )
    ).all()
    nuevos_por_tenant: dict[int, set[str]] = defaultdict(set)
    for tid, numero in recientes:
        prefijo = _prefijo_destino(numero)
        if prefijo:
            nuevos_por_tenant[tid].add(prefijo)
    if nuevos_por_tenant:
        historicos = (
            await session.execute(
                select(CallLog.tenant_id, CallLog.callee_number).where(
                    CallLog.tenant_id.in_(list(nuevos_por_tenant)),
                    CallLog.via_trunk.is_(True),
                    CallLog.started_at >= ahora - timedelta(days=DIAS_HISTORIAL),
                    CallLog.started_at < hace_una_hora,
                )
            )
        ).all()
        conocidos: dict[int, set[str]] = defaultdict(set)
        for tid, numero in historicos:
            prefijo = _prefijo_destino(numero)
            if prefijo:
                conocidos[tid].add(prefijo)
        for tid, prefijos in nuevos_por_tenant.items():
            nuevos = sorted(prefijos - conocidos[tid])
            if nuevos:
                lista = ", ".join(f"+{p}…" for p in nuevos)
                hallazgos.append((tid, "destino_nuevo", f"Llamadas a destinos internacionales nuevos: {lista}"))

    # Cerca del cupo diario.
    hoy = await salientes.minutos_salientes_hoy(
        session, [t for (t,) in (await session.execute(select(Tenant.id))).all()]
    )
    licencias = {
        lic.tenant_id: lic
        for lic in (await session.execute(select(License).where(License.tenant_id.in_(list(hoy) or [0])))).scalars().all()
    }
    for tid, m in hoy.items():
        lic = licencias.get(tid)
        cupo = licensing.limite(lic, "max_outbound_minutes_day") if lic else None
        if cupo and m >= FRACCION_CUPO * cupo:
            hallazgos.append((tid, "cupo", f"{m:.0f} de {cupo} min del cupo diario de salientes"))

    return hallazgos


# --- Operación: lo que hace que la central deje de atender ----------------------------------
# Mismo canal que las de fraude (security_alerts, webhook) y, además, correo a
# los administradores de la empresa: a quien no mira el panel le llega igual.

LICENCIA_DIAS_AVISO = 7
ABANDONO_VENTANA = timedelta(minutes=30)
ABANDONO_MIN_LLAMADAS = 5
ABANDONO_PCT = 30
# Estados de un gateway de sofia que significan «no está conectado».
_GATEWAY_CAIDO = ("FAIL_WAIT", "FAILED", "UNREGED", "NOAVAIL", "DOWN")
# Silencio propio por tipo (el resto usa SILENCIO).
SILENCIO_POR_TIPO = {"licencia_vence": timedelta(hours=24), "licencia_vencida": timedelta(hours=24)}

TITULOS = {
    "pico": "Pico de llamadas salientes",
    "madrugada": "Llamadas salientes de madrugada",
    "destino_nuevo": "Destino internacional nuevo",
    "cupo": "Cerca del cupo diario de minutos",
    "troncal_caida": "Proveedor de telefonía desconectado",
    "licencia_vence": "La licencia está por vencer",
    "licencia_vencida": "La licencia venció",
    "abandono_alto": "Muchas llamadas colgaron esperando",
}


async def detectar_operacion(session, ahora: datetime | None = None) -> list[tuple[int, str, str]]:
    from app.models import Trunk
    from app.services import esl
    from app.services.gateways import nombre_gateway

    ahora = ahora or datetime.utcnow()
    hallazgos: list[tuple[int, str, str]] = []
    empresas = {t.id: t for t in (await session.execute(select(Tenant).where(Tenant.enabled.is_(True)))).scalars().all()}

    # Licencia por vencer o vencida (sin licencia vigente no se puede guardar nada).
    for lic in (await session.execute(select(License).where(License.tenant_id.in_(list(empresas) or [0])))).scalars().all():
        if lic.expires_at is None:
            continue
        if lic.expires_at <= ahora:
            hallazgos.append((lic.tenant_id, "licencia_vencida",
                              "La licencia venció: no se pueden guardar cambios hasta renovarla"))
        elif lic.expires_at <= ahora + timedelta(days=LICENCIA_DIAS_AVISO):
            dias = max(1, (lic.expires_at - ahora).days)
            hallazgos.append((lic.tenant_id, "licencia_vence", f"La licencia vence en {dias} día(s)"))

    # Proveedor de telefonía desconectado (solo las troncales que registran).
    troncales = (
        await session.execute(
            select(Trunk).where(Trunk.enabled.is_(True), Trunk.register_enabled.is_(True),
                                Trunk.tenant_id.in_(list(empresas) or [0]))
        )
    ).scalars().all()
    for t in troncales:
        try:
            estado = (await esl.gateway_status(nombre_gateway(t.name, empresas[t.tenant_id].slug))).get("state")
        except Exception:
            # Sin FreeSWITCH no se sabe: no se alerta por eso (lo ve la plataforma).
            continue
        if estado in _GATEWAY_CAIDO:
            hallazgos.append((t.tenant_id, "troncal_caida",
                              f"El proveedor «{t.name}» no está conectado ({estado}): no entran ni salen llamadas por él"))

    # Muchos colgando en la fila de un grupo en la última media hora.
    filas = (
        await session.execute(
            select(CallLog.tenant_id, CallLog.cola, func.count(),
                   func.sum(case((CallLog.cola_resultado == "abandonada", 1), else_=0)))
            .where(CallLog.cola.is_not(None), CallLog.started_at >= ahora - ABANDONO_VENTANA)
            .group_by(CallLog.tenant_id, CallLog.cola)
        )
    ).all()
    for tid, cola, n, abandonadas in filas:
        abandonadas = int(abandonadas or 0)
        if n >= ABANDONO_MIN_LLAMADAS and 100 * abandonadas >= ABANDONO_PCT * n:
            hallazgos.append((tid, "abandono_alto",
                              f"Grupo «{cola}»: {abandonadas} de {n} llamadas colgaron esperando en la última media hora"))
    return hallazgos


async def _correo(alerta: SecurityAlert, empresa: str) -> None:
    """A los administradores de la empresa con correo (si hay SMTP)."""
    from app.core import permissions
    from app.core.database import async_session
    from app.models import User
    from app.services import reportes_programados

    if not reportes_programados.correo_configurado():
        return
    async with async_session() as session:
        para = [
            e for (e,) in (
                await session.execute(
                    select(User.email).where(User.tenant_id == alerta.tenant_id, User.role == permissions.ADMIN,
                                             User.enabled.is_(True), User.email.is_not(None))
                )
            ).all() if e and "@" in e
        ]
    if not para:
        return
    titulo = TITULOS.get(alerta.kind, "Aviso de la central")
    try:
        await reportes_programados.enviar_correo(
            para, f"[NSPBX] {titulo}",
            f"{empresa}: {alerta.detail}\n\nLo ves también en el panel, en el Inicio (Avisos).", [],
        )
    except Exception as exc:
        logger.warning("No se pudo enviar la alerta por correo: %s", exc)


async def _avisar(alerta: SecurityAlert, empresa: str) -> None:
    await _correo(alerta, empresa)
    if not settings.alertas_webhook_url:
        return
    texto = f"[NSPBX] {empresa}: {alerta.detail}"
    try:
        async with httpx.AsyncClient(timeout=5) as cliente:
            await cliente.post(
                settings.alertas_webhook_url,
                # `text` es lo que leen Slack y Teams; el resto, para quien
                # quiera procesarlo.
                json={"text": texto, "empresa": empresa, "tipo": alerta.kind, "detalle": alerta.detail,
                      "cuando": alerta.created_at.isoformat() + "Z"},
            )
    except Exception as exc:
        logger.warning("No se pudo enviar la alerta al webhook: %s", exc)


async def revisar(session, ahora: datetime | None = None) -> list[SecurityAlert]:
    """Detecta, guarda lo nuevo (sin repetir un tipo por empresa antes de
    SILENCIO) y avisa. Devuelve las alertas creadas."""
    ahora = ahora or datetime.utcnow()
    hallazgos = await detectar(session, ahora)
    try:
        hallazgos += await detectar_operacion(session, ahora)
    except Exception:
        logger.exception("No se pudieron revisar las alertas de operación")
    if not hallazgos:
        return []
    mas_largo = max([SILENCIO, *SILENCIO_POR_TIPO.values()])
    recientes = {
        (tid, kind)
        for tid, kind, cuando in (
            await session.execute(
                select(SecurityAlert.tenant_id, SecurityAlert.kind, SecurityAlert.created_at)
                .where(SecurityAlert.created_at >= ahora - mas_largo)
            )
        ).all()
        if cuando >= ahora - SILENCIO_POR_TIPO.get(kind, SILENCIO)
    }
    nombres = {t.id: t.name for t in (await session.execute(select(Tenant))).scalars().all()}
    creadas = []
    for tid, kind, detalle in hallazgos:
        if (tid, kind) in recientes:
            continue
        recientes.add((tid, kind))
        alerta = SecurityAlert(tenant_id=tid, kind=kind, detail=detalle, created_at=ahora)
        session.add(alerta)
        creadas.append(alerta)
        logger.warning("ALERTA (%s) en %s: %s", kind, nombres.get(tid, tid), detalle)
    await session.commit()
    for alerta in creadas:
        await _avisar(alerta, nombres.get(alerta.tenant_id, str(alerta.tenant_id)))
    return creadas
