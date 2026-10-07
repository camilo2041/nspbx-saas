"""Las guías en pantalla que conoce el asistente son las que existen en el panel."""
import re
from pathlib import Path

from app.api.assistant import GUIAS, _sistema

GUIAS_TS = Path(__file__).resolve().parents[2] / "frontend" / "lib" / "guias.ts"


def _ids_del_front() -> list[str]:
    texto = GUIAS_TS.read_text(encoding="utf-8")
    return re.findall(r'^\s{4}id: "([a-z0-9-]+)",$', texto, flags=re.M)


def test_mismos_ids_que_el_front():
    if not GUIAS_TS.exists():  # imagen del backend sin el front
        return
    ids = _ids_del_front()
    assert ids, "no se encontró ninguna guía en frontend/lib/guias.ts"
    assert len(ids) == len(set(ids)), "ids de guía repetidos en el front"
    assert set(ids) == set(GUIAS)


def test_el_prompt_ofrece_las_guias():
    sistema = _sistema("Usuario: Ana (rol admin).")
    assert "[[guia:id]]" in sistema
    for gid in GUIAS:
        assert f"- {gid}:" in sistema


GUIAS_APP = Path(__file__).resolve().parents[2] / "mobile" / "src" / "guias.ts"


def test_las_guias_de_la_app_existen_en_el_asistente():
    """La app tiene solo las que se hacen desde el teléfono, pero con los mismos ids."""
    if not GUIAS_APP.exists():
        return
    ids = re.findall(r'^\s{4}id: "([a-z0-9-]+)",$', GUIAS_APP.read_text(encoding="utf-8"), flags=re.M)
    assert ids and len(ids) == len(set(ids))
    assert set(ids) <= set(GUIAS), set(ids) - set(GUIAS)
