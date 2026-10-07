"""Cuándo pueden marcar las campañas.

La Ley 2300 de 2023 ("Dejen de fregar") limita el contacto de cobranza a
lunes a viernes de 7:00 a 19:00 y sábados de 8:00 a 15:00, nunca domingos
ni festivos. Un voizbot de cobranza que marca fuera de esa franja expone a
la empresa a sanciones de la Superintendencia de Industria y Comercio.

- Cada empresa define su franja (Ajustes); por defecto es la de la ley.
- Las campañas de cobranza quedan SIEMPRE dentro de la franja legal: la
  empresa puede achicarla, no ampliarla.
- Las demás (confirmar citas, avisos) usan la franja de la empresa tal cual.

Las horas son las del negocio (`core.clock.now_local`, zona de Ajustes del
servidor). Una llamada que empezó antes del cierre no se corta: lo que se
frena es marcar la siguiente.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import re

# Franja legal de la Ley 2300 de 2023, art. 3.
LEGAL_LV = (time(7, 0), time(19, 0))
LEGAL_SABADO = (time(8, 0), time(15, 0))

_FRANJA_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)-([01]\d|2[0-4]):([0-5]\d)$")
SABADO, DOMINGO = 5, 6


def leer_franja(texto: str | None) -> tuple[time, time] | None:
    """"07:00-19:00" -> (07:00, 19:00). Vacío o "-" = no se marca ese día."""
    texto = (texto or "").strip()
    if not texto or texto == "-":
        return None
    m = _FRANJA_RE.fullmatch(texto)
    if not m:
        raise ValueError("La franja va como HH:MM-HH:MM, por ejemplo 07:00-19:00")
    desde = time(int(m[1]), int(m[2]))
    hasta = time(23, 59, 59) if m[3] == "24" else time(int(m[3]), int(m[4]))
    if hasta <= desde:
        raise ValueError("La hora final tiene que ser posterior a la inicial")
    return desde, hasta


# --- Festivos de Colombia (Ley 51 de 1983) ------------------------------------


def _pascua(anio: int) -> date:
    """Domingo de Pascua (algoritmo de Butcher/Meeus, calendario gregoriano)."""
    a, b, c = anio % 19, anio // 100, anio % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = (h + l - 7 * m + 114) % 31 + 1
    return date(anio, mes, dia)


def _al_lunes(d: date) -> date:
    """Ley Emiliani: el festivo se corre al lunes siguiente (si no cae en lunes)."""
    return d + timedelta(days=(7 - d.weekday()) % 7)


def festivos(anio: int) -> set[date]:
    fijos = {date(anio, 1, 1), date(anio, 5, 1), date(anio, 7, 20), date(anio, 8, 7),
             date(anio, 12, 8), date(anio, 12, 25)}
    trasladables = {_al_lunes(date(anio, m, d)) for m, d in
                    ((1, 6), (3, 19), (6, 29), (8, 15), (10, 12), (11, 1), (11, 11))}
    p = _pascua(anio)
    # Jueves y Viernes Santo no se trasladan; Ascensión, Corpus Christi y
    # Sagrado Corazón caen en lunes por la misma ley.
    pascuales = {p - timedelta(days=3), p - timedelta(days=2),
                 p + timedelta(days=43), p + timedelta(days=64), p + timedelta(days=71)}
    return fijos | trasladables | pascuales


def es_festivo(d: date) -> bool:
    return d in festivos(d.year)


# --- La franja de un día -------------------------------------------------------


@dataclass(frozen=True)
class Horario:
    lunes_a_viernes: tuple[time, time] | None = LEGAL_LV
    sabado: tuple[time, time] | None = LEGAL_SABADO
    domingos_y_festivos: bool = False


LEGAL = Horario()


def horario_de(ajustes) -> Horario:
    """El de la empresa (Ajustes). Si algo está mal guardado, el legal."""
    if ajustes is None:
        return LEGAL
    try:
        return Horario(
            lunes_a_viernes=leer_franja(getattr(ajustes, "campaign_hours_weekdays", None) or "07:00-19:00"),
            sabado=leer_franja(getattr(ajustes, "campaign_hours_saturday", None) or "08:00-15:00"),
            domingos_y_festivos=bool(getattr(ajustes, "campaign_sundays_holidays", False)),
        )
    except ValueError:
        return LEGAL


def _franja_del_dia(h: Horario, d: date) -> tuple[time, time] | None:
    if d.weekday() == DOMINGO or es_festivo(d):
        # Domingos y festivos: si la empresa los permite, con la franja del sábado.
        return h.sabado if h.domingos_y_festivos else None
    return h.sabado if d.weekday() == SABADO else h.lunes_a_viernes


def _interseccion(a, b):
    if a is None or b is None:
        return None
    desde, hasta = max(a[0], b[0]), min(a[1], b[1])
    return (desde, hasta) if desde < hasta else None


def franja(ajustes, intencion: str | None, d: date) -> tuple[time, time] | None:
    """Desde y hasta cuándo se puede marcar ese día, o None si no se marca.
    Una fecha especial de la empresa (services/festivos.py) la cierra o la
    acorta."""
    from app.services import festivos

    propia = _franja_del_dia(horario_de(ajustes), d)
    if (intencion or "").strip().lower() == "cobranza":
        propia = _interseccion(propia, _franja_del_dia(LEGAL, d))
    especial = festivos.especial(getattr(ajustes, "tenant_id", None), d)
    if especial is not None:
        return _interseccion(propia, especial[1])
    return propia


def puede_marcar(ajustes, intencion: str | None, ahora: datetime) -> bool:
    f = franja(ajustes, intencion, ahora.date())
    return f is not None and f[0] <= ahora.time() < f[1]


# --- Horario laboral de las salientes de los teléfonos ---------------------------
# Opcional por empresa (Ajustes): fuera de él solo llaman afuera las
# extensiones con permiso (ver services/salientes.py). Usa los mismos
# festivos y la misma lógica de franjas que las campañas.


def horario_salientes_de(ajustes) -> Horario | None:
    """None = la empresa no limita las salientes por horario."""
    if ajustes is None or not getattr(ajustes, "outbound_hours_enabled", False):
        return None
    try:
        return Horario(
            lunes_a_viernes=leer_franja(getattr(ajustes, "outbound_hours_weekdays", None) or "07:00-19:00"),
            sabado=leer_franja(getattr(ajustes, "outbound_hours_saturday", None) or "08:00-13:00"),
            domingos_y_festivos=bool(getattr(ajustes, "outbound_hours_sundays_holidays", False)),
        )
    except ValueError:
        # Mal guardado: se trata como "fuera de horario" siempre, no como
        # "sin límite" (fallo seguro).
        return Horario(lunes_a_viernes=None, sabado=None)


def en_horario(h: Horario, ahora: datetime) -> bool:
    f = _franja_del_dia(h, ahora.date())
    return f is not None and f[0] <= ahora.time() < f[1]


def proxima_apertura(ajustes, intencion: str | None, ahora: datetime) -> datetime | None:
    """Cuándo vuelve a poder marcar (para decírselo a la empresa)."""
    if puede_marcar(ajustes, intencion, ahora):
        return ahora
    for dias in range(0, 15):
        d = ahora.date() + timedelta(days=dias)
        f = franja(ajustes, intencion, d)
        if f is None:
            continue
        inicio = datetime.combine(d, f[0])
        if inicio > ahora:
            return inicio
    return None
