"""Fase G: prueba de humo, vigía de grupos y devolución de llamada, buzón
completo, festivos, calidad automática y operación."""

import re
from datetime import datetime

import pytest
from sqlalchemy import delete, select, update

from app.core import permissions
from app.core.config import settings
from app.core.database import async_session
from app.models import Extension, MensajeBuzon, NumeroSinRuta, Queue
from app.services import esl, humo

# --- G1: prueba de humo --------------------------------------------------------------------


class CentralFalsa:
    """Responde como FreeSWITCH y, al originar, deja lo que dejaría el CDR."""

    def __init__(self, monkeypatch, mundo, viva=True, deja_cdr=True):
        self.mundo, self.viva, self.deja_cdr = mundo, viva, deja_cdr
        self.comandos: list[str] = []
        self.en_fila: str | None = None
        monkeypatch.setattr(esl, "api", self.api)
        monkeypatch.setattr(esl, "bgapi", self.bgapi)

    async def api(self, cmd, tenant_id=None, **kw):
        self.comandos.append(cmd)
        if not self.viva:
            raise ConnectionError("ESL caído")
        if cmd == "status":
            return "UP 0 years, 1 day\nFreeSWITCH is ready\n"
        if cmd.startswith("sofia status gateway"):
            return "State\tREGED\n"
        if cmd == "show registrations":
            return f"reg_user,realm\n1000,{self.mundo.alfa.dominio}\n"
        if cmd.startswith("callcenter_config queue list members"):
            cabecera = "queue|instance_id|uuid|session_uuid|cid_number|cid_name|system_epoch|joined_epoch|state|score"
            fila = f"\nq|i|m|aaaaaaaa-0000-0000-0000-000000000009|{self.en_fila}|P|0|1|Waiting|0" if self.en_fila else ""
            return cabecera + fila + "\n+OK\n"
        if cmd.startswith("callcenter_config queue list agents"):
            return "name|status|state|max_no_answer\n1000@x|Available|Waiting|3\n+OK\n"
        return "+OK"

    async def bgapi(self, cmd, tenant_id=None, **kw):
        self.comandos.append(cmd)
        quien = re.search(r"origination_caller_id_number=(\d+)", cmd).group(1)
        destino = re.search(r"loopback/([^/ ]+)/", cmd).group(1)
        if destino.startswith("*99") and self.deja_cdr:
            async with async_session() as s:
                s.add(MensajeBuzon(tenant_id=self.mundo.alfa.id, extension="1000", caller_number=quien, duracion=7,
                                   ruta=f"{settings.fs_recordings_dir}/t{self.mundo.alfa.id}/buzon/1000/humo.wav"))
                await s.commit()
        elif destino.startswith(humo.PREFIJO) and self.deja_cdr:
            async with async_session() as s:
                s.add(NumeroSinRuta(numero=destino, origen=quien))
                await s.commit()
        elif "/public" not in cmd:
            self.en_fila = quien
        return "+OK Job-UUID: x"


@pytest.fixture
async def con_buzon_y_grupo(mundo):
    async with async_session() as s:
        await s.execute(update(Extension).where(Extension.tenant_id == mundo.alfa.id, Extension.number == "1000")
                        .values(voicemail=True))
        q = Queue(tenant_id=mundo.alfa.id, name="humo_g", extension="8711", strategy="ring-all", agents='["1000"]', enabled=True)
        s.add(q)
        await s.commit()
    yield
    async with async_session() as s:
        await s.execute(update(Extension).where(Extension.tenant_id == mundo.alfa.id, Extension.number == "1000")
                        .values(voicemail=False))
        await s.execute(delete(Queue).where(Queue.id == q.id))
        await s.execute(delete(NumeroSinRuta))
        await s.commit()


