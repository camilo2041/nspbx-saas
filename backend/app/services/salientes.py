"""Política de llamadas salientes: UN solo lugar decide qué número puede salir.

Las llamadas salen por tres caminos, y antes cada uno tenía su propia
regla (o ninguna):

- el dialplan, cuando un teléfono marca un número externo;
- el clic-para-llamar del panel (`POST /api/extensions/{id}/call`);
- el marcador de campañas (`workers/dialer.py`).

Los dos últimos hacen `originate` directo a `sofia/gateway/...`: no pasan
por el dialplan, así que el filtro internacional del dialplan no los
alcanzaba. Y el del dialplan miraba el número MARCADO, no el que sale:
una ruta "9." que quita el 9 dejaba salir `9 0044…` como `0044…`.

Acá se define la política una vez, sobre el número que de verdad se le
entrega al proveedor, y se aplica de dos formas que tienen que coincidir:

- `motivo_bloqueo()` en Python, para el clic-para-llamar y las campañas;
- `restriccion_regex()`, que la traduce a una condición del dialplan.

backend/tests/test_salientes.py comprueba que las dos decidan igual para
miles de combinaciones de prefijo y número marcado.
"""

import re
import time
from collections import deque
from dataclasses import dataclass, replace

# Cómo se marca un destino internacional. "011" es el de Norteamérica;
# en Colombia, los prefijos de operador de larga distancia (005, 007,
# 009…) empiezan con "00" y quedan cubiertos por ese.
PREFIJOS_INTERNACIONALES = ("011", "00", "+")

# Sin prefijo internacional, un número de más de esto no es nacional: o es
# un internacional marcado sin prefijo (que algunos proveedores aceptan) o
# un error. En Colombia fijos y celulares tienen 10 dígitos.
LARGO_MAXIMO_NACIONAL = 10

# Códigos que se bloquean SIEMPRE, aunque la empresa tenga internacional:
# redes satelitales e internacionales (870 Inmarsat, 881 GMSS, 882/883
# redes internacionales), tarifa premium internacional (979), costo
# compartido (808) y premium de Norteamérica (1 900). Son el destino
# clásico del fraude por tráfico internacional (IRSF): cobran por minuto
# al que llama y el estafador se lleva una parte.
CODIGOS_BLOQUEADOS = ("870", "881", "882", "883", "979", "808", "1900")

_NUMERO_RE = re.compile(r"^\+?[0-9*#]+$")
_SEPARADORES_RE = re.compile(r"[\s\-().]")
_PAIS_RE = re.compile(r"^[1-9][0-9]{0,3}$")


class SalienteBloqueada(RuntimeError):
    """Una llamada que la política no deja salir.

    `definitiva`: el destino está prohibido (reintentar no sirve). Si es
    False, las salientes están cortadas por un tiempo (interruptor, cupo)."""

    def __init__(self, motivo: str, definitiva: bool = True):
        super().__init__(f"Saliente bloqueada: {motivo}")
        self.motivo = motivo
        self.definitiva = definitiva


@dataclass(frozen=True)
class Politica:
    """Lo que una empresa puede marcar en este momento."""

    permitir_internacional: bool = False
    # Códigos de país permitidos ("57", "1", "34"…). Con internacional
    # activado y la lista vacía, no sale ningún internacional: hay que
    # elegir a qué países, no habilitar el mundo entero.
    paises: tuple[str, ...] = ()
    # Si no es None, las salientes están cortadas y este es el motivo
    # (interruptor de la empresa o de la plataforma, cupo diario agotado).
    bloqueo: str | None = None
    # Llamadas salientes nuevas por segundo (licencia). None = sin tope.
    # Lo aplican el dialplan (limit hash) y el clic para llamar
    # (`exigir_ritmo`); las campañas tienen su propio ritmo (concurrencia).
    cps: int | None = None
    # La empresa limita las salientes de los teléfonos al horario laboral y
    # ahora está fuera de él: solo llaman afuera estas extensiones (guardias).
    # Las campañas no (tienen su franja propia), ni lo que sale sin un
    # teléfono detrás (un desvío del IVR al celular de guardia).
    fuera_de_horario: bool = False
    permitidas_fuera_de_horario: tuple[str, ...] = ()


