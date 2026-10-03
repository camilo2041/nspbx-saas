"""Reportes del contact center (docs/plan-contact-center.md, §8 y fase 6).

Todo sale de tres fuentes y de ninguna otra, para que las cifras cuadren:

- `estados_agente` y `sesiones_agente`: el tiempo de cada agente. Los tramos
  se cortan al rango pedido (un tramo que empezó ayer y siguió hoy cuenta
  solo su parte de hoy) y un tramo abierto cuenta hasta ahora. Como los
  tramos de una sesión no dejan huecos, la suma de los estados es el
  tiempo conectado.
- `call_logs`: las llamadas (el CDR de FreeSWITCH), con su campaña, agente,
  disposición y si fue abandonada.
- `metricas_campana`: el abandono del día que lleva el motor predictivo, la
  cifra oficial de cumplimiento.

Las fechas del filtro son días LOCALES del negocio; en la base todo está en
UTC (naive). `rango_utc` hace la conversión en un solo lugar.
"""

import csv
import io
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.core.clock import business_tz
from app.models import (
    CallLog,
    Callback,
    Campaign,
    CampaignNumber,
    CodigoPausa,
    Disposicion,
    EstadoAgente,
    Lista,
    MetricaCampana,
    SesionAgente,
    SystemSettings,
    User,
)
from app.services import crm, horario_marcacion

MAX_DIAS = 366
ESTADOS = ("LISTO", "PAUSA", "PREVIA", "TIMBRANDO", "EN_LLAMADA", "DISPO")
_UTC = ZoneInfo("UTC")


class RangoInvalido(ValueError):
    pass


@dataclass
class Rango:
    desde: date
    hasta: date
    ini: datetime  # UTC naive, incluido
    fin: datetime  # UTC naive, excluido


def rango_utc(desde: date, hasta: date) -> Rango:
    if hasta < desde:
        raise RangoInvalido("La fecha final es anterior a la inicial")
    if (hasta - desde).days >= MAX_DIAS:
        raise RangoInvalido(f"El rango máximo es de {MAX_DIAS} días")
    tz = business_tz()

    def utc(d: date) -> datetime:
        return datetime.combine(d, time.min, tzinfo=tz).astimezone(_UTC).replace(tzinfo=None)

    return Rango(desde, hasta, utc(desde), utc(hasta + timedelta(days=1)))


def a_local(dt: datetime) -> datetime:
    return dt.replace(tzinfo=_UTC).astimezone(business_tz()).replace(tzinfo=None)


def _solape(ini: datetime, fin: datetime | None, r: Rango, ahora: datetime) -> float:
    a = max(ini, r.ini)
    b = min(fin or ahora, r.fin, ahora)
    return max(0.0, (b - a).total_seconds())


def _pct(parte: float, total: float) -> float | None:
    return round(100.0 * parte / total, 1) if total else None


def _promedio(total: float, n: int) -> float | None:
    return round(total / n, 1) if n else None


async def _nombres(session, ids) -> dict[int, str]:
    ids = [i for i in set(ids) if i]
    if not ids:
        return {}
    return {u.id: u.full_name or u.username for u in (await session.execute(select(User).where(User.id.in_(ids)))).unique().scalars()}


# --- Agentes ------------------------------------------------------------------------------


