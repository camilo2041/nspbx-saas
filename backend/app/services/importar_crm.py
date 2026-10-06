"""Importar contactos desde un CSV o un Excel (.xlsx) (y, si se elige, cargarlos en una campaña).

Flujo: `leer` el archivo → el usuario dice qué columna va a qué campo
(`sugerir_mapeo` propone uno) → `importar` crea o actualiza contactos y
devuelve un reporte con cada fila que no entró y por qué.

Un contacto existente se reconoce por su documento (si la columna viene y
tiene valor) o por la clave de su teléfono (services/crm.py). Los valores
no vacíos del archivo reemplazan a los guardados; los vacíos no borran nada.
"""

import csv
import io
import re
import unicodedata
from dataclasses import dataclass, field

from sqlalchemy import select

from app.core import validacion
from app.models import Contacto
from app.services import crm, excel

MAX_BYTES = 5 * 1024 * 1024
MAX_FILAS = 50_000
MAX_ERRORES_REPORTADOS = 200

DESTINOS_FIJOS = ("nombre", "documento", "telefono", "telefono2", "telefono3", "email", "direccion", "ciudad")
_SEPARADORES_TEL = re.compile(r"[ \-().]")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ErrorDeArchivo(ValueError):
    pass


@dataclass
class Archivo:
    columnas: list[str]
    filas: list[list[str]]


def leer(contenido: bytes) -> Archivo:
    if len(contenido) > MAX_BYTES:
        raise ErrorDeArchivo(f"El archivo pasa de {MAX_BYTES // (1024 * 1024)} MB")
    # Excel (.xlsx) se lee directo: pedir «Guardar como CSV» era un paso
    # más en el que la gente se perdía (y Excel en español lo guarda con ;
    # y en otra codificación). Ver services/excel.py.
    if excel.es_xls_viejo(contenido):
        raise ErrorDeArchivo("Es un Excel antiguo (.xls): ábrelo en Excel y guárdalo como .xlsx o CSV")
    if excel.es_xlsx(contenido):
        try:
            columnas, filas = excel.leer(contenido, MAX_FILAS)
        except excel.ErrorExcel as exc:
            raise ErrorDeArchivo(str(exc)) from None
        columnas = [c.strip() for c in columnas]
        if not any(columnas):
            raise ErrorDeArchivo("La primera fila tiene que traer los nombres de las columnas")
        return Archivo(columnas=columnas, filas=filas)
    try:
        texto = contenido.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Excel en español guarda en Windows-1252 cuando no se elige UTF-8.
        texto = contenido.decode("cp1252", errors="replace")
    if not texto.strip():
        raise ErrorDeArchivo("El archivo está vacío")
    muestra = texto[:4096]
    try:
        dialecto = csv.Sniffer().sniff(muestra, delimiters=",;\t|")
        separador = dialecto.delimiter
    except csv.Error:
        separador = ";" if muestra.count(";") > muestra.count(",") else ","
    lector = csv.reader(io.StringIO(texto), delimiter=separador)
    try:
        columnas = [c.strip() for c in next(lector)]
    except StopIteration:
        raise ErrorDeArchivo("El archivo no tiene encabezados") from None
    if not any(columnas):
        raise ErrorDeArchivo("La primera fila tiene que traer los nombres de las columnas")
    filas = []
    for fila in lector:
        if not any(c.strip() for c in fila):
            continue
        filas.append(fila)
        if len(filas) > MAX_FILAS:
            raise ErrorDeArchivo(f"El archivo pasa de {MAX_FILAS:,} filas; divídelo".replace(",", "."))
    return Archivo(columnas=columnas, filas=filas)


