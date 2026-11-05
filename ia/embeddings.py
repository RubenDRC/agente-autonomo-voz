"""
ia/embeddings.py
================
Similitud semantica con un modelo de embeddings multilingue (local, sin costo).
El modelo se carga una sola vez y solo cuando se necesita.
"""

import configuracion as cfg

_modelo = None


def _cargar():
    global _modelo
    if _modelo is None:
        from sentence_transformers import SentenceTransformer
        print("[ia] Cargando modelo de embeddings multilingue...")
        _modelo = SentenceTransformer(cfg.MODELO_EMBEDDINGS)
        print("[ia] Modelo de embeddings listo.")
    return _modelo


def similitudes(consulta: str, textos: list[str]) -> list[float]:
    if not textos:
        return []
    from sentence_transformers import util
    modelo = _cargar()
    a = modelo.encode(consulta, convert_to_tensor=True)
    b = modelo.encode(list(textos), convert_to_tensor=True)
    return [float(x) for x in util.cos_sim(a, b)[0]]


def mejor_match(consulta: str, textos: list[str]) -> tuple[int, float]:
    """(indice, similitud) del texto mas parecido a la consulta; (-1, 0.0) si no hay."""
    sims = similitudes(consulta, textos)
    if not sims:
        return -1, 0.0
    i = max(range(len(sims)), key=sims.__getitem__)
    return i, sims[i]
