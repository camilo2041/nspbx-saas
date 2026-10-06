"""Importar clientes desde Excel (.xlsx) directo, sin «Guardar como CSV»."""

import io
import json
import zipfile

import pytest

from app.services import excel, importar_crm

_NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
_NS_R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'


def _xlsx(filas: list[list], fechas_col: set[int] = frozenset()) -> bytes:
    """Un .xlsx mínimo como lo guarda Excel: textos compartidos, números y un
    estilo de fecha (numFmtId 14) para las columnas de `fechas_col`."""
    compartidos: list[str] = []
    celdas_xml = []
    for r, fila in enumerate(filas, start=1):
        celdas = []
        for c, valor in enumerate(fila):
            ref = f"{chr(65 + c)}{r}"
            if isinstance(valor, str):
                if valor not in compartidos:
                    compartidos.append(valor)
                celdas.append(f'<c r="{ref}" t="s"><v>{compartidos.index(valor)}</v></c>')
            else:
                estilo = ' s="1"' if c in fechas_col else ""
                celdas.append(f'<c r="{ref}"{estilo}><v>{valor}</v></c>')
        celdas_xml.append(f'<row r="{r}">{"".join(celdas)}</row>')
    archivos = {
        "[Content_Types].xml": '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        "xl/workbook.xml": f'<workbook {_NS} {_NS_R}><sheets><sheet name="Clientes" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="worksheet" Target="worksheets/hoja_clientes.xml"/></Relationships>',
        "xl/worksheets/hoja_clientes.xml": f'<worksheet {_NS}><sheetData>{"".join(celdas_xml)}</sheetData></worksheet>',
        "xl/sharedStrings.xml": f'<sst {_NS}>' + "".join(f"<si><t>{t}</t></si>" for t in compartidos) + "</sst>",
        "xl/styles.xml": f'<styleSheet {_NS}><cellXfs><xf numFmtId="0"/><xf numFmtId="14"/></cellXfs></styleSheet>',
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for nombre, contenido in archivos.items():
            zf.writestr(nombre, contenido)
    return buf.getvalue()


def test_lee_textos_numeros_y_fechas():
    contenido = _xlsx(
        [["Celular", "Nombre", "Monto", "Vence"], [3001234567, "Ana Pérez", 150000.5, 46300], [3109876543, "Luis", 20000, 46301]],
        fechas_col={3},
    )
    datos = importar_crm.leer(contenido)
    assert datos.columnas == ["Celular", "Nombre", "Monto", "Vence"]
    # El teléfono guardado como número no queda «3001234567.0».
    assert datos.filas[0] == ["3001234567", "Ana Pérez", "150000.5", "2026-10-05"]
    assert len(datos.filas) == 2


def test_excel_viejo_y_zip_bomba_se_rechazan(monkeypatch):
    with pytest.raises(importar_crm.ErrorDeArchivo, match=r"\.xls"):
        importar_crm.leer(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"0" * 100)
    monkeypatch.setattr(excel, "MAX_DESCOMPRIMIDO", 100)
    with pytest.raises(importar_crm.ErrorDeArchivo, match="demasiado grande"):
        importar_crm.leer(_xlsx([["telefono"], [3001234567]]))


async def test_importar_un_excel_a_una_campana(cliente, mundo):
    cab = mundo.alfa.cabeceras()
    camp = mundo.alfa.ids["campaign"]
    contenido = _xlsx([["Celular", "Nombre", "Saldo"], [3001112233, "Cliente Uno", 50000], [3004445566, "Cliente Dos", 75000]])
    archivos = {"archivo": ("cartera.xlsx", contenido, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}

    r = await cliente.post("/api/crm/importar/vista-previa", headers=cab, files=archivos)
    assert r.status_code == 200, r.text
    assert r.json()["sugerido"]["Celular"] == "telefono" and r.json()["total_filas"] == 2

    mapeo = {"Celular": "telefono", "Nombre": "nombre", "Saldo": "var:saldo"}
    r = await cliente.post(
        "/api/crm/importar", headers=cab, files=archivos,
        data={"mapeo": json.dumps(mapeo), "campaign_id": str(camp), "nombre_lista": "cartera"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["con_error"] == 0 and r.json()["campana"]["added"] == 2
    numeros = (await cliente.get(f"/api/campaigns/{camp}/numbers?search=3001112233", headers=cab)).json()
    assert numeros and (numeros[0]["vars"] or {}).get("saldo") == "50000"
