"""
conocimiento/lector_word.py
===========================
Lee una guia de procedimientos en Word (.docx) y la convierte en rutas que el
agente puede ejecutar. Formato esperado (ver guias/Guia_Banco_Sandbox.docx):

  Aplicativo: <nombre>                 (parrafo al inicio)
  Origen: http://localhost:5173        (parrafo al inicio)

  [Titulo] Contactos
     Tabla: Nombre | Alias | Llave

  [Titulo 1] Procedimiento: <Nombre>
     Identificador: <id>               (opcional)
     Descripción: <texto>
     Requiere sesión: Sí / No
     [Titulo 2] Frases de ejemplo      + lista con viñetas
     Tabla: Parámetro | Tipo | Obligatorio | Valores | Por defecto | Pregunta | Pista
     Tabla: # | Acción | Elemento | Valor | Confirmar | Resultado esperado

Las tablas se reconocen por su encabezado, asi que el orden de las columnas y
los estilos visuales pueden variar.
"""

import re

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from comun.texto import normalizar, slug

ACCIONES = {"ir_a", "clic", "escribir", "seleccionar", "leer", "esperar"}
SINONIMOS_ACCION = {"ir a": "ir_a", "navegar": "ir_a", "click": "clic", "pulsar": "clic",
                    "seleccionar opcion": "seleccionar", "elegir": "seleccionar",
                    "consultar": "leer", "espera": "esperar"}
TIPOS = {"llave", "monto", "opcion", "anio", "texto"}
VACIO = {"", "-", "—", "–", "n/a", "na", "ninguno", "ninguna"}


# ------------------------------------------------------------------ utilidades de docx

def _bloques(doc):
    """Recorre parrafos y tablas en el orden en que aparecen en el documento."""
    for hijo in doc.element.body.iterchildren():
        if hijo.tag.endswith("}p"):
            yield Paragraph(hijo, doc)
        elif hijo.tag.endswith("}tbl"):
            yield Table(hijo, doc)


def _es_titulo(p) -> bool:
    nombre = normalizar(p.style.name if p.style is not None else "")
    return "heading" in nombre or "titulo" in nombre or nombre == "title"


def _es_vineta(p) -> bool:
    ppr = p._p.pPr
    estilo = normalizar(p.style.name if p.style is not None else "")
    return ((ppr is not None and ppr.numPr is not None) or "list" in estilo or "lista" in estilo
            or p.text.strip().startswith(("-", "•", "*")))


def _campo(texto: str, nombre: str):
    """'Descripción: Envía dinero' con nombre 'descripcion' -> 'Envía dinero'."""
    if ":" not in texto:
        return None
    clave, valor = texto.split(":", 1)
    return valor.strip() if normalizar(clave).strip() == nombre else None


def _si(texto: str) -> bool:
    return normalizar(texto).strip() in {"si", "s", "x", "true", "1", "yes", "obligatorio"}


def _vacio(texto: str) -> bool:
    return normalizar(texto).strip() in VACIO


def _filas(tabla) -> list[list[str]]:
    return [[c.text.strip() for c in fila.cells] for fila in tabla.rows]


def _columna(encabezado: list[str], *prefijos) -> int:
    for i, c in enumerate(encabezado):
        if any(c.startswith(p) for p in prefijos):
            return i
    return -1


def _celda(fila, i) -> str:
    return fila[i].strip() if 0 <= i < len(fila) else ""


def _valores(texto: str) -> list[dict]:
    """'ahorros=Cuenta de ahorros; corriente/cte=Cuenta corriente' ->
    [{'etiquetas': ['ahorros'], 'valor': 'Cuenta de ahorros'}, ...]"""
    resultado = []
    for parte in re.split(r"[;|\n]", texto or ""):
        parte = parte.strip()
        if not parte:
            continue
        if "=" in parte:
            etiquetas, valor = parte.split("=", 1)
        else:
            etiquetas, valor = parte, parte
        resultado.append({"etiquetas": [e.strip() for e in etiquetas.split("/") if e.strip()],
                          "valor": valor.strip()})
    return resultado


# ------------------------------------------------------------------ lectura

