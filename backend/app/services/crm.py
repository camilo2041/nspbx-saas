"""CRM: contactos, campos propios y lista de no llamar.

El teléfono identifica al cliente. Se compara por su CLAVE: los últimos 10
dígitos ("+57 300-123 4567", "573001234567" y "3001234567" son el mismo).
Diez porque es el largo de un número colombiano sin indicativo; un número
más corto (una extensión) se compara entero.
"""

import re
from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy import func, or_, select

from app.models import CampoContacto, Contacto, NoLlamar

TIPOS_CAMPO = ("texto", "numero", "fecha", "opciones", "si_no")
CLAVE_CAMPO_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_LARGO_CLAVE = 10


def clave_telefono(numero: str | None) -> str:
    return re.sub(r"\D", "", numero or "")[-_LARGO_CLAVE:]


def clave_sql(columna):
    """La misma clave calculada en la base, para cruzar con columnas que
    guardan el número tal cual llegó (historial, deudas, citas)."""
    return func.right(func.regexp_replace(columna, r"\D", "", "g"), _LARGO_CLAVE)


# --- Campos propios ---------------------------------------------------------


async def definiciones(session) -> dict[str, CampoContacto]:
    filas = (await session.execute(select(CampoContacto).order_by(CampoContacto.orden, CampoContacto.id))).scalars()
    return {c.clave: c for c in filas}


def _valor(campo: CampoContacto, valor):
    """Valor ya convertido al tipo del campo, o ValueError con el motivo."""
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return None
    if campo.tipo == "texto":
        texto = str(valor).strip()
        if len(texto) > 500:
            raise ValueError("máximo 500 caracteres")
        return texto
    if campo.tipo == "numero":
        if isinstance(valor, bool):
            raise ValueError("tiene que ser un número")
        try:
            return float(str(valor).replace(",", "").replace("$", "").strip())
        except ValueError:
            raise ValueError("tiene que ser un número") from None
    if campo.tipo == "fecha":
        try:
            return date.fromisoformat(str(valor).strip()[:10]).isoformat()
        except ValueError:
            raise ValueError("fecha en formato AAAA-MM-DD") from None
    if campo.tipo == "opciones":
        texto = str(valor).strip()
        if texto not in (campo.opciones or []):
            raise ValueError(f"tiene que ser una de: {', '.join(campo.opciones or [])}")
        return texto
    if campo.tipo == "si_no":
        if isinstance(valor, bool):
            return valor
        texto = str(valor).strip().lower()
        if texto in ("si", "sí", "s", "true", "1", "yes", "x"):
            return True
        if texto in ("no", "n", "false", "0"):
            return False
        raise ValueError("sí o no")
    raise ValueError("tipo desconocido")


def validar_campos(defs: dict[str, CampoContacto], valores: dict | None, exigir_obligatorios: bool = True) -> dict:
    """Campos propios validados. Un campo que la empresa no definió es un
    error, no se guarda en silencio: así no se acumula basura en el JSON."""
    valores = valores or {}
    errores = []
    limpio = {}
    for clave, valor in valores.items():
        campo = defs.get(clave)
        if campo is None:
            errores.append(f"«{clave}» no es un campo de la empresa")
            continue
        try:
            convertido = _valor(campo, valor)
        except ValueError as exc:
            errores.append(f"{campo.nombre}: {exc}")
            continue
        if convertido is not None:
            limpio[clave] = convertido
    if exigir_obligatorios:
        for campo in defs.values():
            if campo.obligatorio and limpio.get(campo.clave) is None:
                errores.append(f"{campo.nombre} es obligatorio")
    if errores:
        raise ValueError("; ".join(errores))
    return limpio


# --- Contactos ----------------------------------------------------------------


async def por_claves(session, claves: list[str]) -> dict[str, Contacto]:
    """Contactos de la empresa de la sesión por clave de teléfono."""
    encontrados: dict[str, Contacto] = {}
    unicas = list(dict.fromkeys(c for c in claves if c))
    for i in range(0, len(unicas), 1000):
        filas = (
            await session.execute(
                select(Contacto).where(Contacto.telefono_clave.in_(unicas[i:i + 1000])).order_by(Contacto.id)
            )
        ).scalars()
        for c in filas:
            encontrados.setdefault(c.telefono_clave, c)
    return encontrados


async def asegurar(session, tenant_id: int, telefono: str, nombre: str | None, fuente: str,
                   cache: dict[str, Contacto]) -> Contacto | None:
    """El contacto de este teléfono; lo crea si no existe. `cache` (clave →
    contacto) evita una consulta por fila en cargas grandes: llenarlo antes
    con `por_claves`."""
    clave = clave_telefono(telefono)
    if not clave:
        return None
    contacto = cache.get(clave)
    if contacto is None:
        contacto = Contacto(tenant_id=tenant_id, nombre=(nombre or "")[:150], telefono=telefono[:40],
                            telefono_clave=clave, fuente=fuente)
        session.add(contacto)
        cache[clave] = contacto
    elif nombre and not contacto.nombre:
        contacto.nombre = nombre[:150]
    return contacto


def nombre_de_variables(variables: dict | None) -> str | None:
    bajas = {str(k).lower(): v for k, v in (variables or {}).items()}
    valor = bajas.get("cliente") or bajas.get("nombre")
    return str(valor).strip() if valor else None


def telefonos_de(contacto: Contacto) -> list[str]:
    extra = [t.get("numero", "") for t in (contacto.telefonos or []) if isinstance(t, dict)]
    return [n for n in [contacto.telefono, *extra] if n]


def condicion_historial(columnas, contacto: Contacto):
    """WHERE para encontrar en otra tabla lo que es de este contacto, por
    cualquiera de sus teléfonos."""
    claves = [c for c in {clave_telefono(t) for t in telefonos_de(contacto)} if c]
    if not claves:
        return None
    return or_(*[clave_sql(col).in_(claves) for col in columnas])


# --- No llamar ------------------------------------------------------------------


def vigente_no_llamar(ahora: datetime | None = None):
    ahora = ahora or datetime.utcnow()
    return or_(NoLlamar.hasta.is_(None), NoLlamar.hasta > ahora)


async def en_no_llamar(session, telefono: str) -> NoLlamar | None:
    clave = clave_telefono(telefono)
    if not clave:
        return None
    return (
        await session.execute(select(NoLlamar).where(NoLlamar.telefono_clave == clave, vigente_no_llamar()))
    ).scalar_one_or_none()


def error_422(mensaje: str) -> HTTPException:
    return HTTPException(status_code=422, detail=mensaje)
