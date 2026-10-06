"""Reportes que salen solos por correo (fase 6), con el CSV adjunto.

- Diaria: el día anterior. Semanal: la semana anterior (lunes a domingo),
  el lunes. Mensual: el mes anterior, el día 1. Siempre períodos CERRADOS:
  un reporte de «hoy» a las 7 de la mañana no dice nada.
- Sale a la hora local elegida. Si el servidor estuvo apagado a esa hora,
  sale al volver (se guarda qué período ya se mandó: nunca dos veces).
- Si el correo falla, se reintenta cada 30 minutos y el panel muestra el error.
- El correo es de la plataforma (SMTP_* en el .env), no de cada empresa.
"""

import asyncio
import logging
import re
import smtplib
import ssl
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from email.message import EmailMessage

from sqlalchemy import select

from app.core.clock import now_local
from app.core.config import settings
from app.core.database import async_session, sesion_de_empresa
from app.models import ReporteProgramado, Tenant
from app.services import reportes

logger = logging.getLogger(__name__)

FRECUENCIAS = ("diaria", "semanal", "mensual")
MAX_DESTINATARIOS = 10
ESPERA_TRAS_ERROR = timedelta(minutes=30)
_CORREO = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")
NOMBRES = {"agentes": "Agentes", "campanas": "Campañas", "disposiciones": "Disposiciones", "cumplimiento": "Cumplimiento"}


def correo_configurado() -> bool:
    return bool(settings.smtp_host and settings.smtp_remitente)


def leer_destinatarios(texto: str) -> list[str]:
    correos = [c.strip().lower() for c in re.split(r"[,;\s]+", texto or "") if c.strip()]
    if not correos:
        raise ValueError("Indica al menos un correo")
    if len(correos) > MAX_DESTINATARIOS:
        raise ValueError(f"Máximo {MAX_DESTINATARIOS} destinatarios")
    malos = [c for c in correos if not _CORREO.match(c)]
    if malos:
        raise ValueError(f"Correo inválido: {malos[0]}")
    return sorted(set(correos))


@dataclass
class Periodo:
    desde: date
    hasta: date
    etiqueta: str
    # Primer día en que el período ya está cerrado (cuando le toca salir).
    sale: date


def periodo(frecuencia: str, hoy: date) -> Periodo:
    """El último período cerrado a la fecha `hoy`."""
    if frecuencia == "diaria":
        d = hoy - timedelta(days=1)
        return Periodo(d, d, d.isoformat(), hoy)
    if frecuencia == "semanal":
        lunes = hoy - timedelta(days=hoy.weekday())
        desde = lunes - timedelta(days=7)
        anio, semana, _ = desde.isocalendar()
        return Periodo(desde, lunes - timedelta(days=1), f"{anio}-S{semana:02d}", lunes)
    if frecuencia == "mensual":
        primero = hoy.replace(day=1)
        fin = primero - timedelta(days=1)
        return Periodo(fin.replace(day=1), fin, f"{fin:%Y-%m}", primero)
    raise ValueError(frecuencia)


def toca(rep: ReporteProgramado, ahora_local: datetime, ahora_utc: datetime) -> Periodo | None:
    """El período a enviar ahora, o None."""
    if not rep.activo:
        return None
    p = periodo(rep.frecuencia, ahora_local.date())
    if rep.ultimo_periodo == p.etiqueta:
        return None
    # El día en que cierra, recién a la hora elegida; después, apenas se pueda.
    if ahora_local.date() == p.sale and ahora_local.hour < rep.hora:
        return None
    if rep.ultimo_error and rep.ultimo_intento_at and ahora_utc - rep.ultimo_intento_at < ESPERA_TRAS_ERROR:
        return None
    return p


def _enviar_smtp(mensaje: EmailMessage) -> None:
    seguridad = (settings.smtp_seguridad or "starttls").lower()
    contexto = ssl.create_default_context()
    if seguridad == "ssl":
        servidor = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=30, context=contexto)
    else:
        servidor = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30)
    with servidor:
        if seguridad == "starttls":
            servidor.starttls(context=contexto)
        if settings.smtp_usuario:
            servidor.login(settings.smtp_usuario, settings.smtp_clave)
        servidor.send_message(mensaje)


async def enviar_correo(destinatarios: list[str], asunto: str, cuerpo: str, adjuntos: list[tuple[str, str]]) -> None:
    if not correo_configurado():
        raise RuntimeError("El correo saliente no está configurado en el servidor (SMTP_HOST y SMTP_REMITENTE)")
    m = EmailMessage()
    m["From"] = settings.smtp_remitente
    m["To"] = ", ".join(destinatarios)
    m["Subject"] = asunto
    m.set_content(cuerpo)
    for nombre, texto in adjuntos:
        m.add_attachment(texto.encode("utf-8"), maintype="text", subtype="csv", filename=nombre)
    await asyncio.to_thread(_enviar_smtp, m)