def leer_guia(ruta) -> tuple[dict, list[str], list[str]]:
    """Devuelve (guia, errores, advertencias)."""
    doc = Document(str(ruta))
    guia = {"aplicativo": "", "origen": "", "contactos": [], "procedimientos": []}
    actual, seccion = None, None

    for bloque in _bloques(doc):
        if isinstance(bloque, Paragraph):
            texto = bloque.text.strip()
            if not texto:
                continue
            if _es_titulo(bloque):
                n = normalizar(texto)
                if n.startswith("procedimiento"):
                    nombre = texto.split(":", 1)[1].strip() if ":" in texto else texto
                    actual = {"id": slug(nombre), "nombre": nombre, "descripcion": "",
                              "requiere_sesion": False, "frases": [], "parametros": [], "pasos": []}
                    guia["procedimientos"].append(actual)
                    seccion = None
                elif n.startswith("contactos"):
                    actual, seccion = None, "contactos"
                elif "frases" in n and actual is not None:
                    seccion = "frases"
                else:
                    seccion = None
                continue

            if actual is None:
                for clave in ("aplicativo", "origen"):
                    valor = _campo(texto, clave)
                    if valor:
                        guia[clave] = valor
                continue

            if (valor := _campo(texto, "identificador")) is not None:
                actual["id"] = slug(valor) or actual["id"]
            elif (valor := _campo(texto, "descripcion")) is not None:
                actual["descripcion"] = valor
            elif (valor := _campo(texto, "requiere sesion")) is not None:
                actual["requiere_sesion"] = _si(valor)
            elif (valor := _campo(texto, "frases de ejemplo")) is not None:
                actual["frases"] += [f.strip() for f in re.split(r"[;|]", valor) if f.strip()]
            elif seccion == "frases" and _es_vineta(bloque):
                actual["frases"].append(texto.lstrip("-•* ").strip().strip("«»\"'"))
            continue

        # ---- tablas
        filas = _filas(bloque)
        if len(filas) < 2:
            continue
        enc = [normalizar(c) for c in filas[0]]

        if _columna(enc, "parametro") != -1 and actual is not None:
            c = {k: _columna(enc, *p) for k, p in {
                "nombre": ("parametro",), "tipo": ("tipo",), "obligatorio": ("obligatorio",),
                "valores": ("valores",), "defecto": ("por defecto", "defecto"),
                "pregunta": ("pregunta",), "pista": ("pista",)}.items()}
            for fila in filas[1:]:
                nombre = slug(_celda(fila, c["nombre"]))
                if not nombre:
                    continue
                actual["parametros"].append({
                    "nombre": nombre,
                    "tipo": {"ano": "anio", "numero_de_ano": "anio"}.get(
                        slug(_celda(fila, c["tipo"])), slug(_celda(fila, c["tipo"]))),
                    "obligatorio": _si(_celda(fila, c["obligatorio"])),
                    "valores": _valores(_celda(fila, c["valores"])) if not _vacio(_celda(fila, c["valores"])) else [],
                    "defecto": None if _vacio(_celda(fila, c["defecto"])) else _celda(fila, c["defecto"]),
                    "pregunta": None if _vacio(_celda(fila, c["pregunta"])) else _celda(fila, c["pregunta"]),
                    "pista": None if _vacio(_celda(fila, c["pista"])) else _celda(fila, c["pista"]),
                })

        elif _columna(enc, "accion") != -1 and actual is not None:
            c = {k: _columna(enc, *p) for k, p in {
                "n": ("#", "n", "paso"), "accion": ("accion",), "objetivo": ("elemento", "objetivo"),
                "valor": ("valor",), "confirmar": ("confirmar",), "esperado": ("resultado", "esperado")}.items()}
            for i, fila in enumerate(filas[1:], start=1):
                accion = normalizar(_celda(fila, c["accion"])).strip()
                if not accion:
                    continue
                accion = SINONIMOS_ACCION.get(accion, accion.replace(" ", "_"))
                valor = _celda(fila, c["valor"])
                actual["pasos"].append({
                    "n": len(actual["pasos"]) + 1,
                    "accion": accion,
                    "objetivo": _celda(fila, c["objetivo"]),
                    "valor": None if _vacio(valor) else valor,
                    "confirmar": _si(_celda(fila, c["confirmar"])),
                    "esperado": _celda(fila, c["esperado"]),
                })

        elif seccion == "contactos" or ("llave" in enc and _columna(enc, "nombre") != -1):
            cn, ca, cl = _columna(enc, "nombre"), _columna(enc, "alias"), _columna(enc, "llave")
            for fila in filas[1:]:
                if _celda(fila, cn) and _celda(fila, cl):
                    guia["contactos"].append({
                        "nombre": _celda(fila, cn),
                        "alias": [a.strip() for a in re.split(r"[,;]", _celda(fila, ca)) if a.strip()],
                        "llave": _celda(fila, cl).strip(),
                    })

    errores, advertencias = validar(guia)
    return guia, errores, advertencias


def validar(guia: dict) -> tuple[list[str], list[str]]:
    errores, advertencias = [], []
    if not guia["procedimientos"]:
        errores.append("La guía no tiene procedimientos (títulos «Procedimiento: …»).")
    if not guia["origen"]:
        advertencias.append("Falta el párrafo «Origen: …» al inicio de la guía.")
    vistos = set()
    for p in guia["procedimientos"]:
        donde = f"«{p['nombre']}»"
        if p["id"] in vistos:
            errores.append(f"{donde}: el identificador '{p['id']}' está repetido.")
        vistos.add(p["id"])
        if not p["pasos"]:
            errores.append(f"{donde}: no tiene tabla de pasos.")
        if not p["frases"]:
            advertencias.append(f"{donde}: no tiene frases de ejemplo; será difícil reconocerlo.")
        declarados = {q["nombre"] for q in p["parametros"]}
        for q in p["parametros"]:
            if q["tipo"] not in TIPOS:
                errores.append(f"{donde}: el parámetro '{q['nombre']}' tiene un tipo desconocido "
                               f"'{q['tipo']}' (válidos: {', '.join(sorted(TIPOS))}).")
            if q["tipo"] == "opcion" and not q["valores"]:
                errores.append(f"{donde}: el parámetro '{q['nombre']}' es de tipo opcion pero no tiene valores.")
            if q["tipo"] == "texto" and not q["pista"] and not q["obligatorio"]:
                advertencias.append(f"{donde}: el parámetro de texto '{q['nombre']}' no tiene pista; "
                                    "solo se obtendrá si el modelo de IA lo detecta.")
        for paso in p["pasos"]:
            if paso["accion"] not in ACCIONES:
                errores.append(f"{donde}, paso {paso['n']}: acción desconocida '{paso['accion']}' "
                               f"(válidas: {', '.join(sorted(ACCIONES))}).")
            for ref in re.findall(r"\{([^}]+)\}", f"{paso['objetivo']} {paso['valor'] or ''}"):
                if not ref.startswith("credencial:") and ref not in declarados:
                    errores.append(f"{donde}, paso {paso['n']}: usa {{{ref}}} pero ese parámetro no está declarado.")
    nombres_contacto = [normalizar(c["nombre"]) for c in guia["contactos"]]
    if len(set(nombres_contacto)) != len(nombres_contacto):
        advertencias.append("Hay contactos con el mismo nombre.")
    return errores, advertencias
