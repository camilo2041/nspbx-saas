"""Contraseñas SIP: la puerta de entrada del fraude telefónico es una
extensión con una clave que un escáner adivina."""

import pytest

from app.core.validacion import generar_clave_sip, problema_clave_sip


@pytest.mark.parametrize(
    "clave,numero",
    [
        ("", None),
        ("corta", None),
        ("123456789012", None),  # solo números
        ("ext1000-oficina", "1000"),  # contiene el número
        ("password1234", None),  # común
        ("Contraseña2026", None),
        ("aaaaaaaaaaaa", None),  # sin variedad
        ("abababab1212", None),
    ],
)
def test_claves_rechazadas(clave, numero):
    assert problema_clave_sip(clave, numero)


@pytest.mark.parametrize("clave", ["clave-sip-alfa", "Tr0mpeta-Azul-77", "x9Lq2mZr8Vt4"])
def test_claves_aceptadas(clave):
    assert problema_clave_sip(clave, "1000") is None


def test_las_generadas_son_fuertes_y_distintas():
    claves = {generar_clave_sip() for _ in range(50)}
    assert len(claves) == 50
    assert all(problema_clave_sip(c, "1000") is None and len(c) == 20 for c in claves)


async def test_crear_extension_sin_clave_la_genera(cliente, mundo):
    resp = await cliente.post("/api/extensions", headers=mundo.alfa.cabeceras(), json={"number": "1101"})
    assert resp.status_code == 201, resp.text
    assert problema_clave_sip(resp.json()["password"], "1101") is None


async def test_crear_extension_con_clave_debil_se_rechaza(cliente, mundo):
    resp = await cliente.post(
        "/api/extensions", headers=mundo.alfa.cabeceras(), json={"number": "1102", "password": "1102"}
    )
    assert resp.status_code == 422
    assert "12 caracteres" in resp.text


async def test_cambiar_a_una_clave_debil_se_rechaza(cliente, mundo):
    ext = mundo.alfa.ids["extension"]
    resp = await cliente.put(f"/api/extensions/{ext}", headers=mundo.alfa.cabeceras(), json={"password": "123456789012"})
    assert resp.status_code == 422


async def test_una_clave_debil_heredada_no_impide_editar_otros_campos(cliente, mundo):
    """El panel manda el formulario completo, con la contraseña actual."""
    from sqlalchemy import update

    from app.core.database import async_session
    from app.models import Extension

    crear = await cliente.post("/api/extensions", headers=mundo.alfa.cabeceras(), json={"number": "1103"})
    ext_id = crear.json()["id"]
    async with async_session() as s:
        await s.execute(update(Extension).where(Extension.id == ext_id).values(password="1103"))
        await s.commit()

    resp = await cliente.put(
        f"/api/extensions/{ext_id}", headers=mundo.alfa.cabeceras(),
        json={"password": "1103", "caller_id_name": "Recepcion dos"},
    )
    assert resp.status_code == 200, resp.text

    debiles = await cliente.get("/api/security/claves-debiles", headers=mundo.alfa.cabeceras())
    assert debiles.status_code == 200
    assert [d["number"] for d in debiles.json()] == ["1103"]