def paises_desde_texto(texto: str | None) -> tuple[str, ...]:
    """"57, 1,34" -> ("57", "1", "34"). Ignora lo que no sea un código válido."""
    salida = []
    for parte in (texto or "").replace(";", ",").split(","):
        parte = parte.strip().lstrip("+")
        if _PAIS_RE.fullmatch(parte) and parte not in salida:
            salida.append(parte)
    return tuple(salida)


def normalizar(numero: str | None) -> str:
    return _SEPARADORES_RE.sub("", numero or "")


def _prefijo_internacional(numero: str) -> str | None:
    for prefijo in PREFIJOS_INTERNACIONALES:
        if numero.startswith(prefijo):
            return prefijo
    return None


def motivo_bloqueo(numero: str | None, politica: Politica) -> str | None:
    """None si `numero` puede salir; si no, el motivo para mostrar o registrar.

    `numero` es lo que se le entrega al proveedor (después de quitar y
    anteponer dígitos), no lo que se marcó."""
    if politica.bloqueo:
        return politica.bloqueo
    n = normalizar(numero)
    if not n or not _NUMERO_RE.fullmatch(n):
        return "Número no válido"
    prefijo = _prefijo_internacional(n)
    if prefijo is None:
        if len(n) > LARGO_MAXIMO_NACIONAL:
            return (
                f"Número de más de {LARGO_MAXIMO_NACIONAL} dígitos sin prefijo internacional: "
                "los internacionales se marcan con 00, 011 o +"
            )
        return None
    resto = n[len(prefijo):]
    if not resto.isdigit():
        return "Número no válido"
    for codigo in CODIGOS_BLOQUEADOS:
        if resto.startswith(codigo):
            return f"Destino bloqueado siempre (+{codigo}: red satelital o tarifa premium)"
    if not politica.permitir_internacional:
        return "Las llamadas internacionales no están habilitadas para esta empresa"
    if not any(resto.startswith(p) for p in politica.paises):
        return "El país de destino no está entre los permitidos para esta empresa"
    return None


# --- Traducción al dialplan --------------------------------------------
#
# Una ruta del dialplan tiene la forma  ^<dígitos que se quitan>(<resto>)$
# y marca  <antepuesto>$1 . La condición tiene que valer sobre lo que sale
# (antepuesto + $1), pero la expresión solo ve lo marcado. La solución es
# "consumir" el antepuesto, que es un texto fijo: para cada prefijo
# prohibido o requerido se calcula qué le falta a $1 para completarlo
# (la derivada del prefijo respecto del antepuesto), y eso va como una
# condición al comienzo del grupo.


def _derivar(prefijos: list[str], antepuesto: str) -> list[str] | None:
    """Qué tiene que traer el grupo para que `antepuesto + grupo` empiece
    con alguno de `prefijos`.

    Devuelve None si el antepuesto solo ya empieza con uno (se cumple
    siempre, traiga lo que traiga el grupo); una lista vacía si no hay
    forma de cumplirlo."""
    restos: list[str] = []
    for p in prefijos:
        if antepuesto.startswith(p):
            return None
        if p.startswith(antepuesto):
            resto = p[len(antepuesto):]
            if resto not in restos:
                restos.append(resto)
    return restos


def _alternativas(restos: list[str]) -> str:
    return "|".join(re.escape(r) for r in sorted(restos, key=len, reverse=True))


