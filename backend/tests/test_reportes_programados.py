"""Fase 6: reportes que salen solos por correo.

Períodos cerrados (ayer, la semana pasada, el mes pasado), a la hora local
elegida, nunca dos veces el mismo período, y reintento espaciado si el
correo falla. El SMTP se simula.
"""

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core import permissions
from app.core.config import settings
from app.core.database import sesion_de_empresa
from app.models import ReporteProgramado
from app.services import reportes_programados as rp

from .test_agentes import papa  # noqa: F401  (fixture)
from .test_supervision import _cab, _usuario


def test_periodos_cerrados():
    lunes = date(2026, 9, 14)
    assert rp.periodo("diaria", lunes) == rp.Periodo(date(2026, 9, 13), date(2026, 9, 13), "2026-09-13", lunes)
    p = rp.periodo("semanal", date(2026, 9, 16))  # miércoles
    assert (p.desde, p.hasta, p.etiqueta, p.sale) == (date(2026, 9, 7), date(2026, 9, 13), "2026-S37", lunes)
    p = rp.periodo("mensual", date(2026, 3, 10))
    assert (p.desde, p.hasta, p.etiqueta, p.sale) == (date(2026, 2, 1), date(2026, 2, 28), "2026-02", date(2026, 3, 1))


def test_cuando_toca():
    rep = ReporteProgramado(frecuencia="semanal", hora=7, activo=True)
    utc = datetime(2026, 9, 14, 12)
    assert rp.toca(rep, datetime(2026, 9, 14, 6, 59), utc) is None  # el lunes, antes de la hora
    assert rp.toca(rep, datetime(2026, 9, 14, 7, 0), utc).etiqueta == "2026-S37"
    # El servidor estuvo apagado el lunes: sale el martes a cualquier hora.
    assert rp.toca(rep, datetime(2026, 9, 15, 3, 0), utc).etiqueta == "2026-S37"
    rep.ultimo_periodo = "2026-S37"
    assert rp.toca(rep, datetime(2026, 9, 15, 9, 0), utc) is None  # ya salió
    rep.ultimo_periodo, rep.ultimo_error, rep.ultimo_intento_at = None, "SMTP caído", utc - timedelta(minutes=10)
    assert rp.toca(rep, datetime(2026, 9, 15, 9, 0), utc) is None  # espera tras un error
    rep.ultimo_intento_at = utc - timedelta(minutes=31)
    assert rp.toca(rep, datetime(2026, 9, 15, 9, 0), utc) is not None
    rep.activo = False
    assert rp.toca(rep, datetime(2026, 9, 15, 9, 0), utc) is None


def test_destinatarios():
    assert rp.leer_destinatarios("A@x.co; b@y.com , a@x.co") == ["a@x.co", "b@y.com"]
    for malo in ("", "no-es-correo", ",".join(f"u{i}@x.co" for i in range(11))):
        with pytest.raises(ValueError):
            rp.leer_destinatarios(malo)


@pytest.fixture
def smtp(monkeypatch):
    enviados = []
    monkeypatch.setattr(settings, "smtp_host", "smtp.prueba.test")
    monkeypatch.setattr(settings, "smtp_remitente", "reportes@nspbx.test")
    monkeypatch.setattr(rp, "_enviar_smtp", lambda m: enviados.append(m))
    return enviados


async def test_api_y_envio(cliente, papa, smtp, monkeypatch):  # noqa: F811
    coord = await _usuario(papa, permissions.COORDINADOR)
    cab = _cab(papa, coord, permissions.COORDINADOR)
    r = await cliente.post("/api/reportes/programados", headers=cab, json={
        "nombre": "Cumplimiento semanal", "tipo": "cumplimiento", "frecuencia": "semanal", "hora": 7,
        "destinatarios": "jefa@papa.test; legal@papa.test", "filtros": {"max_contactos_semana": 2},
    })
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    assert r.json()["destinatarios"] == "jefa@papa.test, legal@papa.test"
    assert (await cliente.post("/api/reportes/programados", headers=cab, json={
        "nombre": "x", "tipo": "campanas", "frecuencia": "diaria", "destinatarios": "malo"})).status_code == 422
    lista = (await cliente.get("/api/reportes/programados", headers=cab)).json()
    assert lista["correo_configurado"] is True and lista["programados"][0]["id"] == rid

    r = await cliente.post(f"/api/reportes/programados/{rid}/enviar", headers=cab)
    assert r.status_code == 200, r.text
    m = smtp[-1]
    assert m["To"] == "jefa@papa.test, legal@papa.test" and m["Subject"].startswith("[Papa] Cumplimiento semanal")
    adjuntos = [a.get_filename() for a in m.iter_attachments()]
    assert len(adjuntos) == 3 and all(a.startswith("cumplimiento-") and a.endswith(".csv") for a in adjuntos)
    # Ya salió ese período: la vuelta automática no lo repite.
    assert await rp.enviar(papa["tenant"], rid) is None and len(smtp) == 1

    # Falla el correo: queda el error y se reintenta más tarde.
    def falla(m):
        raise OSError("conexión rechazada")

    monkeypatch.setattr(rp, "_enviar_smtp", falla)
    r = await cliente.post(f"/api/reportes/programados/{rid}/enviar", headers=cab)
    assert r.status_code == 502
    async with sesion_de_empresa(papa["tenant"]) as s:
        fila = (await s.execute(select(ReporteProgramado).where(ReporteProgramado.id == rid))).scalar_one()
        assert "conexión rechazada" in fila.ultimo_error and fila.ultimo_intento_at is not None
    # Asesor: no.
    assert (await cliente.get("/api/reportes/programados", headers=papa["cab"](papa["agentes"][0]))).status_code == 403


async def test_sin_smtp_no_se_envia(cliente, papa, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "smtp_host", "")
    coord = await _usuario(papa, permissions.ADMIN, "297")
    cab = _cab(papa, coord, permissions.ADMIN)
    r = await cliente.post("/api/reportes/programados", headers=cab, json={
        "nombre": "Diario", "tipo": "agentes", "frecuencia": "diaria", "destinatarios": "a@papa.test"})
    assert r.status_code == 201
    assert (await cliente.get("/api/reportes/programados", headers=cab)).json()["correo_configurado"] is False
    assert (await cliente.post(f"/api/reportes/programados/{r.json()['id']}/enviar", headers=cab)).status_code == 409
    assert await rp.programador.ciclo() == 0
