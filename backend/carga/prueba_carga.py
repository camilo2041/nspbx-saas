"""Prueba de carga del contact center (fase 7, docs/escala.md).

Mide, contra una base de PRUEBA (nunca la de producción: siembra datos):

1. El motor predictivo con N agentes listos: cuánto tarda una vuelta (lanzar
   todas las llamadas que tocan) y en asignar los clientes que contestan a la
   vez, sin asignar dos al mismo agente.
2. Las pantallas en vivo del supervisor con N agentes conectados.
3. Los reportes con D días de historia (estados de agente y llamadas).

FreeSWITCH se simula (se cuentan los comandos): lo que se mide es el backend
y la base. La capacidad de FreeSWITCH y de la troncal se mide aparte
(scripts/medir-recursos.sh y una prueba en el ambiente local).

    cd backend
    DATABASE_URL=postgresql+asyncpg://…/nspbx_carga python -m carga.prueba_carga --agentes 200 --dias 7

La prueba liviana de CI (tests/test_carga.py) usa estas mismas funciones con
pocos agentes.
"""

import argparse
import asyncio
import json
import random
import statistics
import time
import uuid as uuidlib
from contextlib import contextmanager
from datetime import date, datetime, timedelta

from sqlalchemy import select

from app.core import permissions
from app.core.database import async_session, sesion_de_empresa
from app.core.security import hash_password
from app.models import (
    AgenteVivo,
    CampanaAgente,
    Campaign,
    CampaignNumber,
    Disposicion,
    Extension,
    License,
    SesionAgente,
    Tenant,
    Trunk,
    User,
)
from app.services import agentes, esl, predictivo, reportes, supervision
from app.services.ajustes import get_or_create_settings


@contextmanager
def freeswitch_simulado():
    """Reemplaza esl.api/bgapi por funciones que solo cuentan."""
    contador = {"bgapi": 0, "api": 0}
    originales = (esl.bgapi, esl.api)

    async def bgapi(cmd):
        contador["bgapi"] += 1
        return "+OK Job-UUID: x"

    async def api(cmd):
        contador["api"] += 1
        return "+OK"

    esl.bgapi, esl.api = bgapi, api
    try:
        yield contador
    finally:
        esl.bgapi, esl.api = originales


async def sembrar(n_agentes: int, n_leads: int) -> dict:
    """Una empresa con N agentes listos (con audio) en una campaña predictiva en curso."""
    sufijo = uuidlib.uuid4().hex[:6]
    async with async_session() as s:
        t = Tenant(name=f"Carga {sufijo}", slug=f"carga{sufijo}", sip_domain=f"c{sufijo}.test", modules="voicebot,pbx", enabled=True)
        s.add(t)
        await s.flush()
        s.add(License(tenant_id=t.id, plan="enterprise", status="active"))
        ajustes = await get_or_create_settings(s, t.id)
        ajustes.campaign_hours_weekdays = ajustes.campaign_hours_saturday = "00:00-24:00"
        ajustes.campaign_sundays_holidays = True
        troncal = Trunk(tenant_id=t.id, name="principal", gateway_host="sip.carga.test", register_enabled=False, caller_id_number="6015550000")
        s.add(troncal)
        await s.flush()
        camp = Campaign(tenant_id=t.id, name=f"pred-{sufijo}", trunk_id=troncal.id, status="running", metodo="predictivo",
                        retries=2, max_concurrency=n_agentes * 3, nivel_max=3.0)
        s.add(camp)
        await s.flush()
        clave = hash_password("clave-de-prueba")
        usuarios = []
        for i in range(n_agentes):
            ext = Extension(tenant_id=t.id, number=f"{2000 + i}", password="clave-sip-larga-1")
            s.add(ext)
            await s.flush()
            u = User(tenant_id=t.id, username=f"ag{i}-{t.slug}", full_name=f"Agente {i}", password_hash=clave,
                     role=permissions.ASESOR, extension_id=ext.id, enabled=True)
            s.add(u)
            await s.flush()
            s.add(CampanaAgente(tenant_id=t.id, campaign_id=camp.id, user_id=u.id))
            usuarios.append((u.id, ext.number))
        ahora = datetime.utcnow()
        for i, (uid, ext) in enumerate(usuarios):
            ses = SesionAgente(tenant_id=t.id, user_id=uid, campanas=[camp.id], extension=ext, inicio=ahora)
            s.add(ses)
            await s.flush()
            s.add(AgenteVivo(tenant_id=t.id, user_id=uid, sesion_id=ses.id, estado=agentes.LISTO, campanas=[camp.id],
                             extension=ext, audio=True, desde=ahora - timedelta(seconds=n_agentes - i)))
        s.add_all([CampaignNumber(tenant_id=t.id, campaign_id=camp.id, phone=f"300{i:07d}") for i in range(n_leads)])
        await s.commit()
        ctx = {"tenant": t.id, "camp": camp.id, "agentes": [u for u, _ in usuarios]}
    # Los catálogos con la sesión de la empresa: la del dueño ve los de todas
    # y creería que esta ya los tiene.
    async with sesion_de_empresa(ctx["tenant"]) as s:
        await agentes.asegurar_catalogos(s, ctx["tenant"])
        await s.commit()
    return ctx