def restriccion_regex(politica: Politica, antepuesto: str = "") -> str | None:
    """Condición (lookahead) que va al comienzo del grupo de captura.

    Devuelve None si con esta política y este antepuesto la ruta no puede
    sacar ninguna llamada: quien genera el dialplan la omite."""
    if politica.bloqueo:
        return None
    antepuesto = normalizar(antepuesto)
    ramas: list[str] = []

    # Nacional: lo que sale no empieza con prefijo internacional y tiene
    # como mucho LARGO_MAXIMO_NACIONAL símbolos.
    internacionales = _derivar(list(PREFIJOS_INTERNACIONALES), antepuesto)
    disponible = LARGO_MAXIMO_NACIONAL - len(antepuesto)
    if internacionales is not None and disponible >= 0 and re.fullmatch(r"[0-9*#]*", antepuesto):
        rama = ""
        if internacionales:
            rama += f"(?!{_alternativas(internacionales)})"
        minimo = 0 if antepuesto else 1
        rama += f"[0-9*#]{{{minimo},{disponible}}}$"
        ramas.append(rama)

    # Internacional: empieza con prefijo + país permitido, y no con un
    # código bloqueado.
    if politica.permitir_internacional and politica.paises:
        buenos = [i + p for i in PREFIJOS_INTERNACIONALES for p in politica.paises]
        malos = [i + c for i in PREFIJOS_INTERNACIONALES for c in CODIGOS_BLOQUEADOS]
        requeridos = _derivar(buenos, antepuesto)
        prohibidos = _derivar(malos, antepuesto)
        if prohibidos is not None and requeridos != []:
            rama = ""
            if requeridos:
                rama += f"(?={_alternativas(requeridos)})"
            if prohibidos:
                rama += f"(?!{_alternativas(prohibidos)})"
            # Lo que sale tiene que ser prefijo + dígitos: después de un "+"
            # o del antepuesto, el grupo trae solo dígitos.
            rama += "[0-9]*$" if antepuesto else r"\+?[0-9]+$"
            ramas.append(rama)

    if not ramas:
        return None
    return "(?=" + "|".join(f"(?:{r})" for r in ramas) + ")"


# --- De dónde sale la política de cada empresa ---------------------------


def politica_desde_ajustes(ajustes, bloqueo: str | None = None) -> Politica:
    """`ajustes` es la fila de SystemSettings de la empresa (o None)."""
    if ajustes is None:
        return Politica(bloqueo=bloqueo)
    return Politica(
        permitir_internacional=bool(ajustes.allow_international),
        paises=paises_desde_texto(getattr(ajustes, "international_countries", "")),
        bloqueo=bloqueo,
    )


MOTIVO_GLOBAL = "Salientes suspendidas en toda la plataforma"
MOTIVO_PLATAFORMA = "Salientes suspendidas por la plataforma para esta empresa"
MOTIVO_EMPRESA = "Salientes pausadas por el administrador de la empresa"


def inicio_del_dia_utc():
    """Medianoche de hoy en la zona del negocio, en UTC naive (la escala de
    `CallLog.started_at`)."""
    from datetime import datetime, timezone

    from app.core.clock import business_tz

    ahora = datetime.now(business_tz())
    medianoche = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
    return medianoche.astimezone(timezone.utc).replace(tzinfo=None)


async def minutos_salientes_hoy(session, tenant_ids) -> dict[int, float]:
    """Minutos hablados hoy por troncal, por empresa. Solo cuentan las
    llamadas que ya terminaron (el CDR llega al colgar); las que están en
    curso las acotan el tope de duración y el de simultáneas."""
    from sqlalchemy import func, select

    from app.models import CallLog

    ids = list(tenant_ids)
    if not ids:
        return {}
    filas = (
        await session.execute(
            select(CallLog.tenant_id, func.coalesce(func.sum(CallLog.billsec), 0))
            .where(
                CallLog.tenant_id.in_(ids),
                CallLog.via_trunk.is_(True),
                CallLog.started_at >= inicio_del_dia_utc(),
            )
            .group_by(CallLog.tenant_id)
        )
    ).all()
    return {tid: segundos / 60 for tid, segundos in filas}