def _simple(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", sin_tildes.lower())


_SINONIMOS = {
    "nombre": ("nombre", "nombres", "cliente", "nombrecompleto", "razonsocial", "name"),
    "documento": ("documento", "cedula", "cc", "nit", "identificacion", "doc", "numerodocumento"),
    "telefono": ("telefono", "celular", "movil", "tel", "phone", "numero", "telefono1", "celular1"),
    "telefono2": ("telefono2", "celular2", "tel2", "otrotelefono", "fijo"),
    "telefono3": ("telefono3", "celular3", "tel3"),
    "email": ("email", "correo", "correoelectronico", "mail", "email1"),
    "direccion": ("direccion", "dir", "address"),
    "ciudad": ("ciudad", "municipio", "city"),
}


def sugerir_mapeo(columnas: list[str], claves_campos: list[str]) -> dict[str, str]:
    """Columna → destino, por el nombre de la columna. Lo que no se
    reconoce queda sin asignar (el usuario decide)."""
    sugerido: dict[str, str] = {}
    usados: set[str] = set()
    for col in columnas:
        s = _simple(col)
        destino = next((d for d, sin in _SINONIMOS.items() if s in sin and d not in usados), None)
        if destino is None and s in {_simple(c) for c in claves_campos}:
            destino = "campo:" + next(c for c in claves_campos if _simple(c) == s)
        if destino:
            sugerido[col] = destino
            usados.add(destino)
    return sugerido


def validar_mapeo(mapeo: dict[str, str], columnas: list[str], claves_campos: set[str]) -> dict[int, str]:
    """Índice de columna → destino. ErrorDeArchivo si algo no cierra."""
    por_indice: dict[int, str] = {}
    vistos: set[str] = set()
    for col, destino in mapeo.items():
        if not destino:
            continue
        if col not in columnas:
            raise ErrorDeArchivo(f"La columna «{col}» no está en el archivo")
        if destino in DESTINOS_FIJOS:
            pass
        elif destino.startswith("campo:"):
            if destino[6:] not in claves_campos:
                raise ErrorDeArchivo(f"«{destino[6:]}» no es un campo de la empresa")
        elif destino.startswith("var:"):
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", destino[4:]):
                raise ErrorDeArchivo(f"Nombre de variable inválido: «{destino[4:]}» (minúsculas, números y _)")
        else:
            raise ErrorDeArchivo(f"Destino desconocido: «{destino}»")
        if destino in vistos:
            raise ErrorDeArchivo(f"Dos columnas van a «{destino}»")
        vistos.add(destino)
        por_indice[columnas.index(col)] = destino
    if "telefono" not in vistos:
        raise ErrorDeArchivo("Falta indicar qué columna es el teléfono")
    return por_indice


def _telefono(valor: str) -> str:
    limpio = _SEPARADORES_TEL.sub("", valor.strip())
    if not validacion.TELEFONO_RE.fullmatch(limpio) or not crm.clave_telefono(limpio):
        raise ValueError(f"teléfono inválido «{valor.strip()[:40]}»")
    return limpio


@dataclass
class Reporte:
    filas: int = 0
    creados: int = 0
    actualizados: int = 0
    errores: list[dict] = field(default_factory=list)
    total_errores: int = 0
    # Para cargar en una campaña: (teléfono, variables, contacto).
    para_campana: list[tuple] = field(default_factory=list)

    def error(self, fila: int, motivo: str) -> None:
        self.total_errores += 1
        if len(self.errores) < MAX_ERRORES_REPORTADOS:
            self.errores.append({"fila": fila, "motivo": motivo})


async def importar(session, tenant_id: int, archivo: Archivo, por_indice: dict[int, str], fuente: str) -> Reporte:
    """Crea o actualiza contactos (sin commit)."""
    defs = await crm.definiciones(session)
    reporte = Reporte(filas=len(archivo.filas))

    # Lo que ya existe, de una vez y no fila por fila.
    idx_tel = next(i for i, d in por_indice.items() if d == "telefono")
    idx_doc = next((i for i, d in por_indice.items() if d == "documento"), None)
    claves = []
    documentos = []
    for fila in archivo.filas:
        if idx_tel < len(fila):
            claves.append(crm.clave_telefono(fila[idx_tel]))
        if idx_doc is not None and idx_doc < len(fila) and fila[idx_doc].strip():
            documentos.append(fila[idx_doc].strip())
    por_clave = await crm.por_claves(session, claves)
    por_documento: dict[str, Contacto] = {}
    unicos = list(dict.fromkeys(documentos))
    for i in range(0, len(unicos), 1000):
        for c in (await session.execute(select(Contacto).where(Contacto.documento.in_(unicos[i:i + 1000])))).scalars():
            por_documento.setdefault(c.documento, c)

    for n, fila in enumerate(archivo.filas, start=2):  # la 1 son los encabezados
        datos: dict[str, str] = {}
        campos: dict[str, str] = {}
        variables: dict[str, str] = {}
        for i, destino in por_indice.items():
            valor = fila[i].strip() if i < len(fila) else ""
            if destino.startswith("campo:"):
                campos[destino[6:]] = valor
            elif destino.startswith("var:"):
                if valor:
                    variables[destino[4:]] = valor[:500]
            else:
                datos[destino] = valor
        try:
            telefono = _telefono(datos.get("telefono", ""))
            extras = [
                {"numero": _telefono(datos[k]), "tipo": "otro"} for k in ("telefono2", "telefono3") if datos.get(k)
            ]
            email = datos.get("email") or None
            if email and not _EMAIL_RE.fullmatch(email):
                raise ValueError(f"correo inválido «{email[:60]}»")
        except ValueError as exc:
            reporte.error(n, str(exc))
            continue

        documento = (datos.get("documento") or "")[:30] or None
        clave = crm.clave_telefono(telefono)
        contacto = (por_documento.get(documento) if documento else None) or por_clave.get(clave)
        try:
            base = dict(contacto.campos or {}) if contacto else {}
            base.update({k: v for k, v in campos.items() if v})
            campos_ok = crm.validar_campos(defs, base)
        except ValueError as exc:
            reporte.error(n, str(exc))
            continue

        if contacto is None:
            contacto = Contacto(tenant_id=tenant_id, telefono=telefono, telefono_clave=clave, fuente=fuente, nombre="")
            session.add(contacto)
            reporte.creados += 1
        else:
            reporte.actualizados += 1
        if datos.get("nombre"):
            contacto.nombre = datos["nombre"][:150]
        if documento:
            contacto.documento = documento
            por_documento[documento] = contacto
        for campo, largo in (("email", 150), ("direccion", 255), ("ciudad", 100)):
            if datos.get(campo):
                setattr(contacto, campo, datos[campo][:largo])
        if extras:
            existentes = {crm.clave_telefono(t.get("numero", "")) for t in (contacto.telefonos or [])}
            nuevos = [t for t in extras if crm.clave_telefono(t["numero"]) not in existentes | {contacto.telefono_clave}]
            contacto.telefonos = [*(contacto.telefonos or []), *nuevos][:5]
        contacto.campos = campos_ok or None
        por_clave.setdefault(clave, contacto)

        if contacto.nombre and "cliente" not in variables:
            variables["cliente"] = contacto.nombre
        reporte.para_campana.append((telefono, variables, contacto))
    return reporte
