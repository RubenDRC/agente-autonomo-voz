"""
ia/extraccion.py
================
Extraccion y normalizacion de parametros de una instruccion, por reglas.

  - El proveedor local la usa para extraer los parametros.
  - Los proveedores LLM la usan para NORMALIZAR lo que devuelve el modelo
    (por ejemplo "Lucía" -> "@lucia", "$150.000" -> 150000), de modo que todos
    los modelos entreguen los parametros en el mismo formato.

Tipos de parametro admitidos en la guia de entrenamiento:
  llave  : llave Bre-B (@usuario, correo, numero de 10 digitos o un contacto)
  monto  : cantidad en pesos, en cifras o en palabras
  opcion : uno de los valores permitidos (columna "Valores" de la guia)
  anio   : ano de cuatro digitos
  texto  : texto libre; se ubica despues de su "pista" (p. ej. "descripcion")
"""

import re

from comun.numeros import texto_a_monto
from comun.texto import contiene_frase, limpiar_dictado, normalizar

_EMAIL = re.compile(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}")
_ARROBA_DICHA = re.compile(r"\barroba\s+([a-z0-9_.]+)")
_ARROBA = re.compile(r"(?<![a-z0-9.])@[a-z0-9_.]+")
_NUMERICA = re.compile(r"(?<!\d)(\d{3})[\s.-]?(\d{3})[\s.-]?(\d{4})(?!\d)")
_ANIO = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")


# ------------------------------------------------------------------ por tipo

def resolver_llave(texto: str, contactos: list) -> tuple:
    """Devuelve (llave, (inicio, fin)) o (None, None)."""
    t = normalizar(texto)
    reglas = ((_EMAIL, lambda m: m.group(0)),
              (_ARROBA_DICHA, lambda m: "@" + m.group(1)),
              (_ARROBA, lambda m: m.group(0)),
              (_NUMERICA, lambda m: "".join(m.groups())))
    for regex, valor in reglas:
        m = regex.search(t)
        if m:
            return valor(m).rstrip("."), m.span()
    # Contactos: nombre o alias, del mas largo al mas corto ("mi hijo" antes que "hijo")
    pares = sorted(((normalizar(a), c) for c in contactos
                    for a in [c["nombre"], *c.get("alias", [])] if a),
                   key=lambda par: -len(par[0]))
    for alias, contacto in pares:
        m = re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", t)
        if m:
            return contacto["llave"], m.span()
    return None, None


def resolver_opcion(texto: str, valores: list):
    """Busca la etiqueta (o el valor) mas larga que aparezca en el texto."""
    t = normalizar(texto)
    pares = sorted(((etq, v["valor"]) for v in valores
                    for etq in [*v.get("etiquetas", []), v["valor"]] if etq),
                   key=lambda par: -len(normalizar(par[0])))
    for etiqueta, valor in pares:
        if contiene_frase(t, etiqueta):
            return valor
    return None


def resolver_texto(texto: str, pista: str):
    """Texto que sigue a la pista. Pista: alternativas separadas por '|'."""
    if not pista:
        return None
    alternativas = "|".join(re.escape(normalizar(a).strip()) for a in pista.split("|") if a.strip())
    t = normalizar(texto)
    m = re.search(rf"(?:{alternativas})\s*(?:de|:|es)?\s*(.+)$", t)
    if not m:
        return None
    ini, fin = m.span(1)
    # Si la normalizacion no cambio la longitud, se conserva el texto original (tildes, mayusculas)
    fuente = texto if len(texto) == len(t) else t
    valor = fuente[ini:fin].strip().strip("«»\"'.,;:¿?¡! ")
    return valor or None


def valor_por_defecto(param: dict):
    defecto = param.get("defecto")
    if not defecto:
        return None
    if param["tipo"] == "opcion":
        return resolver_opcion(defecto, param.get("valores", [])) or defecto
    return defecto


# ------------------------------------------------------------------ extraccion

def extraer_parametros(instruccion: str, procedimiento: dict, contactos: list) -> dict:
    """Extrae todos los parametros declarados de un procedimiento."""
    resultado = {}
    restante = instruccion
    # La llave va primero: asi sus digitos no se confunden con el monto.
    for p in procedimiento.get("parametros", []):
        if p["tipo"] == "llave":
            llave, span = resolver_llave(instruccion, contactos)
            if llave:
                resultado[p["nombre"]] = llave
                t = normalizar(instruccion)
                restante = t[:span[0]] + " " + t[span[1]:]
    for p in procedimiento.get("parametros", []):
        if p["nombre"] in resultado:
            continue
        valor = extraer_parametro(p, instruccion, contactos, restante=restante, respuesta_directa=False)
        if valor not in (None, ""):
            resultado[p["nombre"]] = valor
    return resultado


def extraer_parametro(param: dict, texto: str, contactos: list, restante=None, respuesta_directa=True):
    """Extrae un parametro. Con respuesta_directa=True el texto es la respuesta del
    usuario a una pregunta concreta (p. ej. '¿Cuánto quieres enviar?')."""
    tipo = param["tipo"]
    if tipo == "llave":
        return resolver_llave(limpiar_dictado(texto) if respuesta_directa else texto, contactos)[0]
    if tipo == "monto":
        return texto_a_monto(restante if restante is not None else texto)
    if tipo == "opcion":
        return resolver_opcion(texto, param.get("valores", []))
    if tipo == "anio":
        m = _ANIO.search(texto)
        return m.group(1) if m else None
    if tipo == "texto":
        valor = resolver_texto(texto, param.get("pista", ""))
        if valor is None and respuesta_directa:
            valor = texto.strip().strip("«»\"'.,;:¿?¡! ") or None
        return valor
    return None


def normalizar_parametros(procedimiento: dict, crudos: dict, contactos: list) -> dict:
    """Lleva los parametros propuestos por un modelo al formato comun."""
    resultado = {}
    declarados = {p["nombre"]: p for p in procedimiento.get("parametros", [])}
    for nombre, valor in (crudos or {}).items():
        p = declarados.get(nombre)
        if p is None or valor in (None, "", [], {}):
            continue
        texto = str(valor).strip()
        if p["tipo"] == "monto":
            v = int(valor) if isinstance(valor, (int, float)) and not isinstance(valor, bool) else texto_a_monto(texto)
        elif p["tipo"] == "llave":
            v = resolver_llave(texto, contactos)[0] or normalizar(texto).replace(" ", "")
        elif p["tipo"] == "opcion":
            v = resolver_opcion(texto, p.get("valores", []))
        elif p["tipo"] == "anio":
            m = _ANIO.search(texto)
            v = m.group(1) if m else None
        else:
            v = texto
        if v not in (None, ""):
            resultado[nombre] = v
    return resultado