def _resumen(tipo: str, datos: dict) -> list[str]:
    t = datos.get("total") or {}
    if tipo == "agentes":
        return [f"Agentes: {len(datos['filas'])}", f"Llamadas: {t.get('llamadas', 0)}",
                f"Ocupación: {t.get('ocupacion_pct') if t.get('ocupacion_pct') is not None else '—'} %"]
    if tipo == "campanas":
        return [f"Intentos: {t.get('intentos', 0)}", f"Contestadas: {t.get('contestadas', 0)}",
                f"Abandono: {t.get('abandono_pct') if t.get('abandono_pct') is not None else '—'} %",
                f"Conversión: {t.get('conversion_pct') if t.get('conversion_pct') is not None else '—'} %"]
    if tipo == "entrantes":
        return [f"Llamadas a grupos: {t.get('ofrecidas', 0)}", f"Atendidas: {t.get('atendidas', 0)}",
                f"Nivel de servicio ({datos['umbral_s']} s): {t.get('nivel_servicio_pct') if t.get('nivel_servicio_pct') is not None else '—'} %",
                f"Abandono: {t.get('abandono_pct') if t.get('abandono_pct') is not None else '—'} %"]
    if tipo == "disposiciones":
        return [f"Llamadas dispuestas: {datos['total']}", f"Callbacks cumplidos: {datos['callbacks']['hechos']} de {datos['callbacks']['total']}"]
    return [f"Días con abandono sobre el objetivo: {datos['abandono_incumplido']}",
            f"Llamadas fuera de horario: {datos['fuera_de_horario_total']}",
            f"Números con más contactos por semana que el tope: {datos['contactos_semana_total']}"]


async def armar(session, rep: ReporteProgramado, p: Periodo, empresa: str) -> tuple[str, str, list[tuple[str, str]]]:
    rango = reportes.rango_utc(p.desde, p.hasta)
    filtros = rep.filtros or {}
    datos = await reportes.generar(session, rep.tipo, rango, **filtros)
    sufijo = f"{p.desde.isoformat()}_{p.hasta.isoformat()}"
    if rep.tipo == "cumplimiento":
        adjuntos = [(f"cumplimiento-{s}_{sufijo}.csv", reportes.csv_de("cumplimiento", datos, s))
                    for s in ("abandono", "contactos_semana", "fuera_de_horario")]
    else:
        adjuntos = [(f"{rep.tipo}_{sufijo}.csv", reportes.csv_de(rep.tipo, datos))]
    rango_txt = p.desde.isoformat() if p.desde == p.hasta else f"{p.desde.isoformat()} a {p.hasta.isoformat()}"
    asunto = f"[{empresa}] {rep.nombre} — {NOMBRES.get(rep.tipo, rep.tipo)} {rango_txt}"
    cuerpo = "\n".join([
        f"{rep.nombre} ({NOMBRES.get(rep.tipo, rep.tipo)}), {rango_txt}.",
        "",
        *_resumen(rep.tipo, datos),
        "",
        "El detalle va en el CSV adjunto (se abre con Excel).",
        "Para dejar de recibirlo, desactívalo en NSPBX → Reportes → Programados.",
    ])
    return asunto, cuerpo, adjuntos


async def enviar(tenant_id: int, reporte_id: int, forzar: bool = False) -> str | None:
    """Envía si le toca (o ya, con `forzar`: el último período cerrado).
    Devuelve el período enviado, o None si no tocaba. Lanza si falló."""
    ahora_utc, ahora_local = datetime.utcnow(), now_local()
    async with sesion_de_empresa(tenant_id) as session:
        rep = await session.get(ReporteProgramado, reporte_id, with_for_update={"skip_locked": True})
        if rep is None:
            return None
        p = periodo(rep.frecuencia, ahora_local.date()) if forzar else toca(rep, ahora_local, ahora_utc)
        if p is None:
            return None
        empresa = await session.get(Tenant, tenant_id)
        rep.ultimo_intento_at = ahora_utc
        try:
            asunto, cuerpo, adjuntos = await armar(session, rep, p, empresa.name if empresa else "NSPBX")
            await enviar_correo(leer_destinatarios(rep.destinatarios), asunto, cuerpo, adjuntos)
        except Exception as exc:
            rep.ultimo_error = f"{type(exc).__name__}: {exc}"[:500]
            await session.commit()
            raise
        rep.ultimo_error = None
        rep.ultimo_envio_at = ahora_utc
        # También al forzar: así la vuelta automática no repite ese período.
        rep.ultimo_periodo = p.etiqueta
        await session.commit()
        return p.etiqueta


class Programador:
    def __init__(self):
        self._tarea: asyncio.Task | None = None

    def start(self) -> None:
        if self._tarea is None or self._tarea.done():
            self._tarea = asyncio.create_task(self._bucle())

    async def stop(self) -> None:
        if self._tarea:
            self._tarea.cancel()
            try:
                await self._tarea
            except asyncio.CancelledError:
                pass

    async def _bucle(self) -> None:
        while True:
            try:
                await self.ciclo()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error en los reportes programados")
            await asyncio.sleep(60)

    async def ciclo(self) -> int:
        if not correo_configurado():
            return 0
        async with async_session() as dueno:
            activos = (
                await dueno.execute(select(ReporteProgramado.tenant_id, ReporteProgramado.id).where(ReporteProgramado.activo.is_(True)))
            ).all()
        enviados = 0
        for tenant_id, rid in activos:
            try:
                if await enviar(tenant_id, rid):
                    enviados += 1
            except Exception as exc:
                logger.warning("Reporte programado %s no salió: %s", rid, exc)
        return enviados


programador = Programador()