async def agentes(session, r: Rango, campaign_id: int | None = None, user_id: int | None = None) -> dict:
    ahora = datetime.utcnow()
    q_ses = select(SesionAgente).where(SesionAgente.inicio < r.fin, (SesionAgente.fin.is_(None)) | (SesionAgente.fin > r.ini))
    if user_id:
        q_ses = q_ses.where(SesionAgente.user_id == user_id)
    sesiones = [s for s in (await session.execute(q_ses)).scalars() if not campaign_id or campaign_id in (s.campanas or [])]
    ids_sesion = [s.id for s in sesiones]
    tramos = (
        (await session.execute(select(EstadoAgente).where(EstadoAgente.sesion_id.in_(ids_sesion), EstadoAgente.inicio < r.fin)))
        .scalars()
        .all()
        if ids_sesion
        else []
    )
    pausas = {p.id: p for p in (await session.execute(select(CodigoPausa))).scalars()}
    nombres = await _nombres(session, [s.user_id for s in sesiones])

    por: dict[int, dict] = {}

    def fila(uid: int) -> dict:
        if uid not in por:
            por[uid] = {"user_id": uid, "nombre": nombres.get(uid, f"#{uid}"), "sesiones": 0, "login_s": 0.0,
                        **{f"{e.lower()}_s": 0.0 for e in ESTADOS}, "llamadas": 0, "_pausas": defaultdict(lambda: [0, 0.0]),
                        "_llamadas": set()}
        return por[uid]

    for s in sesiones:
        f = fila(s.user_id)
        f["sesiones"] += 1
        f["login_s"] += _solape(s.inicio, s.fin, r, ahora)
    for t in tramos:
        dur = _solape(t.inicio, t.fin, r, ahora)
        if dur <= 0 and not (t.estado == "EN_LLAMADA" and r.ini <= t.inicio < r.fin):
            continue
        f = fila(t.user_id)
        clave = f"{t.estado.lower()}_s"
        if clave in f:
            f[clave] += dur
        if t.estado == "PAUSA":
            p = f["_pausas"][t.codigo_pausa_id]
            p[0] += 1
            p[1] += dur
        if t.estado == "EN_LLAMADA" and r.ini <= t.inicio < r.fin:
            f["_llamadas"].add(t.call_uuid or f"tramo-{t.id}")

    filas = []
    for f in por.values():
        f["llamadas"] = len(f.pop("_llamadas"))
        detalle = f.pop("_pausas")
        f["pausas"] = [
            {"codigo_pausa_id": cid, "nombre": pausas[cid].nombre if cid in pausas else "Sin código", "veces": n,
             "total_s": round(total), "promedio_s": _promedio(total, n)}
            for cid, (n, total) in sorted(detalle.items(), key=lambda x: -x[1][1])
        ]
        trabajo = f["en_llamada_s"] + f["dispo_s"]
        f["aht_s"] = _promedio(trabajo, f["llamadas"])
        # Ocupación: del tiempo disponible (sin pausas), cuánto estuvo con
        # clientes. Utilización: lo mismo sobre todo el tiempo conectado.
        f["ocupacion_pct"] = _pct(trabajo, f["login_s"] - f["pausa_s"])
        f["utilizacion_pct"] = _pct(trabajo, f["login_s"])
        f["llamadas_hora"] = round(f["llamadas"] / (f["login_s"] / 3600), 1) if f["login_s"] >= 60 else None
        for k in [k for k in f if k.endswith("_s") and isinstance(f[k], float)]:
            f[k] = round(f[k])
        filas.append(f)
    filas.sort(key=lambda f: f["nombre"].lower())
    total = {k: sum(f[k] for f in filas) for k in ("login_s", "llamadas", *[f"{e.lower()}_s" for e in ESTADOS])}
    trabajo = total["en_llamada_s"] + total["dispo_s"]
    total.update(
        aht_s=_promedio(trabajo, total["llamadas"]),
        ocupacion_pct=_pct(trabajo, total["login_s"] - total["pausa_s"]),
        utilizacion_pct=_pct(trabajo, total["login_s"]),
    )
    return {"filas": filas, "total": total}


# --- Campañas ---------------------------------------------------------------------------------


def _llamadas_en(r: Rango, campaign_id: int | None = None):
    q = select(CallLog).where(CallLog.campaign_id.is_not(None), CallLog.started_at >= r.ini, CallLog.started_at < r.fin)
    if campaign_id:
        q = q.where(CallLog.campaign_id == campaign_id)
    return q


