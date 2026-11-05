"""
comun/texto.py
==============
Utilidades de texto compartidas por todos los modulos.
"""

import re
import unicodedata


def normalizar(texto: str) -> str:
    """Minusculas y sin tildes: 'Contraseña Dinámica' -> 'contrasena dinamica'."""
    sin_tildes = unicodedata.normalize("NFKD", str(texto))
    return "".join(c for c in sin_tildes if not unicodedata.combining(c)).lower()


def pct(score: float) -> float:
    """Similitud o confianza expresada en porcentaje (no es una probabilidad)."""
    return round(float(score) * 100, 1)


def slug(texto: str) -> str:
    """'Transferencia Bre-B' -> 'transferencia_bre_b'."""
    return re.sub(r"[^a-z0-9]+", "_", normalizar(texto)).strip("_")


def limpiar_dictado(texto: str) -> str:
    """Ajusta lo que devuelve el reconocimiento de voz antes de escribirlo:
    'Arroba Lucía.' -> '@lucia'   |   '310 555 8842' -> '3105558842'
    '150.000'       -> '150000'   |   quita puntuacion al inicio y al final."""
    t = texto.strip().strip("¿¡.,;:!? ")
    t = re.sub(r"\barroba\s*", "@", t, flags=re.IGNORECASE)
    t = re.sub(r"(?<=\d)[\s.](?=\d)", "", t)                 # une grupos de digitos
    t = re.sub(r"@\S+", lambda m: normalizar(m.group()), t)  # llaves sin tildes
    return t


def contiene_frase(texto_normalizado: str, frase: str) -> bool:
    """True si 'frase' aparece como palabra(s) completa(s) dentro del texto."""
    f = normalizar(frase).strip()
    return bool(f) and re.search(rf"(?<![a-z0-9]){re.escape(f)}(?![a-z0-9])", texto_normalizado) is not None