async def test_prueba_de_humo_completa(cliente, mundo, monkeypatch, con_buzon_y_grupo):
    central = CentralFalsa(monkeypatch, mundo)
    r = await cliente.post("/api/plataforma/humo", headers=mundo.cabeceras_plataforma(),
                           json={"tenant_id": mundo.alfa.id, "buzon": "1000", "grupo": "8711"})
    assert r.status_code == 200, r.text
    pasos = {p["clave"]: p for p in r.json()["pasos"]}
    assert {k: p["estado"] for k, p in pasos.items() if k != "voces"} == {
        "central": "ok", "proveedores": "ok", "telefonos": "ok", "sin_ruta": "ok", "buzon": "ok", "grupo": "ok",
    }
    assert "1 conectado" in pasos["telefonos"]["detalle"] and "1 agente(s) libre(s)" in pasos["grupo"]["detalle"]
    # Lo que dejó la prueba se limpia, y la llamada de la fila se cuelga.
    async with async_session() as s:
        assert not (await s.execute(select(MensajeBuzon).where(MensajeBuzon.caller_number.like(f"{humo.PREFIJO}%")))).first()
        assert not (await s.execute(select(NumeroSinRuta))).first()
    assert any(c.startswith("uuid_kill ") for c in central.comandos)
    # El buzón se prueba por *99 en el contexto de la empresa; el número sin ruta, por el público.
    assert any(f"loopback/*991000/ctx_{mundo.alfa.slug}" in c for c in central.comandos)
    assert any("/public &park()" in c for c in central.comandos)
    # Solo la plataforma.
    r = await cliente.post("/api/plataforma/humo", headers=mundo.alfa.cabeceras(permissions.ADMIN), json={"tenant_id": mundo.alfa.id})
    assert r.status_code == 403


async def test_prueba_de_humo_con_fallos(mundo, monkeypatch, con_buzon_y_grupo):
    monkeypatch.setattr(humo, "ESPERA_CDR_SEG", 1)
    CentralFalsa(monkeypatch, mundo, deja_cdr=False)
    r = await humo.probar(mundo.alfa.id, "1000", "9999")
    pasos = {p["clave"]: p for p in r["pasos"]}
    assert r["ok"] is False
    assert pasos["sin_ruta"]["estado"] == "fallo" and "json_cdr" in pasos["sin_ruta"]["detalle"]
    assert pasos["buzon"]["estado"] == "fallo"
    assert pasos["grupo"]["estado"] == "fallo" and "no existe" in pasos["grupo"]["detalle"]

    CentralFalsa(monkeypatch, mundo, viva=False)
    r = await humo.probar(mundo.alfa.id)
    assert [p["estado"] for p in r["pasos"]] == ["fallo", "omitido"]


async def test_mensaje_de_prueba_no_manda_correo(cliente, mundo, monkeypatch):
    """El CDR de un mensaje dejado por la prueba de humo no avisa por correo."""
    from app.services import buzon

    avisos = []

    async def avisar(tenant_id, mensaje_id):
        avisos.append(mensaje_id)

    monkeypatch.setattr(buzon, "avisar", avisar)
    monkeypatch.setattr(buzon, "duracion_wav", lambda ruta: 5.0)
    from pathlib import Path

    carpeta = Path(settings.recordings_dir) / f"t{mundo.alfa.id}" / "buzon" / "1000"
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / "humo-g.wav").write_bytes(b"RIFF")
    from .conftest import FS_SECRET

    ruta = f"{settings.fs_recordings_dir.rstrip('/')}/t{mundo.alfa.id}/buzon/1000/humo-g.wav"
    try:
        for quien in (f"{humo.PREFIJO}123456", "3005550000"):
            r = await cliente.post(f"/fs/cdr/{FS_SECRET}", json={"variables": {
                "uuid": f"humo-{quien}-{datetime.utcnow().timestamp()}", "nspbx_tenant_id": str(mundo.alfa.id),
                "direction": "inbound", "billsec": "7", "caller_id_number": quien,
                "nspbx_buzon_ext": "1000", "nspbx_buzon": ruta,
            }})
            assert r.status_code == 200
            (carpeta / "humo-g.wav").write_bytes(b"RIFF")
        assert len(avisos) == 1
    finally:
        async with async_session() as s:
            await s.execute(delete(MensajeBuzon).where(MensajeBuzon.ruta == ruta))
            await s.commit()