async def campanas(session, r: Rango, campaign_id: int | None = None) -> dict:
    llamadas = (await session.execute(_llamadas_en(r, campaign_id))).scalars().all()
    disps = {d.id: d for d in (await session.execute(select(Disposicion))).scalars()}
    nombres = dict((await session.execute(select(Campaign.id, Campaign.name))).all())
    metodos = dict((await session.execute(select(Campaign.id, Campaign.metodo))).all())
    por: dict[int, dict] = {}
    for c in llamadas:
        f = por.setdefault(c.campaign_id, {
            "campaign_id": c.campaign_id, "nombre": nombres.get(c.campaign_id, f"#{c.campaign_id}"),
            "metodo": metodos.get(c.campaign_id), "intentos": 0, "contestadas": 0, "abandonadas": 0, "ocupado": 0,
            "no_contesta": 0, "fallidas": 0, "hablado_s": 0, "_ring": [], "contactos": 0, "ventas": 0, "promesas": 0,
            "dispuestas": 0,
        })
        f["intentos"] += 1
        if c.status == "answered":
            f["contestadas"] += 1
            f["hablado_s"] += c.billsec or 0
        elif c.status == "busy":
            f["ocupado"] += 1
        elif c.status == "no_answer":
            f["no_contesta"] += 1
        else:
            f["fallidas"] += 1
        if c.abandonada:
            f["abandonadas"] += 1
        if c.ring_ms is not None:
            f["_ring"].append(c.ring_ms)
        d = disps.get(c.disposicion_id) if c.disposicion_id else None
        if d is not None:
            f["dispuestas"] += 1
            if d.contacto_humano:
                f["contactos"] += 1
            if d.categoria == "venta":
                f["ventas"] += 1
            elif d.categoria == "promesa":
                f["promesas"] += 1
    filas = []
    for f in por.values():
        ring = f.pop("_ring")
        humanas = f["contestadas"] - f["abandonadas"]
        f.update(
            contacto_pct=_pct(f["contestadas"], f["intentos"]),
            abandono_pct=_pct(f["abandonadas"], f["contestadas"]),
            ring_promedio_s=round(sum(ring) / len(ring) / 1000, 1) if ring else None,
            aht_s=_promedio(f["hablado_s"], humanas),
            # Conversión: ventas y promesas sobre las conversaciones con una persona.
            conversion_pct=_pct(f["ventas"] + f["promesas"], f["contactos"]),
        )
        filas.append(f)
    filas.sort(key=lambda f: f["nombre"].lower())
    total = {k: sum(f[k] for f in filas) for k in ("intentos", "contestadas", "abandonadas", "ocupado", "no_contesta", "fallidas", "contactos", "ventas", "promesas")}
    total.update(contacto_pct=_pct(total["contestadas"], total["intentos"]), abandono_pct=_pct(total["abandonadas"], total["contestadas"]),
                 conversion_pct=_pct(total["ventas"] + total["promesas"], total["contactos"]))
    return {"filas": filas, "total": total}


# --- Disposiciones -----------------------------------------------------------------------------

AGRUPAR = ("campana", "agente", "lista")


async def disposiciones(session, r: Rango, agrupar: str = "campana", campaign_id: int | None = None) -> dict:
    if agrupar not in AGRUPAR:
        raise RangoInvalido("Agrupación inválida")
    q = _llamadas_en(r, campaign_id).where(CallLog.disposicion_id.is_not(None))
    llamadas = (await session.execute(q)).scalars().all()
    disps = {d.id: d for d in (await session.execute(select(Disposicion))).scalars()}
    if agrupar == "campana":
        nombres = dict((await session.execute(select(Campaign.id, Campaign.name))).all())
        grupo = {c.id: c.campaign_id for c in llamadas}
    elif agrupar == "agente":
        nombres = await _nombres(session, [c.agente_id for c in llamadas])
        grupo = {c.id: c.agente_id for c in llamadas}
    else:
        leads = [c.lead_id for c in llamadas if c.lead_id]
        lista_de = dict((await session.execute(select(CampaignNumber.id, CampaignNumber.lista_id).where(CampaignNumber.id.in_(leads or [0])))).all())
        nombres = dict((await session.execute(select(Lista.id, Lista.nombre))).all())
        grupo = {c.id: lista_de.get(c.lead_id) for c in llamadas}
    cuenta: dict[tuple, int] = defaultdict(int)
    por_grupo: dict = defaultdict(int)
    for c in llamadas:
        g = grupo[c.id]
        cuenta[(g, c.disposicion_id)] += 1
        por_grupo[g] += 1
    filas = []
    for (g, did), n in sorted(cuenta.items(), key=lambda x: (str(nombres.get(x[0][0], "")), -x[1])):
        d = disps.get(did)
        filas.append({
            "grupo_id": g, "grupo": nombres.get(g, "Sin asignar" if g is None else f"#{g}"),
            "disposicion_id": did, "disposicion": d.nombre if d else f"#{did}", "codigo": d.codigo if d else None,
            "categoria": d.categoria if d else None, "cantidad": n, "pct": _pct(n, por_grupo[g]),
        })
    # Callbacks del rango: cuántos se cumplieron y cuántos quedaron vencidos.
    ahora = datetime.utcnow()
    cbs = (await session.execute(select(Callback).where(Callback.cuando >= r.ini, Callback.cuando < r.fin))).scalars().all()
    if campaign_id:
        cbs = [c for c in cbs if c.campaign_id == campaign_id]
    callbacks = {
        "total": len(cbs),
        "hechos": sum(1 for c in cbs if c.estado == "hecho"),
        "vencidos": sum(1 for c in cbs if c.estado == "pendiente" and c.cuando < ahora),
        "cancelados": sum(1 for c in cbs if c.estado == "cancelado"),
    }
    return {"filas": filas, "total": len(llamadas), "callbacks": callbacks}


