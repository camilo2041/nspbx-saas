"""Números en palabras — para que el texto a voz los lea bien.

Un monto escrito "350.000" es un problema: varios motores de TTS (medido
con Deepgram) lo leen como DECIMAL y dicen "trescientos cincuenta" — se
pierde el "mil". Pasar el número a palabras ("trescientos cincuenta mil")
garantiza que la voz diga lo que se debe, sin depender de cómo el TTS
interprete separadores."""

# 0-9
_UNIDADES = [
    "cero", "uno", "dos", "tres", "cuatro",
    "cinco", "seis", "siete", "ocho", "nueve",
]
# 10-29 tienen formas propias.
_ESPECIALES = {
    10: "diez", 11: "once", 12: "doce", 13: "trece", 14: "catorce",
    15: "quince", 16: "dieciséis", 17: "diecisiete", 18: "dieciocho",
    19: "diecinueve", 20: "veinte", 21: "veintiuno", 22: "veintidós",
    23: "veintitrés", 24: "veinticuatro", 25: "veinticinco", 26: "veintiséis",
    27: "veintisiete", 28: "veintiocho", 29: "veintinueve",
}
_DECENAS = ["", "", "veinte", "treinta", "cuarenta", "cincuenta", "sesenta", "setenta", "ochenta", "noventa"]
_CENTENAS = [
    "", "ciento", "doscientos", "trescientos", "cuatrocientos", "quinientos",
    "seiscientos", "setecientos", "ochocientos", "novecientos",
]


def _tres_cifras(n: int) -> str:
    """0 <= n < 1000 en palabras."""
    if n == 0:
        return ""
    if n < 30:
        if n in _ESPECIALES:
            return _ESPECIALES[n]
        d, u = n // 10, n % 10
        return _DECENAS[d] + (f" y {_UNIDADES[u]}" if u else "")
    if n < 100:
        d, u = n // 10, n % 10
        return _DECENAS[d] + (f" y {_UNIDADES[u]}" if u else "")
    if n == 100:
        return "cien"
    c, resto = n // 100, n % 100
    return _CENTENAS[c] + (f" {_tres_cifras(resto)}" if resto else "")


def numero_a_palabras(n: int | float) -> str:
    """350000 -> 'trescientos cincuenta mil'. Acepta floats de montos."""
    n = abs(int(round(float(n))))
    if n == 0:
        return "cero"
    partes: list[str] = []
    if n >= 1_000_000:
        millones, n = divmod(n, 1_000_000)
        if millones == 1:
            partes.append("un millón")
        else:
            partes.append(f"{_tres_cifras(millones)} millones")
    if n >= 1_000:
        miles, n = divmod(n, 1_000)
        if miles == 1:
            partes.append("mil")
        else:
            partes.append(f"{_tres_cifras(miles)} mil")
    if n > 0:
        partes.append(_tres_cifras(n))
    return " ".join(partes)
