"""Grabaciones separadas por empresa: carpeta propia, retención propia, y
ninguna empresa grabada por la configuración de otra."""

import os
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from sqlalchemy import update

from app.core.config import settings
from app.core.database import async_session
from app.models import SystemSettings
from app.workers.maintenance import maintenance

from .conftest import FS_SECRET


async def _poner(tenant_id: int, **valores):
    async with async_session() as s:
        await s.execute(update(SystemSettings).where(SystemSettings.tenant_id == tenant_id).values(**valores))
        await s.commit()


async def test_cada_empresa_graba_en_su_carpeta(cliente, mundo):
    await _poner(mundo.alfa.id, record_all_calls=True)
    try:
        raiz = ET.fromstring((await cliente.get("/fs/dialplan", params={"secret": FS_SECRET})).text)
        ctx = raiz.find(".//context[@name='ctx_alfa']")
        rutas = [a.get("data") for a in ctx.iter("action") if (a.get("data") or "").startswith("nspbx_recording=")]
        assert rutas and all(f"}}/t{mundo.alfa.id}/" in r for r in rutas), rutas
        # beta no graba: su contexto no tiene grabación.
        beta = raiz.find(".//context[@name='ctx_beta']")
        assert not [a for a in beta.iter("action") if a.get("application") == "record_session"]
    finally:
        await _poner(mundo.alfa.id, record_all_calls=False)


async def test_las_entrantes_no_se_graban_por_la_configuracion_de_otra(cliente, mundo):
    """Antes: si CUALQUIER empresa grababa todo, el contexto público grababa
    TODA entrante, también las de las que no graban."""
    await _poner(mundo.alfa.id, record_all_calls=True)
    try:
        raiz = ET.fromstring((await cliente.get("/fs/dialplan", params={"secret": FS_SECRET})).text)
        public = raiz.find(".//context[@name='public']")
        assert not [a for a in public.iter("action") if a.get("application") == "record_session"]
    finally:
        await _poner(mundo.alfa.id, record_all_calls=False)


def _archivo(relativa: str, dias: int) -> Path:
    ruta = Path(settings.recordings_dir) / relativa
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(b"RIFF")
    viejo = time.time() - dias * 86400
    os.utime(ruta, (viejo, viejo))
    return ruta


async def test_retencion_por_empresa(mundo):
    a, b = mundo.alfa.id, mundo.beta.id
    alfa_vieja = _archivo(f"t{a}/2026/01/01/llamada_a.wav", 40)
    beta_vieja = _archivo(f"t{b}/2026/01/01/llamada_b.wav", 40)
    alfa_nueva = _archivo(f"t{a}/2026/09/01/llamada_c.wav", 5)
    cola_alfa = _archivo(f"queue_t{a}_soporte_x.wav", 40)
    heredada = _archivo("2025/01/01/llamada_vieja.wav", 40)

    await maintenance._limpiar_grabaciones(retencion_dias=90, tope_gb=100, por_empresa={a: 30, b: 365})

    assert not alfa_vieja.exists(), "alfa guarda 30 días"
    assert not cola_alfa.exists(), "las de cola también son de la empresa"
    assert beta_vieja.exists(), "beta guarda un año"
    assert alfa_nueva.exists()
    assert heredada.exists(), "lo de antes de separar usa la retención general (90)"
    assert not (Path(settings.recordings_dir) / f"t{a}/2026/01").exists(), "carpetas vacías purgadas"
    for f in (beta_vieja, alfa_nueva, heredada):
        f.unlink()


async def test_se_descarga_una_grabacion_de_la_carpeta_de_la_empresa(cliente, mundo):
    from app.models import CallLog

    relativa = f"t{mundo.alfa.id}/2026/10/01/llamada_x.wav"
    ruta = _archivo(relativa, 0)
    async with async_session() as s:
        llamada = await s.get(CallLog, mundo.alfa.ids["call"])
        anterior = llamada.recording_path
        llamada.recording_path = f"{settings.fs_recordings_dir}/{relativa}"
        await s.commit()
    try:
        resp = await cliente.get(f"/api/calls/{mundo.alfa.ids['call']}/recording", headers=mundo.alfa.cabeceras())
        assert resp.status_code == 200 and resp.content == b"RIFF"
    finally:
        async with async_session() as s:
            llamada = await s.get(CallLog, mundo.alfa.ids["call"])
            llamada.recording_path = anterior
            await s.commit()
        ruta.unlink()


def test_grabaciones_de_cola_llevan_la_empresa():
    from types import SimpleNamespace

    from app.services.queues_sync import build_callcenter_xml

    cola = SimpleNamespace(
        tenant_id=7, name="soporte", record=True, strategy="ring-all", moh_sound="x", max_wait_time=0,
        max_wait_time_with_no_agent=0, agent_ring_timeout=20, max_no_answer=3, wrap_up_time=10,
        announce_position=False, agents="[]", enabled=True,
    )
    xml = build_callcenter_xml([cola], {7: "siete.pbx.test"})
    assert "/queue_t7_soporte_" in xml
