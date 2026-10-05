"""Marcar a mano una promesa de pago como cumplida o incumplida."""

from datetime import datetime

import pytest

from app.core import permissions
from app.core.database import async_session
from app.models import Debt, PaymentPromise


@pytest.fixture
async def promesa(mundo):
    async with async_session() as s:
        deuda = Debt(tenant_id=mundo.alfa.id, phone="3009990001", debtor_name="Prom", amount=500, status="promised")
        s.add(deuda)
        await s.flush()
        p = PaymentPromise(tenant_id=mundo.alfa.id, debt_id=deuda.id, phone="3009990001", debtor_name="Prom",
                           amount_promised=200, promise_date=datetime(2026, 10, 10), plan="abono")
        s.add(p)
        await s.commit()
        return {"id": p.id, "deuda": deuda.id}


async def test_marcar_cumplida_no_salda_la_deuda(cliente, mundo, promesa):
    r = await cliente.put(f"/api/cobranza/promises/{promesa['id']}", json={"status": "completed", "notes": "Pagó en caja"},
                          headers=mundo.alfa.cabeceras())
    assert r.status_code == 200, r.text
    assert (r.json()["status"], r.json()["notes"]) == ("completed", "Pagó en caja")
    async with async_session() as s:
        # Un abono cumple la promesa, pero la deuda sigue.
        assert (await s.get(Debt, promesa["deuda"])).status == "promised"


@pytest.mark.parametrize("malo", ["paid", "", "COMPLETED"])
async def test_estado_invalido(cliente, mundo, promesa, malo):
    r = await cliente.put(f"/api/cobranza/promises/{promesa['id']}", json={"status": malo}, headers=mundo.alfa.cabeceras())
    assert r.status_code == 422


async def test_requiere_permiso_de_campanas(cliente, mundo, promesa):
    r = await cliente.put(f"/api/cobranza/promises/{promesa['id']}", json={"status": "missed"},
                          headers=mundo.alfa.cabeceras(permissions.ASESOR))
    assert r.status_code == 403
