"""
comun/numeros.py
================
Convierte cantidades dichas o escritas en espanol a numeros:

    "ciento cincuenta mil"          -> 150000
    "un millón doscientos mil"      -> 1200000
    "veinte mil quinientos pesos"   -> 20500
    "$150.000" / "150 mil" / "1,5 millones" -> 150000 / 150000 / 1500000

Lo usan la captura (montos dictados) y la extraccion de parametros.
"""

import re

from .texto import normalizar

UNIDADES = {
    "cero": 0, "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12,
    "trece": 13, "catorce": 14, "quince": 15, "dieciseis": 16, "diecisiete": 17,
    "dieciocho": 18, "diecinueve": 19, "veinte": 20, "veintiun": 21, "veintiuno": 21,
    "veintiuna": 21, "veintidos": 22, "veintitres": 23, "veinticuatro": 24,
    "veinticinco": 25, "veintiseis": 26, "veintisiete": 27, "veintiocho": 28,
    "veintinueve": 29,
}
DECENAS = {"treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60,
           "setenta": 70, "ochenta": 80, "noventa": 90}
CENTENAS = {"cien": 100, "ciento": 100, "doscientos": 200, "doscientas": 200,
            "trescientos": 300, "trescientas": 300, "cuatrocientos": 400,
            "cuatrocientas": 400, "quinientos": 500, "quinientas": 500,
            "seiscientos": 600, "seiscientas": 600, "setecientos": 700,
            "setecientas": 700, "ochocientos": 800, "ochocientas": 800,
            "novecientos": 900, "novecientas": 900}
PALABRAS = {**UNIDADES, **DECENAS, **CENTENAS}

_MILES = re.compile(r"^\d{1,3}(?:[.,]\d{3})+$")      # 150.000 / 1,200,000
_DECIMAL = re.compile(r"^\d+(?:[.,]\d+)?$")          # 150 / 1,5


def _cifra(token: str):
    t = token.lstrip("$")
    if _MILES.match(t):
        return int(re.sub(r"[.,]", "", t))
    if _DECIMAL.match(t):
        return float(t.replace(",", ".")) if re.search(r"[.,]", t) else int(t)
    return None


def buscar_numeros(texto: str) -> list[int]:
    """Devuelve todas las cantidades encontradas en el texto, en orden."""
    tokens = re.findall(r"\$?\d[\d.,]*\d|\$?\d|[a-zñ]+", normalizar(texto))
    resultados, total, actual, activo = [], 0, 0, False

    def cerrar():
        nonlocal total, actual, activo
        if activo:
            resultados.append(int(round(total + actual)))
        total, actual, activo = 0, 0, False

    for tok in tokens:
        valor = _cifra(tok)
        if valor is None and tok in PALABRAS:
            valor = PALABRAS[tok]
        if valor is not None:
            actual += valor
            activo = True
        elif tok == "y" and activo:
            continue
        elif tok == "mil":
            total += (actual or 1) * 1000
            actual, activo = 0, True
        elif tok in ("millon", "millones"):
            total = (total + (actual or 1)) * 1_000_000
            actual, activo = 0, True
        else:
            cerrar()
    cerrar()
    return resultados


def texto_a_monto(texto: str):
    """La cantidad mayor del texto (la mas probable como monto), o None."""
    numeros = [n for n in buscar_numeros(texto) if n > 0]
    return max(numeros) if numeros else None