# --- Cumplimiento --------------------------------------------------------------------------------


async def cumplimiento(session, r: Rango, max_contactos_semana: int = 1, solo_cobranza: bool = True) -> dict:
    campanas_ = {c.id: c for c in (await session.execute(select(Campaign))).scalars()}
    # 1. Abandono por día y campaña (cifra del motor) frente al objetivo.
    metricas = (
        await session.execute(
            select(MetricaCampana).where(MetricaCampana.fecha >= r.desde, MetricaCampana.fecha <= r.hasta).order_by(MetricaCampana.fecha)
        )
    ).scalars().all()
    abandono = []
    for m in metricas:
        c = campanas_.get(m.campaign_id)
        objetivo = c.abandono_objetivo if c else 3.0
        pct = _pct(m.abandonadas, m.contestadas)
        abandono.append({
            "fecha": m.fecha.isoformat(), "campaign_id": m.campaign_id, "campana": c.name if c else f"#{m.campaign_id}",
            "contestadas": m.contestadas, "abandonadas": m.abandonadas, "abandono_pct": pct, "objetivo_pct": objetivo,
            "cumple": pct is None or pct <= objetivo,
        })

    # 2. Llamadas de campaña fuera del horario permitido (debería ser 0).
    ajustes = (await session.execute(select(SystemSettings).limit(1))).scalar_one_or_none()
    llamadas = (await session.execute(_llamadas_en(r).where(CallLog.direction == "outbound"))).scalars().all()
    fuera = []
    for c in llamadas:
        camp = campanas_.get(c.campaign_id)
        local = a_local(c.started_at)
        if not horario_marcacion.puede_marcar(ajustes, camp.ai_intent if camp else None, local):
            fuera.append({"fecha": local.isoformat(timespec="seconds"), "campana": camp.name if camp else None,
                          "telefono": c.callee_number, "agente_id": c.agente_id})

    # 3. Contactos por persona por semana (Ley 2300 en cobranza). Cuenta las
    # llamadas CONTESTADAS a un mismo número en la misma semana (lunes a domingo, hora local).
    por_semana: dict[tuple, list] = defaultdict(lambda: [0, 0, set()])
    for c in llamadas:
        camp = campanas_.get(c.campaign_id)
        if solo_cobranza and (not camp or camp.ai_intent != "cobranza"):
            continue
        clave = crm.clave_telefono(c.callee_number)
        if not clave:
            continue
        anio, semana, _ = a_local(c.started_at).isocalendar()
        fila = por_semana[(clave, anio, semana)]
        fila[0] += 1
        if c.status == "answered":
            fila[1] += 1
        if camp:
            fila[2].add(camp.name)
    excesos = [
        {"telefono": tel, "semana": f"{anio}-S{semana:02d}", "intentos": n, "contestadas": cont, "campanas": sorted(nom)}
        for (tel, anio, semana), (n, cont, nom) in por_semana.items()
        if cont > max_contactos_semana
    ]
    excesos.sort(key=lambda x: (-x["contestadas"], x["semana"]))
    return {
        "abandono": abandono,
        "abandono_incumplido": sum(1 for a in abandono if not a["cumple"]),
        "fuera_de_horario": fuera[:500],
        "fuera_de_horario_total": len(fuera),
        "contactos_semana": excesos[:500],
        "contactos_semana_total": len(excesos),
        "max_contactos_semana": max_contactos_semana,
        "solo_cobranza": solo_cobranza,
    }


# --- CSV ---------------------------------------------------------------------------------------------


_NUMERO = re.compile(r"[+-]?\d[\d,.]*")


