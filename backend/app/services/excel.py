"""Leer la primera hoja de un .xlsx sin dependencias nuevas.

Un .xlsx es un ZIP de XML (Office Open XML). Para importar clientes basta
con la primera hoja: textos (compartidos o en línea), números y fechas. Se
hace con la librería estándar para no sumar otra dependencia que auditar
(la de Python más usada para esto, openpyxl, trae su propio árbol).

Defensas: tamaño descomprimido acotado (un ZIP de unos KB puede inflarse a
GB), sin DTD (entidades XML) y un tope de filas y columnas.
"""

import io
import posixpath
import re
import zipfile
from datetime import datetime, timedelta
from xml.etree import ElementTree as ET

MAX_DESCOMPRIMIDO = 60 * 1024 * 1024
MAX_COLUMNAS = 200

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
_COLUMNA_RE = re.compile(r"^([A-Z]+)(\d+)$")
# Formatos de número de fábrica que son fechas u horas (ECMA-376, 18.8.30).
_FORMATOS_FECHA = set(range(14, 23)) | {45, 46, 47}


class ErrorExcel(ValueError):
    pass


def es_xlsx(contenido: bytes) -> bool:
    return contenido[:4] == b"PK\x03\x04"


def es_xls_viejo(contenido: bytes) -> bool:
    """Excel 97-2003 (.xls): formato binario que no se lee."""
    return contenido[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _xml(zf: zipfile.ZipFile, nombre: str) -> ET.Element:
    datos = zf.read(nombre)
    if b"<!DOCTYPE" in datos[:2048].upper():
        raise ErrorExcel("El archivo de Excel trae contenido no permitido")
    return ET.fromstring(datos)


def _indice_columna(ref: str) -> int:
    m = _COLUMNA_RE.match(ref)
    if not m:
        return -1
    n = 0
    for letra in m.group(1):
        n = n * 26 + (ord(letra) - 64)
    return n - 1


def _primera_hoja(zf: zipfile.ZipFile) -> str:
    """Ruta de la primera hoja según el libro (no siempre es sheet1.xml)."""
    try:
        libro = _xml(zf, "xl/workbook.xml")
        hoja = libro.find("m:sheets/m:sheet", _NS)
        rid = hoja.get(_REL) if hoja is not None else None
        rels = _xml(zf, "xl/_rels/workbook.xml.rels")
        for rel in rels:
            if rel.get("Id") == rid:
                destino = rel.get("Target", "")
                return destino.lstrip("/") if destino.startswith("/") else posixpath.normpath(posixpath.join("xl", destino))
    except (KeyError, ET.ParseError):
        pass
    return "xl/worksheets/sheet1.xml"


def _estilos_fecha(zf: zipfile.ZipFile) -> set[int]:
    """Índices de estilo de celda (atributo s) que muestran una fecha."""
    try:
        estilos = _xml(zf, "xl/styles.xml")
    except KeyError:
        return set()
    propios = {}
    for f in estilos.findall("m:numFmts/m:numFmt", _NS):
        codigo = re.sub(r'"[^"]*"|\[[^\]]*\]', "", f.get("formatCode", "")).lower()
        propios[int(f.get("numFmtId", "0"))] = bool(re.search(r"[dmy]", codigo)) and "general" not in codigo
    salida = set()
    for i, xf in enumerate(estilos.findall("m:cellXfs/m:xf", _NS)):
        fmt = int(xf.get("numFmtId", "0"))
        if fmt in _FORMATOS_FECHA or propios.get(fmt):
            salida.add(i)
    return salida


def _numero(texto: str) -> str:
    """3001234567 y no 3001234567.0 ni 3.001234567E9: los teléfonos llegan
    como números."""
    try:
        valor = float(texto)
    except ValueError:
        return texto
    if valor.is_integer() and abs(valor) < 1e15:
        return str(int(valor))
    return repr(valor)


def _fecha(texto: str) -> str:
    try:
        serial = float(texto)
    except ValueError:
        return texto
    momento = datetime(1899, 12, 30) + timedelta(days=serial)
    if serial == int(serial):
        return momento.strftime("%Y-%m-%d")
    return (momento + timedelta(seconds=0.5)).strftime("%Y-%m-%d %H:%M")


def leer(contenido: bytes, max_filas: int) -> tuple[list[str], list[list[str]]]:
    """(encabezados, filas) de la primera hoja."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(contenido))
    except zipfile.BadZipFile:
        raise ErrorExcel("El archivo no es un Excel válido (.xlsx)") from None
    with zf:
        if sum(i.file_size for i in zf.infolist()) > MAX_DESCOMPRIMIDO:
            raise ErrorExcel("El Excel es demasiado grande: divídelo o guárdalo como CSV")
        try:
            compartidos = [
                "".join(t.text or "" for t in si.iter(f"{{{_NS['m']}}}t"))
                for si in _xml(zf, "xl/sharedStrings.xml").findall("m:si", _NS)
            ]
        except KeyError:
            compartidos = []
        fechas = _estilos_fecha(zf)
        try:
            hoja = _xml(zf, _primera_hoja(zf))
        except KeyError:
            raise ErrorExcel("El Excel no tiene hojas con datos") from None
        except ET.ParseError:
            raise ErrorExcel("El Excel está dañado") from None

        filas: list[list[str]] = []
        for fila in hoja.findall("m:sheetData/m:row", _NS):
            valores: dict[int, str] = {}
            for siguiente, celda in enumerate(fila.findall("m:c", _NS)):
                col = _indice_columna(celda.get("r", ""))
                col = siguiente if col < 0 else col
                if col >= MAX_COLUMNAS:
                    continue
                tipo = celda.get("t", "n")
                v = celda.find("m:v", _NS)
                texto = v.text if v is not None and v.text is not None else ""
                if tipo == "s":
                    try:
                        texto = compartidos[int(texto)]
                    except (ValueError, IndexError):
                        texto = ""
                elif tipo == "inlineStr":
                    texto = "".join(t.text or "" for t in celda.iter(f"{{{_NS['m']}}}t"))
                elif tipo == "b":
                    texto = "Sí" if texto == "1" else "No"
                elif tipo in ("n", "") and texto:
                    texto = _fecha(texto) if int(celda.get("s", "0") or 0) in fechas else _numero(texto)
                valores[col] = texto.strip()
            if not valores:
                continue
            ancho = max(valores) + 1
            filas.append([valores.get(i, "") for i in range(ancho)])
            if len(filas) > max_filas + 1:
                raise ErrorExcel(f"El archivo pasa de {max_filas:,} filas; divídelo".replace(",", "."))
    if not filas:
        raise ErrorExcel("La primera hoja del Excel está vacía")
    encabezados, *datos = filas
    ancho = len(encabezados)
    return encabezados, [f + [""] * (ancho - len(f)) if len(f) < ancho else f for f in datos]