async def politicas(session, tenant_ids) -> dict[int, Politica]:
    """La política vigente de cada empresa pedida.

    En orden, corta las salientes: el interruptor global de la plataforma,
    el de la plataforma para la empresa, la pausa de la propia empresa y el
    cupo diario de minutos de su licencia.

    Sirve con la sesión del dueño (dialplan, marcador) o con la de la
    aplicación (clic-para-llamar): en ese caso RLS solo deja leer la propia
    empresa, y las demás quedan sin ajustes, es decir, con la política más
    restrictiva."""
    from sqlalchemy import select

    from app.core.clock import now_local
    from app.models import Extension, License, PlatformState, SystemSettings, Tenant
    from app.services import horario_marcacion, licensing

    ids = list(tenant_ids)
    if not ids:
        return {}
    estado = await session.get(PlatformState, 1)
    global_cortado = bool(estado and estado.outbound_blocked)
    empresas = {
        t.id: t for t in (await session.execute(select(Tenant).where(Tenant.id.in_(ids)))).scalars().all()
    }
    ajustes = {
        f.tenant_id: f
        for f in (await session.execute(select(SystemSettings).where(SystemSettings.tenant_id.in_(ids)))).scalars().all()
    }
    licencias = {
        lic.tenant_id: lic
        for lic in (await session.execute(select(License).where(License.tenant_id.in_(ids)))).scalars().all()
    }
    usados = await minutos_salientes_hoy(session, ids)

    salida: dict[int, Politica] = {}
    ahora = now_local()
    for tid in ids:
        bloqueo = None
        empresa = empresas.get(tid)
        fila = ajustes.get(tid)
        lic = licencias.get(tid)
        cupo = licensing.limite(lic, "max_outbound_minutes_day") if lic else None
        if global_cortado:
            bloqueo = MOTIVO_GLOBAL
        elif empresa is not None and empresa.outbound_blocked:
            bloqueo = MOTIVO_PLATAFORMA
        elif fila is not None and fila.outbound_paused:
            bloqueo = MOTIVO_EMPRESA
        elif cupo is not None and usados.get(tid, 0) >= cupo:
            bloqueo = f"Cupo diario de {cupo} minutos salientes agotado; se renueva a medianoche"
        # Sin licencia todavía: el tope de la prueba, no "sin tope".
        cps = licensing.limite(lic, "max_outbound_cps") if lic else licensing.PLANES["trial"]["max_outbound_cps"]
        politica = replace(politica_desde_ajustes(fila, bloqueo), cps=cps)
        horario = horario_marcacion.horario_salientes_de(fila)
        if horario is not None and not horario_marcacion.en_horario(horario, ahora):
            permitidas = (await session.execute(
                select(Extension.number).where(
                    Extension.tenant_id == tid, Extension.enabled.is_(True), Extension.outbound_after_hours.is_(True)
                ).order_by(Extension.number)
            )).scalars().all()
            politica = replace(politica, fuera_de_horario=True, permitidas_fuera_de_horario=tuple(permitidas))
        salida[tid] = politica
    return salida


async def politica_de(session, tenant_id: int) -> Politica:
    return (await politicas(session, [tenant_id]))[tenant_id]


# --- Ritmo del clic para llamar ---------------------------------------------
# El dialplan aplica el tope de llamadas por segundo con `limit hash` en
# FreeSWITCH; el clic para llamar hace originate directo y no pasa por ahí,
# así que se aplica acá. En memoria del proceso (hoy el backend es uno solo).

_ULTIMAS: dict[int, deque] = {}


class RitmoExcedido(Exception):
    pass


def exigir_ritmo(tenant_id: int, cps: int | None) -> None:
    """Lanza RitmoExcedido si la empresa ya originó `cps` llamadas en el
    último segundo."""
    if not cps:
        return
    ahora = time.monotonic()
    marcas = _ULTIMAS.setdefault(tenant_id, deque())
    while marcas and marcas[0] <= ahora - 1:
        marcas.popleft()
    if len(marcas) >= cps:
        raise RitmoExcedido(f"Más de {cps} llamadas salientes por segundo; espera un momento")
    marcas.append(ahora)
