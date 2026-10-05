"""En producción, el backend no arranca sin los secretos que sostienen el
aislamiento y las sesiones. Ver app/core/arranque.py."""

import pytest

from app.core.arranque import exigir_configuracion_segura, problemas_de_configuracion
from app.core.config import Settings

_BIEN = {
    "database_url": "postgresql+asyncpg://dueno:x@db/nspbx",
    "database_url_app": "postgresql+asyncpg://nspbx_app:y@db/nspbx",
    "fs_xml_secret": "s" * 32,
}
_CLAVE = "k" * 48


def _cfg(**cambios) -> Settings:
    return Settings(_env_file=None, **{**_BIEN, **cambios})


def test_configuracion_completa_no_tiene_problemas():
    assert problemas_de_configuracion(_cfg(), _CLAVE) == []
    exigir_configuracion_segura(_cfg(entorno="produccion"), _CLAVE)


@pytest.mark.parametrize(
    "cambios,clave,motivo",
    [
        ({"database_url_app": ""}, _CLAVE, "DATABASE_URL_APP"),
        ({"database_url_app": _BIEN["database_url"]}, _CLAVE, "igual a DATABASE_URL"),
        ({}, "", "AUTH_SECRET no está definida"),
        ({}, "   ", "AUTH_SECRET no está definida"),
        ({}, "corta", "AUTH_SECRET tiene 5 caracteres"),
        ({"fs_xml_secret": ""}, _CLAVE, "FS_XML_SECRET"),
    ],
)
def test_en_produccion_no_arranca(cambios, clave, motivo):
    with pytest.raises(RuntimeError, match=motivo):
        exigir_configuracion_segura(_cfg(entorno="produccion", **cambios), clave)


def test_produccion_es_el_valor_por_omision(monkeypatch):
    """Olvidarse de ENTORNO tiene que dejar el sistema protegido."""
    monkeypatch.delenv("ENTORNO", raising=False)
    assert Settings(_env_file=None).entorno == "produccion"
    with pytest.raises(RuntimeError):
        exigir_configuracion_segura(_cfg(database_url_app=""), _CLAVE)


def test_en_desarrollo_solo_avisa(caplog):
    exigir_configuracion_segura(_cfg(entorno="desarrollo", database_url_app=""), "")
    assert "DATABASE_URL_APP" in caplog.text
