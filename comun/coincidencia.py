"""
comun/coincidencia.py
=====================
Coincidencia por etiqueta: primer criterio para elegir un elemento en pantalla.

La guia de entrenamiento nombra los elementos por su etiqueta visible
("Clave", "Monto a enviar", "Continuar"). Si esa etiqueta aparece en un
elemento, se elige sin depender de ningun modelo; la similitud semantica (o
el LLM) queda como respaldo para comandos libres ("escribir la llave").

Niveles, en orden:
  1. igual      la etiqueta (o la descripcion completa) es igual al objetivo   -> 1.00
  2. contiene   la descripcion contiene el objetivo como frase completa       -> 0.95
  3. incluida   el objetivo contiene la etiqueta del elemento (>= 4 letras)   -> 0.90
"""

from .texto import contiene_frase, normalizar


def _etiqueta(descripcion: str) -> str:
    """La etiqueta es el primer segmento de la descripcion ('Clave · password' -> 'clave')."""
    return normalizar(descripcion.split(" · ")[0]).strip()


def por_etiqueta(objetivo: str, candidatos: list[str]) -> tuple[int, float]:
    """(indice, confianza) por coincidencia textual, o (-1, 0.0) si no hay."""
    o = normalizar(objetivo).strip(" ¿?¡!.,")
    if not o or not candidatos:
        return -1, 0.0
    completos = [normalizar(c).strip() for c in candidatos]
    etiquetas = [_etiqueta(c) for c in candidatos]

    iguales = [i for i in range(len(candidatos)) if o in (etiquetas[i], completos[i])]
    if iguales:
        return iguales[0], 1.0
    contienen = [i for i in range(len(candidatos)) if contiene_frase(completos[i], o)]
    if contienen:
        return min(contienen, key=lambda i: len(candidatos[i])), 0.95
    incluidas = [i for i in range(len(candidatos)) if len(etiquetas[i]) >= 4 and contiene_frase(o, etiquetas[i])]
    if incluidas:
        return max(incluidas, key=lambda i: len(etiquetas[i])), 0.90
    return -1, 0.0
