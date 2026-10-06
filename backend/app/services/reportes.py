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

from sqlalchemy import case, cast, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB

from app.core.clock import business_tz
from app.models import (
    CallLog,
    Callback,
    Campaign,
    CampaignNumber,
    CodigoPausa,
    Disposicion,
    EstadoAgente,
    Extension,
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
# Las sumas las hace la base (GROUP BY): con 200 agentes y una semana son
# medio millón de tramos, y cargarlos en Python tardaba 25 s (docs/escala.md).


def _segundos_en_rango(col_ini, col_fin, ini: datetime, fin: datetime):
    """Segundos del tramo [col_ini, col_fin) dentro de [ini, fin); un tramo
    abierto (fin NULL) cuenta hasta `fin` (que nunca pasa de ahora)."""
    return func.extract("epoch", func.least(func.coalesce(col_fin, fin), fin) - func.greatest(col_ini, ini))


async def agentes(session, r: Rango, campaign_id: int | None = None, user_id: int | None = None) -> dict:
    ahora = datetime.utcnow()
    fin = min(r.fin, ahora)
    filtro_ses = [SesionAgente.inicio < fin, or_(SesionAgente.fin.is_(None), SesionAgente.fin > r.ini)]
    if user_id:
        filtro_ses.append(SesionAgente.user_id == user_id)
    if campaign_id:
        filtro_ses.append(cast(SesionAgente.campanas, JSONB).contains([campaign_id]))
    sesiones = select(SesionAgente.id).where(*filtro_ses)
    filtro_tramo = [
        EstadoAgente.sesion_id.in_(sesiones),
        EstadoAgente.inicio < fin,
        or_(EstadoAgente.fin.is_(None), EstadoAgente.fin > r.ini),
    ]
    dur = _segundos_en_rango(EstadoAgente.inicio, EstadoAgente.fin, r.ini, fin)

    login = (
        await session.execute(
            select(SesionAgente.user_id, func.count(), func.sum(_segundos_en_rango(SesionAgente.inicio, SesionAgente.fin, r.ini, fin)))
            .where(*filtro_ses)
            .group_by(SesionAgente.user_id)
        )
    ).all()
    por_estado = (
        await session.execute(select(EstadoAgente.user_id, EstadoAgente.estado, func.sum(dur)).where(*filtro_tramo).group_by(EstadoAgente.user_id, EstadoAgente.estado))
    ).all()
    por_pausa = (
        await session.execute(
            select(EstadoAgente.user_id, EstadoAgente.codigo_pausa_id, func.count(), func.sum(dur))
            .where(*filtro_tramo, EstadoAgente.estado == "PAUSA")
            .group_by(EstadoAgente.user_id, EstadoAgente.codigo_pausa_id)
        )
    ).all()
    # Llamadas: las que EMPEZARON en el rango (una por uuid).
    llamadas = dict(
        (
            await session.execute(
                select(EstadoAgente.user_id, func.count(func.distinct(func.coalesce(EstadoAgente.call_uuid, func.concat("tramo-", EstadoAgente.id)))))
                .where(EstadoAgente.sesion_id.in_(sesiones), EstadoAgente.estado == "EN_LLAMADA",
                       EstadoAgente.inicio >= r.ini, EstadoAgente.inicio < r.fin)
                .group_by(EstadoAgente.user_id)
            )
        ).all()
    )
    pausas = {p.id: p for p in (await session.execute(select(CodigoPausa))).scalars()}
    uids = {u for u, *_ in login} | {u for u, *_ in por_estado}
    nombres = await _nombres(session, uids)

    por: dict[int, dict] = {
        uid: {"user_id": uid, "nombre": nombres.get(uid, f"#{uid}"), "sesiones": 0, "login_s": 0.0,
              **{f"{e.lower()}_s": 0.0 for e in ESTADOS}, "llamadas": llamadas.get(uid, 0), "pausas": []}
        for uid in uids
    }
    for uid, n, total in login:
        por[uid]["sesiones"] = n
        por[uid]["login_s"] = float(total or 0)
    for uid, estado, total in por_estado:
        clave = f"{estado.lower()}_s"
        if clave in por[uid]:
            por[uid][clave] = float(total or 0)
    for uid, cid, n, total in sorted(por_pausa, key=lambda x: -float(x[3] or 0)):
        total = float(total or 0)
        por[uid]["pausas"].append({"codigo_pausa_id": cid, "nombre": pausas[cid].nombre if cid in pausas else "Sin código",
                                   "veces": n, "total_s": round(total), "promedio_s": _promedio(total, n)})

    filas = []
    for f in por.values():
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


def _en_rango(r: Rango, campaign_id: int | None = None) -> list:
    filtro = [CallLog.campaign_id.is_not(None), CallLog.started_at >= r.ini, CallLog.started_at < r.fin]
    if campaign_id:
        filtro.append(CallLog.campaign_id == campaign_id)
    return filtro


def _cuenta(cond):
    return func.coalesce(func.sum(case((cond, 1), else_=0)), 0)


async def campanas(session, r: Rango, campaign_id: int | None = None) -> dict:
    contestada = CallLog.status == "answered"
    filas_sql = (
        await session.execute(
            select(
                CallLog.campaign_id,
                func.count(),
                _cuenta(contestada),
                _cuenta(CallLog.abandonada.is_(True)),
                _cuenta(CallLog.status == "busy"),
                _cuenta(CallLog.status == "no_answer"),
                func.coalesce(func.sum(case((contestada, CallLog.billsec), else_=0)), 0),
                func.avg(CallLog.ring_ms),
                _cuenta(Disposicion.contacto_humano.is_(True)),
                _cuenta(Disposicion.categoria == "venta"),
                _cuenta(Disposicion.categoria == "promesa"),
                _cuenta(Disposicion.id.is_not(None)),
            )
            .outerjoin(Disposicion, Disposicion.id == CallLog.disposicion_id)
            .where(*_en_rango(r, campaign_id))
            .group_by(CallLog.campaign_id)
        )
    ).all()
    nombres = dict((await session.execute(select(Campaign.id, Campaign.name))).all())
    metodos = dict((await session.execute(select(Campaign.id, Campaign.metodo))).all())
    filas = []
    for cid, n, cont, aband, ocup, noc, hablado, ring, contactos, ventas, promesas, dispuestas in filas_sql:
        humanas = cont - aband
        filas.append({
            "campaign_id": cid, "nombre": nombres.get(cid, f"#{cid}"), "metodo": metodos.get(cid),
            "intentos": n, "contestadas": cont, "abandonadas": aband, "ocupado": ocup, "no_contesta": noc,
            "fallidas": n - cont - ocup - noc, "hablado_s": int(hablado), "contactos": contactos, "ventas": ventas,
            "promesas": promesas, "dispuestas": dispuestas,
            "contacto_pct": _pct(cont, n),
            "abandono_pct": _pct(aband, cont),
            "ring_promedio_s": round(float(ring) / 1000, 1) if ring is not None else None,
            "aht_s": _promedio(float(hablado), humanas),
            # Conversión: ventas y promesas sobre las conversaciones con una persona.
            "conversion_pct": _pct(ventas + promesas, contactos),
        })
    filas.sort(key=lambda f: f["nombre"].lower())
    total = {k: sum(f[k] for f in filas) for k in ("intentos", "contestadas", "abandonadas", "ocupado", "no_contesta", "fallidas", "contactos", "ventas", "promesas")}
    total.update(contacto_pct=_pct(total["contestadas"], total["intentos"]), abandono_pct=_pct(total["abandonadas"], total["contestadas"]),
                 conversion_pct=_pct(total["ventas"] + total["promesas"], total["contactos"]))
    return {"filas": filas, "total": total}


# --- Entrantes (grupos de atención) ------------------------------------------------------------
# Del CDR de cada llamada que pasó por un grupo (api/calls.py:datos_de_cola).
# Nivel de servicio: atendidas dentro de `umbral_s` sobre las ofrecidas,
# sin contar los abandonos de menos de ABANDONO_CORTO_S (colgó al instante:
# número equivocado, no es algo que el grupo pudiera atender).

ABANDONO_CORTO_S = 5


async def entrantes(session, r: Rango, umbral_s: int = 20, cola: str | None = None) -> dict:
    umbral_s = max(1, min(int(umbral_s or 20), 600))
    filtro = [CallLog.cola.is_not(None), CallLog.started_at >= r.ini, CallLog.started_at < r.fin]
    if cola:
        filtro.append(CallLog.cola == cola)
    atendida = CallLog.cola_resultado == "atendida"
    abandonada = CallLog.cola_resultado == "abandonada"
    espera = func.coalesce(CallLog.cola_espera_s, 0)
    medidas = (
        func.count(),
        _cuenta(atendida),
        _cuenta(atendida & (espera <= umbral_s)),
        _cuenta(abandonada),
        _cuenta(abandonada & (espera < ABANDONO_CORTO_S)),
        _cuenta(CallLog.cola_resultado == "desbordada"),
        func.coalesce(func.sum(case((atendida, espera), else_=0)), 0),
        func.max(espera),
        func.coalesce(func.sum(case((abandonada, espera), else_=0)), 0),
        func.coalesce(func.sum(case((atendida, CallLog.billsec), else_=0)), 0),
    )

    def fila(ofrecidas, atendidas, en_umbral, aband, aband_corto, desbordadas, espera_atendidas, espera_max, espera_aband, hablado):
        base_sl = ofrecidas - aband_corto
        return {
            "ofrecidas": ofrecidas, "atendidas": atendidas, "abandonadas": aband, "desbordadas": desbordadas,
            "atendidas_en_umbral": en_umbral,
            "nivel_servicio_pct": _pct(en_umbral, base_sl),
            "atencion_pct": _pct(atendidas, ofrecidas),
            "abandono_pct": _pct(aband, ofrecidas),
            "espera_promedio_s": _promedio(float(espera_atendidas), atendidas),
            "espera_max_s": int(espera_max or 0),
            "espera_abandono_s": _promedio(float(espera_aband), aband),
            "conversacion_promedio_s": _promedio(float(hablado), atendidas),
        }

    por_cola = (await session.execute(select(CallLog.cola, *medidas).where(*filtro).group_by(CallLog.cola))).all()
    filas = [{"cola": c, **fila(*m)} for c, *m in por_cola]
    filas.sort(key=lambda f: f["cola"].lower())
    total_sql = (await session.execute(select(*medidas).where(*filtro))).one()
    total = fila(*total_sql)

    hora = func.extract("hour", func.timezone(business_tz().key, func.timezone("UTC", CallLog.started_at)))
    por_hora_sql = (
        await session.execute(
            select(hora, func.count(), _cuenta(atendida), _cuenta(abandonada), _cuenta(atendida & (espera <= umbral_s)))
            .where(*filtro)
            .group_by(hora)
        )
    ).all()
    horas = {int(h): (n, a, ab, u) for h, n, a, ab, u in por_hora_sql}
    por_hora = [
        {"hora": h, "ofrecidas": horas.get(h, (0, 0, 0, 0))[0], "atendidas": horas.get(h, (0, 0, 0, 0))[1],
         "abandonadas": horas.get(h, (0, 0, 0, 0))[2],
         "nivel_servicio_pct": _pct(horas[h][3], horas[h][0]) if h in horas else None}
        for h in range(24)
    ]

    por_agente_sql = (
        await session.execute(
            select(CallLog.cola_agente, func.count(), func.sum(espera), func.sum(CallLog.billsec))
            .where(*filtro, atendida, CallLog.cola_agente.is_not(None))
            .group_by(CallLog.cola_agente)
        )
    ).all()
    nombres = dict(
        (await session.execute(select(Extension.number, Extension.caller_id_name).where(
            Extension.number.in_([a for a, *_ in por_agente_sql] or ["-"])
        ))).all()
    )
    por_agente = sorted(
        (
            {"extension": a, "nombre": nombres.get(a) or a, "atendidas": n,
             "espera_promedio_s": _promedio(float(e or 0), n), "conversacion_promedio_s": _promedio(float(h or 0), n)}
            for a, n, e, h in por_agente_sql
        ),
        key=lambda f: -f["atendidas"],
    )
    return {"umbral_s": umbral_s, "filas": filas, "total": total, "por_hora": por_hora, "por_agente": por_agente}


# --- Disposiciones -----------------------------------------------------------------------------

AGRUPAR = ("campana", "agente", "lista")


async def disposiciones(session, r: Rango, agrupar: str = "campana", campaign_id: int | None = None) -> dict:
    if agrupar not in AGRUPAR:
        raise RangoInvalido("Agrupación inválida")
    q = select(CallLog.disposicion_id, func.count())
    if agrupar == "campana":
        grupo = CallLog.campaign_id
        nombres = dict((await session.execute(select(Campaign.id, Campaign.name))).all())
    elif agrupar == "agente":
        grupo = CallLog.agente_id
        nombres = None
    else:
        grupo = CampaignNumber.lista_id
        q = q.outerjoin(CampaignNumber, CampaignNumber.id == CallLog.lead_id)
        nombres = dict((await session.execute(select(Lista.id, Lista.nombre))).all())
    cuenta = (
        await session.execute(
            q.add_columns(grupo).where(*_en_rango(r, campaign_id), CallLog.disposicion_id.is_not(None)).group_by(grupo, CallLog.disposicion_id)
        )
    ).all()
    if nombres is None:
        nombres = await _nombres(session, [g for _, _, g in cuenta])
    disps = {d.id: d for d in (await session.execute(select(Disposicion))).scalars()}
    por_grupo: dict = defaultdict(int)
    for _, n, g in cuenta:
        por_grupo[g] += n
    filas = []
    for did, n, g in sorted(cuenta, key=lambda x: (str(nombres.get(x[2], "")), -x[1])):
        d = disps.get(did)
        filas.append({
            "grupo_id": g, "grupo": nombres.get(g, "Sin asignar" if g is None else f"#{g}"),
            "disposicion_id": did, "disposicion": d.nombre if d else f"#{did}", "codigo": d.codigo if d else None,
            "categoria": d.categoria if d else None, "cantidad": n, "pct": _pct(n, por_grupo[g]),
        })
    # Callbacks del rango: cuántos se cumplieron y cuántos quedaron vencidos.
    ahora = datetime.utcnow()
    q_cb = select(Callback.estado, func.count(), _cuenta(Callback.cuando < ahora)).where(Callback.cuando >= r.ini, Callback.cuando < r.fin)
    if campaign_id:
        q_cb = q_cb.where(Callback.campaign_id == campaign_id)
    cbs = {e: (n, vencidos) for e, n, vencidos in (await session.execute(q_cb.group_by(Callback.estado))).all()}
    callbacks = {
        "total": sum(n for n, _ in cbs.values()),
        "hechos": cbs.get("hecho", (0, 0))[0],
        "vencidos": cbs.get("pendiente", (0, 0))[1],
        "cancelados": cbs.get("cancelado", (0, 0))[0],
    }
    return {"filas": filas, "total": sum(por_grupo.values()), "callbacks": callbacks}


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

    # 2. Llamadas de campaña fuera del horario permitido (debería ser 0). Solo
    # las columnas necesarias, y la franja se calcula una vez por día e intención.
    ajustes = (await session.execute(select(SystemSettings).limit(1))).scalar_one_or_none()
    salientes_q = (
        await session.execute(
            select(CallLog.campaign_id, CallLog.started_at, CallLog.callee_number, CallLog.agente_id)
            .where(*_en_rango(r), CallLog.direction == "outbound")
            .order_by(CallLog.started_at)
        )
    ).all()
    franjas: dict[tuple, tuple | None] = {}
    fuera = []
    for cid, inicio, tel, agente in salientes_q:
        camp = campanas_.get(cid)
        intencion = camp.ai_intent if camp else None
        local = a_local(inicio)
        clave = (intencion, local.date())
        if clave not in franjas:
            franjas[clave] = horario_marcacion.franja(ajustes, intencion, local.date())
        f = franjas[clave]
        if f is None or not (f[0] <= local.time() < f[1]):
            fuera.append({"fecha": local.isoformat(timespec="seconds"), "campana": camp.name if camp else None,
                          "telefono": tel, "agente_id": agente})

    # 3. Contactos por persona por semana (Ley 2300 en cobranza): llamadas
    # CONTESTADAS a un mismo número en la misma semana (lunes a domingo, hora
    # local). Lo agrupa la base.
    zona = str(business_tz())
    semana = func.date_trunc("week", func.timezone(zona, func.timezone("UTC", CallLog.started_at)))
    clave_tel = crm.clave_sql(CallLog.callee_number)
    contestadas = _cuenta(CallLog.status == "answered")
    q = (
        select(clave_tel, semana, func.count(), contestadas, func.array_agg(func.distinct(Campaign.name)))
        .join(Campaign, Campaign.id == CallLog.campaign_id)
        .where(*_en_rango(r), CallLog.direction == "outbound", clave_tel != "")
        .group_by(clave_tel, semana)
        .having(contestadas > max_contactos_semana)
    )
    if solo_cobranza:
        q = q.where(Campaign.ai_intent == "cobranza")
    excesos = []
    for tel, lunes, n, cont, nombres_camp in (await session.execute(q)).all():
        anio, sem, _ = lunes.date().isocalendar()
        excesos.append({"telefono": tel, "semana": f"{anio}-S{sem:02d}", "intentos": n, "contestadas": cont,
                        "campanas": sorted(x for x in (nombres_camp or []) if x)})
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
    "entrantes": [
        ("cola", "Grupo"), ("ofrecidas", "Ofrecidas"), ("atendidas", "Atendidas"), ("abandonadas", "Abandonadas"),
        ("desbordadas", "Desbordadas"), ("nivel_servicio_pct", "Nivel de servicio %"), ("atencion_pct", "Atención %"),
        ("abandono_pct", "Abandono %"), ("espera_promedio_s", "Espera media (s)"), ("espera_max_s", "Espera máxima (s)"),
        ("espera_abandono_s", "Espera antes de colgar (s)"), ("conversacion_promedio_s", "Conversación media (s)"),
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
    if tipo == "entrantes":
        return await entrantes(session, r, filtros.get("umbral_s") or 20, filtros.get("cola"))
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


TIPOS = ("agentes", "campanas", "disposiciones", "cumplimiento", "entrantes")

