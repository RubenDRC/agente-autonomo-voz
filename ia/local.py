"""
ia/local.py
===========
Proveedor LOCAL: sin internet, sin costo y sin enviar datos a terceros.

  - Ruta: compara la instruccion con el nombre y las frases de ejemplo de cada
    procedimiento (similitud semantica). Suma una bonificacion si en la
    instruccion aparecen los parametros OBLIGATORIOS de esa ruta (p. ej. una
    llave y un monto son evidencia fuerte de una transferencia).
  - Parametros: reglas de ia/extraccion.py (montos en palabras, llaves,
    contactos, opciones...).

Es la linea base para comparar contra los modelos de lenguaje.
"""

import time

from comun.texto import pct

BONO_PARAMETROS = 0.20   # bonificacion maxima por evidencia de parametros obligatorios

from .base import ProveedorIA, ResultadoIdentificacion
from .embeddings import similitudes
from .extraccion import extraer_parametros


class ProveedorLocal(ProveedorIA):
    tipo = "local"

    def __init__(self, nombre="local"):
        super().__init__(nombre, modelo="embeddings + reglas")

    def identificar(self, instruccion, memoria) -> ResultadoIdentificacion:
        t0 = time.perf_counter()
        textos, duenos = [], []
        for p in memoria.procedimientos:
            for frase in [p["nombre"], *p.get("frases", [])]:
                textos.append(frase)
                duenos.append(p["id"])
        if not textos:
            return ResultadoIdentificacion(None, 0.0, error="la memoria no tiene procedimientos")

        similitud = {}
        for sim, dueno in zip(similitudes(instruccion, textos), duenos):
            similitud[dueno] = max(similitud.get(dueno, -1.0), sim)

        puntaje, extraidos, bonos = {}, {}, {}
        for p in memoria.procedimientos:
            extraidos[p["id"]] = extraer_parametros(instruccion, p, memoria.contactos)
            obligatorios = [q["nombre"] for q in p.get("parametros", []) if q.get("obligatorio")]
            hallados = sum(1 for q in obligatorios if extraidos[p["id"]].get(q) not in (None, ""))
            bonos[p["id"]] = BONO_PARAMETROS * hallados / len(obligatorios) if obligatorios else 0.0
            puntaje[p["id"]] = similitud.get(p["id"], 0.0) + bonos[p["id"]]

        pid = max(puntaje, key=puntaje.get)
        confianza = max(0.0, min(1.0, puntaje[pid]))
        explicacion = f"frase de ejemplo más parecida ({pct(similitud[pid])} %)"
        if bonos[pid]:
            explicacion += f" + datos obligatorios presentes (+{pct(bonos[pid])} %)"
        return ResultadoIdentificacion(
            procedimiento=pid, confianza=confianza, parametros=extraidos[pid], explicacion=explicacion,
            latencia_ms=int((time.perf_counter() - t0) * 1000))
