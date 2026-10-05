"""Secretos cifrados en la base (core/cifrado.py)."""

import pytest
from sqlalchemy import text

from app.core import cifrado
from app.core.arranque import problemas_de_configuracion
from app.core.config import Settings
from app.core.database import engine

_CLAVE_OTRA = cifrado.nueva_clave()


async def _crudo(sql: str, **params):
    async with engine.connect() as conn:
        return (await conn.execute(text(sql), params)).scalar()


async def test_en_la_base_no_queda_ningun_secreto_en_claro(mundo):
    """Como si alguien se llevara un volcado: las contraseñas sembradas no
    aparecen en ninguna columna de ninguna tabla."""
    async with engine.connect() as conn:
        columnas = (
            await conn.execute(
                text(
                    "SELECT table_name, column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND data_type IN ('text', 'character varying')"
                )
            )
        ).all()
        for secreto in ("clave-troncal-alfa", "clave-troncal-zzbeta", "clave-sip-alfa"):
            for tabla, columna in columnas:
                n = (
                    await conn.execute(text(f'SELECT count(*) FROM "{tabla}" WHERE "{columna}" LIKE :s'), {"s": f"%{secreto}%"})
                ).scalar()
                assert n == 0, f"{secreto} está en claro en {tabla}.{columna}"


async def test_la_aplicacion_lee_en_claro(cliente, mundo):
    """FreeSWITCH necesita la contraseña de la extensión en el directorio."""
    from .conftest import FS_SECRET

    resp = await cliente.get("/fs/directory", params={"secret": FS_SECRET})
    assert "clave-sip-alfa" in resp.text


async def test_la_api_no_devuelve_la_contrasenia_de_la_troncal(cliente, mundo):
    trunk = mundo.alfa.ids["trunk"]
    resp = await cliente.get(f"/api/trunks/{trunk}", headers=mundo.alfa.cabeceras())
    password = resp.json()["password"]
    assert password.startswith(cifrado.MASCARA) and "clave-troncal" not in password
    assert password.endswith("alfa"[-4:])

    # El panel reenvía la máscara: no cambia.
    await cliente.put(f"/api/trunks/{trunk}", headers=mundo.alfa.cabeceras(), json={"password": password})
    crudo = await _crudo("SELECT password FROM trunks WHERE id = :i", i=trunk)
    assert cifrado.descifrar(crudo) == "clave-troncal-alfa"

    # Una nueva sí.
    await cliente.put(f"/api/trunks/{trunk}", headers=mundo.alfa.cabeceras(), json={"password": "nueva-clave-del-proveedor"})
    crudo = await _crudo("SELECT password FROM trunks WHERE id = :i", i=trunk)
    assert crudo.startswith(cifrado.PREFIJO) and cifrado.descifrar(crudo) == "nueva-clave-del-proveedor"
    await cliente.put(f"/api/trunks/{trunk}", headers=mundo.alfa.cabeceras(), json={"password": "clave-troncal-alfa"})


async def test_claves_de_proveedores_enmascaradas_y_cifradas(cliente, mundo):
    cab = mundo.alfa.cabeceras()
    resp = await cliente.put("/api/system/settings", headers=cab, json={"ai_llm_api_key": "sk-proveedor-secreta-1234"})  # gitleaks:allow (clave de prueba)
    assert resp.status_code == 200
    assert resp.json()["ai_llm_api_key"] == cifrado.MASCARA + "1234"
    crudo = await _crudo("SELECT ai_llm_api_key FROM system_settings WHERE tenant_id = :t", t=mundo.alfa.id)
    assert crudo.startswith(cifrado.PREFIJO) and "sk-proveedor" not in crudo

    # Guardar el formulario con la máscara no la pisa; vaciarla sí la borra.
    await cliente.put("/api/system/settings", headers=cab, json={"ai_llm_api_key": cifrado.MASCARA + "1234", "app_name": "Alfa"})
    crudo = await _crudo("SELECT ai_llm_api_key FROM system_settings WHERE tenant_id = :t", t=mundo.alfa.id)
    assert cifrado.descifrar(crudo) == "sk-proveedor-secreta-1234"
    await cliente.put("/api/system/settings", headers=cab, json={"ai_llm_api_key": ""})
    assert await _crudo("SELECT ai_llm_api_key FROM system_settings WHERE tenant_id = :t", t=mundo.alfa.id) == ""


async def test_valores_en_claro_de_antes_se_cifran_al_arrancar(mundo):
    trunk = mundo.beta.ids["trunk"]
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE trunks SET password = 'heredada-en-claro' WHERE id = :i"), {"i": trunk})
        await conn.run_sync(cifrado.cifrar_pendientes)
    crudo = await _crudo("SELECT password FROM trunks WHERE id = :i", i=trunk)
    assert crudo.startswith(cifrado.PREFIJO) and cifrado.descifrar(crudo) == "heredada-en-claro"
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE trunks SET password = :p WHERE id = :i"), {"p": cifrado.cifrar("clave-troncal-zzbeta"), "i": trunk})


def test_rotacion_de_clave(monkeypatch):
    viejo = cifrado.cifrar("dato")
    actual = monkeypatch.setenv
    import os

    anterior = os.environ["DATA_ENCRYPTION_KEY"]
    actual("DATA_ENCRYPTION_KEY", _CLAVE_OTRA)
    # Sin la anterior configurada, no se lee (y no devuelve el cifrado).
    assert cifrado.descifrar(viejo) is None
    actual("DATA_ENCRYPTION_KEY_ANTERIOR", anterior)
    assert cifrado.descifrar(viejo) == "dato"
    assert not cifrado.cifrado_con_clave_actual(viejo)
    assert cifrado.cifrado_con_clave_actual(cifrado.cifrar("dato"))


def test_cada_cifrado_es_distinto_y_no_se_cifra_dos_veces():
    a, b = cifrado.cifrar("x"), cifrado.cifrar("x")
    assert a != b and cifrado.descifrar(a) == cifrado.descifrar(b) == "x"
    assert cifrado.cifrar(a) == a
    assert cifrado.cifrar("") == "" and cifrado.cifrar(None) is None


def test_corrupto_no_se_devuelve():
    assert cifrado.descifrar(cifrado.PREFIJO + "no-es-base64!!") is None
    assert cifrado.descifrar(cifrado.PREFIJO + "QUJD") is None


@pytest.mark.parametrize(
    "clave,motivo",
    [("", "DATA_ENCRYPTION_KEY no está definida"), ("YWJj", "32 bytes"), ("%%%", "base64"), ("con espacios", "base64")],
)
def test_en_produccion_se_exige_la_clave(monkeypatch, clave, motivo):
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", clave)
    cfg = Settings(
        _env_file=None, database_url="postgresql+asyncpg://a@b/c",
        database_url_app="postgresql+asyncpg://d@b/c", fs_xml_secret="s" * 32,
    )
    assert any(motivo in p for p in problemas_de_configuracion(cfg, "k" * 48))


def test_mascara():
    assert cifrado.enmascarar("sk-1234567890abcd") == cifrado.MASCARA + "abcd"
    assert cifrado.enmascarar("corta") == cifrado.MASCARA
    assert cifrado.enmascarar("") == "" and cifrado.enmascarar(None) is None
    assert cifrado.es_mascara(cifrado.MASCARA + "abcd") and not cifrado.es_mascara("abcd")
