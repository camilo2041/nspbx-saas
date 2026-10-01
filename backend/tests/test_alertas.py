"""Alertas de tráfico saliente anómalo (services/alertas.py)."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete

from app.core import permissions
from app.core.clock import business_tz
from app.core.database import async_session
from app.core.security import crear_token, hash_password
from app.models import CallLog, License, SecurityAlert, Tenant, User
from app.services import alertas
from app.services.salientes import inicio_del_dia_utc


def _utc_de_hora_local(hora: int) -> datetime:
    """Hoy a `hora` local, en UTC naive (la escala de CallLog.started_at)."""
    local = datetime.now(business_tz()).replace(hour=hora, minute=30, second=0, microsecond=0)
    return local.astimezone(timezone.utc).replace(tzinfo=None)


@pytest.fixture
async def zeta(mundo):
    """Empresa nueva por prueba: las alertas dependen de la historia."""
    async with async_session() as s:
        slug = f"zeta{datetime.utcnow().strftime('%H%M%S%f')}"
        t = Tenant(name=f"Zeta {slug}", slug=slug, sip_domain=f"{slug}.pbx.test", modules="voicebot,pbx", enabled=True)
        s.add(t)
        await s.flush()
        s.add(License(tenant_id=t.id, plan="enterprise", status="active"))
        admin = User(
            tenant_id=t.id, username=f"admin-{slug}", full_name="admin zeta",
            password_hash=hash_password("clave-de-prueba"), role=permissions.ADMIN, enabled=True,
        )
        s.add(admin)
        await s.commit()
        datos = {"tenant": t.id, "cab": {"Authorization": f"Bearer {crear_token(admin.id, permissions.ADMIN, t.id)[0]}"}}
    yield datos
    async with async_session() as s:
        await s.execute(delete(CallLog).where(CallLog.tenant_id == datos["tenant"]))
        await s.execute(delete(SecurityAlert).where(SecurityAlert.tenant_id == datos["tenant"]))
        await s.commit()


async def _llamadas(tenant_id: int, minutos: int, cuando: datetime, destino: str = "3001234567", via_trunk=True):
    async with async_session() as s:
        s.add(
            CallLog(
                tenant_id=tenant_id, uuid=f"al-{tenant_id}-{cuando.timestamp()}-{destino}-{minutos}",
                direction="outbound", status="answered", callee_number=destino,
                billsec=minutos * 60, via_trunk=via_trunk, started_at=cuando,
            )
        )
        await s.commit()


def _de(hallazgos, tenant_id):
    return {(k, d) for t, k, d in hallazgos if t == tenant_id}


async def test_sin_trafico_no_hay_alertas(zeta):
    async with async_session() as s:
        assert not _de(await alertas.detectar(s, _utc_de_hora_local(14)), zeta["tenant"])


async def test_pico_respecto_de_lo_habitual(zeta):
    ahora = _utc_de_hora_local(14)
    for dias in range(1, 8):  # lo habitual: 10 min a esta hora
        await _llamadas(zeta["tenant"], 10, ahora - timedelta(days=dias, minutes=20))
    await _llamadas(zeta["tenant"], 25, ahora - timedelta(minutes=20))
    async with async_session() as s:
        assert not {k for k, _ in _de(await alertas.detectar(s, ahora), zeta["tenant"])} & {"pico"}, "25 < 3 x 10"
    await _llamadas(zeta["tenant"], 20, ahora - timedelta(minutes=10))
    async with async_session() as s:
        tipos = {k for k, _ in _de(await alertas.detectar(s, ahora), zeta["tenant"])}
    assert "pico" in tipos, "45 > 3 x 10"


async def test_pico_sin_historia_respeta_el_piso(zeta):
    ahora = _utc_de_hora_local(14)
    await _llamadas(zeta["tenant"], alertas.PISO_MINUTOS - 5, ahora - timedelta(minutes=10))
    async with async_session() as s:
        assert "pico" not in {k for k, _ in _de(await alertas.detectar(s, ahora), zeta["tenant"])}


async def test_las_internas_no_cuentan(zeta):
    ahora = _utc_de_hora_local(14)
    await _llamadas(zeta["tenant"], 500, ahora - timedelta(minutes=10), via_trunk=False)
    async with async_session() as s:
        assert not _de(await alertas.detectar(s, ahora), zeta["tenant"])


async def test_madrugada(zeta):
    ahora = _utc_de_hora_local(3)
    await _llamadas(zeta["tenant"], 15, ahora - timedelta(minutes=10))
    async with async_session() as s:
        assert "madrugada" in {k for k, _ in _de(await alertas.detectar(s, ahora), zeta["tenant"])}


async def test_destino_internacional_nuevo(zeta):
    ahora = _utc_de_hora_local(14)
    await _llamadas(zeta["tenant"], 1, ahora - timedelta(days=3), destino="+12125551234")
    await _llamadas(zeta["tenant"], 1, ahora - timedelta(minutes=5), destino="+12125559999")  # conocido
    await _llamadas(zeta["tenant"], 1, ahora - timedelta(minutes=5), destino="0044770090012")  # nuevo
    async with async_session() as s:
        detalles = [d for k, d in _de(await alertas.detectar(s, ahora), zeta["tenant"]) if k == "destino_nuevo"]
    assert detalles == ["Llamadas a destinos internacionales nuevos: +4477…"]


async def test_cerca_del_cupo(zeta, cliente, mundo):
    await cliente.put(
        f"/api/tenants/{zeta['tenant']}/licencia", headers=mundo.cabeceras_plataforma(), json={"max_outbound_minutes_day": 10}
    )
    # Dentro de HOY aunque la prueba corra recién pasada la medianoche.
    await _llamadas(zeta["tenant"], 8, max(datetime.utcnow() - timedelta(minutes=5), inicio_del_dia_utc()))
    async with async_session() as s:
        assert "cupo" in {k for k, _ in _de(await alertas.detectar(s), zeta["tenant"])}


async def test_revisar_guarda_avisa_y_no_repite(zeta, cliente, mundo, monkeypatch):
    enviados = []

    async def _avisar(alerta, empresa):
        enviados.append((empresa, alerta.kind))

    monkeypatch.setattr(alertas, "_avisar", _avisar)
    ahora = _utc_de_hora_local(3)
    await _llamadas(zeta["tenant"], 40, ahora - timedelta(minutes=10))
    async with async_session() as s:
        primeras = await alertas.revisar(s, ahora)
    tipos = {a.kind for a in primeras if a.tenant_id == zeta["tenant"]}
    assert {"pico", "madrugada"} <= tipos
    assert any(k == "pico" for _, k in enviados)
    async with async_session() as s:
        segundas = await alertas.revisar(s, ahora + timedelta(minutes=5))
    assert not [a for a in segundas if a.tenant_id == zeta["tenant"]], "repitió dentro del silencio"

    # La empresa ve las suyas; otra empresa no; la plataforma, todas.
    propias = await cliente.get("/api/security/alertas", headers=zeta["cab"])
    assert {a["tipo"] for a in propias.json()} >= {"pico", "madrugada"}
    ajenas = await cliente.get("/api/security/alertas", headers=mundo.alfa.cabeceras())
    assert all(a["detalle"] for a in ajenas.json())
    assert not any(a["id"] in {p["id"] for p in propias.json()} for a in ajenas.json())
    todas = await cliente.get("/api/plataforma/alertas", headers=mundo.cabeceras_plataforma())
    assert {p["id"] for p in propias.json()} <= {a["id"] for a in todas.json()}
    assert (await cliente.get("/api/plataforma/alertas", headers=zeta["cab"])).status_code == 403