def a_csv(filas: list[dict], columnas: list[tuple[str, str]]) -> str:
    """`columnas`: (clave, encabezado). Con BOM y `;` para que Excel en
    español lo abra bien con doble clic."""
    salida = io.StringIO()
    salida.write("\ufeff")
    w = csv.writer(salida, delimiter=";")
    w.writerow([titulo for _, titulo in columnas])
    for f in filas:
        fila = []
        for clave, _ in columnas:
            v = f.get(clave)
            if isinstance(v, list):
                v = ", ".join(str(x) for x in v)
            elif isinstance(v, float):
                v = str(v).replace(".", ",")
            elif isinstance(v, bool):
                v = "sí" if v else "no"
            texto = "" if v is None else str(v)
            # Inyección de fórmulas: una celda que empieza con = + - @ la
            # ejecutaría Excel.
            if texto[:1] in ("=", "+", "-", "@") and not _NUMERO.fullmatch(texto):
                texto = "'" + texto
            fila.append(texto)
        w.writerow(fila)
    return salida.getvalue()


COLUMNAS = {
    "agentes": [
        ("nombre", "Agente"), ("sesiones", "Sesiones"), ("login_s", "Conectado (s)"), ("listo_s", "Listo (s)"),
        ("pausa_s", "Pausa (s)"), ("previa_s", "Vista previa (s)"), ("timbrando_s", "Timbrando (s)"),
        ("en_llamada_s", "En llamada (s)"), ("dispo_s", "Disposición (s)"), ("llamadas", "Llamadas"), ("aht_s", "AHT (s)"),
        ("ocupacion_pct", "Ocupación %"), ("utilizacion_pct", "Utilización %"), ("llamadas_hora", "Llamadas/hora"),
    ],
    "campanas": [
        ("nombre", "Campaña"), ("metodo", "Método"), ("intentos", "Intentos"), ("contestadas", "Contestadas"),
        ("abandonadas", "Abandonadas"), ("ocupado", "Ocupado"), ("no_contesta", "No contesta"), ("fallidas", "Fallidas"),
        ("contacto_pct", "Contacto %"), ("abandono_pct", "Abandono %"), ("ring_promedio_s", "Ring medio (s)"),
        ("aht_s", "Conversación media (s)"), ("contactos", "Contactos humanos"), ("ventas", "Ventas"), ("promesas", "Promesas"),
        ("conversion_pct", "Conversión %"),
    ],
    "disposiciones": [
        ("grupo", "Grupo"), ("disposicion", "Disposición"), ("codigo", "Código"), ("categoria", "Categoría"),
        ("cantidad", "Cantidad"), ("pct", "% del grupo"),
    ],
    "cumplimiento": [
        ("fecha", "Fecha"), ("campana", "Campaña"), ("contestadas", "Contestadas"), ("abandonadas", "Abandonadas"),
        ("abandono_pct", "Abandono %"), ("objetivo_pct", "Objetivo %"), ("cumple", "Cumple"),
    ],
    "contactos_semana": [
        ("telefono", "Teléfono"), ("semana", "Semana"), ("intentos", "Intentos"), ("contestadas", "Contestadas"),
        ("campanas", "Campañas"),
    ],
    "fuera_de_horario": [("fecha", "Fecha"), ("campana", "Campaña"), ("telefono", "Teléfono"), ("agente_id", "Agente")],
}


async def generar(session, tipo: str, r: Rango, **filtros) -> dict:
    """Un solo punto de entrada (lo usan la API y los reportes programados)."""
    if tipo == "agentes":
        return await agentes(session, r, filtros.get("campaign_id"), filtros.get("user_id"))
    if tipo == "campanas":
        return await campanas(session, r, filtros.get("campaign_id"))
    if tipo == "disposiciones":
        return await disposiciones(session, r, filtros.get("agrupar") or "campana", filtros.get("campaign_id"))
    if tipo == "cumplimiento":
        return await cumplimiento(session, r, filtros.get("max_contactos_semana") or 1, filtros.get("solo_cobranza", True))
    raise RangoInvalido("Reporte desconocido")


def csv_de(tipo: str, datos: dict, seccion: str | None = None) -> str:
    if tipo == "cumplimiento":
        seccion = seccion or "abandono"
        clave = {"abandono": "cumplimiento", "contactos_semana": "contactos_semana", "fuera_de_horario": "fuera_de_horario"}.get(seccion)
        if clave is None:
            raise RangoInvalido("Sección inválida")
        return a_csv(datos[seccion], COLUMNAS[clave])
    return a_csv(datos["filas"], COLUMNAS[tipo])


TIPOS = ("agentes", "campanas", "disposiciones", "cumplimiento")