async def limpiar(ctx: dict) -> None:
    async with async_session() as s:
        camp = await s.get(Campaign, ctx["camp"])
        if camp:
            camp.status = "paused"
        await s.execute(AgenteVivo.__table__.delete().where(AgenteVivo.tenant_id == ctx["tenant"]))
        await s.commit()


async def medir_motor(ctx: dict, contacto: float = 0.3) -> dict:
    """Una vuelta del predictivo con todos listos y, después, todos los que
    contestan a la vez, con la tasa de contacto dada en la ventana."""
    motor = predictivo.Motor()
    v = motor.ventana(ctx["camp"])
    ahora = motor.reloj()
    for i in range(200):
        v.resueltas.append(ahora)
        if i < int(200 * contacto):
            v.contestadas.append(ahora)
    with freeswitch_simulado() as fs:
        t0 = time.perf_counter()
        async with sesion_de_empresa(ctx["tenant"]) as s:
            lanzadas = await motor._campana(s, ctx["camp"])
            await s.commit()
        vuelta_s = time.perf_counter() - t0
        n = len(ctx["agentes"])
        contestan = list(motor.llamadas.values())[: n + n // 10]  # un 10 % más de contestadas que agentes
        # Como la fila de eventos de ESL: las contestadas se asignan en paralelo.
        t0 = time.perf_counter()
        for ll in contestan:
            await motor.recibir({"Event-Name": "CHANNEL_ANSWER", "Unique-ID": ll.uuid, "variable_nspbx_pred": "1",
                                 "variable_nspbx_tenant_id": str(ctx["tenant"])}, en_segundo_plano=True)
        while motor._tareas:
            await asyncio.wait(set(motor._tareas.values()))
        asignar_s = time.perf_counter() - t0
    async with sesion_de_empresa(ctx["tenant"]) as s:
        en_llamada = (await s.execute(select(AgenteVivo).where(AgenteVivo.estado == agentes.EN_LLAMADA))).scalars().all()
    uuids = [x.call_uuid for x in en_llamada]
    return {
        "agentes": n,
        "lanzadas": lanzadas,
        "originates": fs["bgapi"],
        "vuelta_s": round(vuelta_s, 3),
        "contestan": len(contestan),
        "asignadas": len([ll for ll in motor.llamadas.values() if ll.estado == "asignada"]),
        "en_espera": len([ll for ll in motor.llamadas.values() if ll.estado == "espera"]),
        "agentes_en_llamada": len(en_llamada),
        "agentes_con_dos_llamadas": len(uuids) - len(set(uuids)),
        "asignar_total_s": round(asignar_s, 3),
        "asignar_por_llamada_ms": round(1000 * asignar_s / max(1, len(contestan)), 2),
    }


async def medir_supervision(ctx: dict, repeticiones: int = 5) -> dict:
    tiempos: dict[str, list[float]] = {"agentes": [], "campanas": [], "resumen": []}
    vivos: list = []
    for _ in range(repeticiones):
        async with sesion_de_empresa(ctx["tenant"]) as s:
            t0 = time.perf_counter()
            vivos = await supervision.agentes_en_vivo(s)
            tiempos["agentes"].append(time.perf_counter() - t0)
            t0 = time.perf_counter()
            await supervision.campanas_en_vivo(s, vivos)
            tiempos["campanas"].append(time.perf_counter() - t0)
            t0 = time.perf_counter()
            await supervision.resumen(s, ctx["tenant"])
            tiempos["resumen"].append(time.perf_counter() - t0)
    return {k: round(statistics.median(v) * 1000, 1) for k, v in tiempos.items()} | {"agentes_conectados": len(vivos)}


async def sembrar_historia(ctx: dict, dias: int, llamadas_por_agente_dia: int, hasta: date) -> dict:
    """Jornadas por agente: tramos LISTO → TIMBRANDO → EN_LLAMADA → DISPO por
    llamada y el CDR de cada una. Con COPY (rápido)."""
    import asyncpg

    from app.services.lider import dsn

    rnd = random.Random(7)
    async with sesion_de_empresa(ctx["tenant"]) as s:
        disps = [d.id for d in (await s.execute(select(Disposicion))).scalars()]
    con = await asyncpg.connect(dsn())
    tramos, cdrs, sesiones = [], [], 0
    try:
        for d in range(dias):
            dia = hasta - timedelta(days=d)
            for uid in ctx["agentes"]:
                ini = datetime(dia.year, dia.month, dia.day, 13)  # 08:00 en Bogotá
                sesion_id = await con.fetchval(
                    "INSERT INTO sesiones_agente (tenant_id, user_id, campanas, inicio, fin) VALUES ($1,$2,$3,$4,$5) RETURNING id",
                    ctx["tenant"], uid, json.dumps([ctx["camp"]]), ini, ini + timedelta(hours=10))
                sesiones += 1
                t = ini
                for _ in range(llamadas_por_agente_dia):
                    listo, ring, hablado, dispo = rnd.randint(5, 60), rnd.randint(4, 20), rnd.randint(30, 240), rnd.randint(5, 40)
                    u = uuidlib.uuid4().hex
                    inicio_llamada = t + timedelta(seconds=listo)
                    for estado, dur in (("LISTO", listo), ("TIMBRANDO", ring), ("EN_LLAMADA", hablado), ("DISPO", dispo)):
                        tramos.append((ctx["tenant"], uid, sesion_id, estado, ctx["camp"], u if estado != "LISTO" else None,
                                       t, t + timedelta(seconds=dur)))
                        t += timedelta(seconds=dur)
                    contesto = rnd.random() < 0.85
                    cdrs.append((ctx["tenant"], ctx["camp"], u, "outbound", "answered" if contesto else "no_answer",
                                 ring + hablado, hablado if contesto else 0, inicio_llamada, ring * 1000, uid,
                                 rnd.choice(disps) if contesto and disps else None, f"300{rnd.randint(0, 9_999_999):07d}"))
        await con.copy_records_to_table("estados_agente", records=tramos, columns=[
            "tenant_id", "user_id", "sesion_id", "estado", "campaign_id", "call_uuid", "inicio", "fin"])
        await con.copy_records_to_table("call_logs", records=cdrs, columns=[
            "tenant_id", "campaign_id", "uuid", "direction", "status", "duration", "billsec", "started_at", "ring_ms",
            "agente_id", "disposicion_id", "callee_number"])
        await con.execute("ANALYZE estados_agente; ANALYZE call_logs; ANALYZE sesiones_agente")
    finally:
        await con.close()
    return {"sesiones": sesiones, "tramos": len(tramos), "llamadas": len(cdrs)}


async def medir_reportes(ctx: dict, desde: date, hasta: date) -> dict:
    r = reportes.rango_utc(desde, hasta)
    tiempos = {}
    for tipo in reportes.TIPOS:
        async with sesion_de_empresa(ctx["tenant"]) as s:
            t0 = time.perf_counter()
            await reportes.generar(s, tipo, r)
            tiempos[tipo] = round((time.perf_counter() - t0) * 1000, 1)
    return tiempos


async def principal(n_agentes: int, dias: int, llamadas: int) -> dict:
    ctx = await sembrar(n_agentes, n_leads=n_agentes * 5)
    try:
        resultado = {"motor": await medir_motor(ctx), "supervision_ms": await medir_supervision(ctx)}
        hasta = date.today() - timedelta(days=1)
        resultado["historia"] = await sembrar_historia(ctx, dias, llamadas, hasta)
        resultado["reportes_1_dia_ms"] = await medir_reportes(ctx, hasta, hasta)
        resultado[f"reportes_{dias}_dias_ms"] = await medir_reportes(ctx, hasta - timedelta(days=dias - 1), hasta)
        return resultado
    finally:
        await limpiar(ctx)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--agentes", type=int, default=200)
    p.add_argument("--dias", type=int, default=7)
    p.add_argument("--llamadas", type=int, default=100, help="Llamadas por agente por día")
    a = p.parse_args()
    print(json.dumps(asyncio.run(principal(a.agentes, a.dias, a.llamadas)), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
