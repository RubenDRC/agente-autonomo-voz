"""
planificacion/comandos.py
=========================
Interpretacion de comandos de un solo paso (modo "paso a paso").

  - es_salida()              : "salir" / "terminar" apagan el agente.
  - es_comando_de_pantalla() : un comando corto que coincide con un elemento
                               visible ("consultar", "continuar") se ejecuta
                               como paso individual, sin buscar una ruta.
  - clasificar_comando()     : decide si el paso es ESCRIBIR, CLIC,
                               SELECCIONAR o AUTENTICAR.
"""

import configuracion as cfg
from comun.coincidencia import por_etiqueta
from comun.texto import contiene_frase, normalizar, pct
from ia.embeddings import mejor_match


def _mejor(texto, candidatos):
    idx, score = por_etiqueta(texto, candidatos)
    return (idx, score) if idx != -1 else mejor_match(texto, candidatos)

PALABRAS_SALIR = ("salir", "terminar")
PALABRAS_CREDENCIALES = ("credencial", "autentica", "billetera", "wallet")


def es_salida(texto: str) -> bool:
    t = normalizar(texto)
    return any(contiene_frase(t, p) for p in PALABRAS_SALIR)


def puntajes_pantalla(texto: str, ui) -> dict:
    """Similitud del comando con el mejor campo, lista y boton visibles."""
    if ui is None:
        return {}
    return {"campo": _mejor(texto, ui.desc_inputs),
            "lista": _mejor(texto, ui.desc_selects),
            "boton": _mejor(texto, ui.txt_botones)}


def es_comando_de_pantalla(texto: str, ui) -> tuple[bool, dict]:
    puntajes = puntajes_pantalla(texto, ui)
    mejor = max((s for _, s in puntajes.values()), default=0.0)
    corto = len(normalizar(texto).split()) <= 3
    return corto and mejor >= cfg.UMBRAL_COMANDO_PANTALLA, puntajes


def clasificar_comando(texto: str, ui, seg, puntajes=None) -> str:
    t = normalizar(texto)
    puntajes = puntajes if puntajes is not None else puntajes_pantalla(texto, ui)
    s_campo = puntajes.get("campo", (-1, 0.0))[1]
    s_lista = puntajes.get("lista", (-1, 0.0))[1]
    s_boton = puntajes.get("boton", (-1, 0.0))[1]

    if any(p in t for p in PALABRAS_CREDENCIALES):
        intencion, regla = "AUTENTICAR", "palabra clave de credenciales"
    elif s_boton >= cfg.UMBRAL_ELEMENTO and s_boton > max(s_campo, s_lista):
        intencion, regla = "CLIC", "se parece más a un botón"
    elif s_lista >= cfg.UMBRAL_ELEMENTO and s_lista > s_campo:
        intencion, regla = "SELECCIONAR", "se parece más a una lista desplegable"
    else:
        intencion, regla = "ESCRIBIR", "se parece más a un campo"

    seg.auditor.registrar("PLANIFICACION", "intencion", modo="paso a paso", comando=texto,
                          intencion=intencion, regla=regla, similitud_campo_pct=pct(s_campo),
                          similitud_lista_pct=pct(s_lista), similitud_boton_pct=pct(s_boton))
    return intencion
