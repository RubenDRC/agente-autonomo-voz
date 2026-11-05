"""
decision_accion/acciones.py
===========================
Acciones primitivas sobre la interfaz y su verificacion inmediata:
escribir, clic, seleccionar, ir_a y leer. Cada una deja en la auditoria la
decision (que elemento se eligio y con que confianza), la accion y su
verificacion.
"""

from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import configuracion as cfg
from comun.coincidencia import por_etiqueta
from comun.texto import normalizar, pct
from percepcion import leer_textos
from seguridad import MASCARA


@dataclass
class Contexto:
    page: object
    seg: object
    ia: object
    captura: object


def metodo_grounding(ctx) -> str:
    return "ia" if getattr(ctx.ia, "grounding_ia", False) else "embeddings"


def elegir_elemento(ctx, objetivo: str, candidatos: list):
    """(indice, confianza, metodo): primero por etiqueta y, si no hay coincidencia,
    por similitud semantica o con el modelo de IA (segun GROUNDING)."""
    idx, score = por_etiqueta(objetivo, candidatos)
    if idx != -1:
        return idx, score, "etiqueta"
    idx, score = ctx.ia.elegir_elemento(objetivo, candidatos)
    return idx, score, metodo_grounding(ctx)


def localizar_exacto(page, objetivo: str):
    """Elemento por identificador exacto: 'testid:saldo-ahorros' o 'css:#monto'."""
    o = (objetivo or "").strip()
    if o.startswith("testid:"):
        return page.locator(f"[data-testid='{o[7:].strip()}']").first
    if o.startswith("css:"):
        return page.locator(o[4:].strip()).first
    return None


def registrar_decision(ctx, tipo, candidatos, idx, score, objetivo=None, metodo=None) -> bool:
    aceptado = idx is not None and idx != -1 and score >= cfg.UMBRAL_ELEMENTO
    ctx.seg.auditor.registrar(
        "DECISION_ACCION", "decision", nivel="INFO" if aceptado else "WARN",
        tipo=tipo, objetivo=objetivo,
        elemento=candidatos[idx] if candidatos and idx not in (None, -1) else None,
        metodo=metodo or metodo_grounding(ctx), similitud=round(float(score), 4),
        confianza_pct=pct(score), umbral_pct=pct(cfg.UMBRAL_ELEMENTO), aceptado=aceptado)
    if not aceptado:
        print(f"[agente] Confianza {pct(score)} % por debajo del umbral ({pct(cfg.UMBRAL_ELEMENTO)} %). No actúo.")
    return aceptado


def retroalimentar(ctx, verificacion: dict):
    if verificacion["resultado"] == "OK":
        return
    errores = [m["texto"] for m in verificacion.get("mensajes", []) if m["tipo"] == "error"]
    mensaje = "; ".join(errores) or verificacion.get("motivo") or "la acción no produjo cambios visibles"
    ctx.seg.auditor.registrar("VERIFICACION", "retroalimentacion", nivel="WARN",
                              destino="PLANIFICACION", mensaje=mensaje)
    print(f"[agente] La verificación reporta: {mensaje}")


def _verificacion(ctx, v: dict, **datos):
    ctx.seg.auditor.registrar("VERIFICACION", "verificacion",
                              nivel="INFO" if v["resultado"] == "OK" else "WARN", **datos, **v)
    retroalimentar(ctx, v)
    return v["resultado"] == "OK"


def esperar_estabilidad(page):
    try:
        page.wait_for_load_state("domcontentloaded", timeout=10000)
    except Exception:
        pass
    page.wait_for_timeout(cfg.ESPERA_TRAS_ACCION_MS)


# ------------------------------------------------------------------ escribir y clic

def ejecutar_escritura(ctx, loc, campo: str, texto: str, sensible: bool, origen: str) -> bool:
    try:
        loc.click()
        loc.fill(texto)
        exito, error = True, None
    except Exception as e:
        exito, error = False, str(e)
    ctx.seg.auditor.registrar(
        "DECISION_ACCION", "accion", nivel="INFO" if exito else "ERROR",
        tipo="escribir", campo=campo, texto=MASCARA if sensible else texto,
        origen_texto=origen, exito=exito, **({"error": error} if error else {}))
    if not exito:
        return False
    v = ctx.seg.verificador.verificar_escritura(loc, texto, sensible=sensible)
    return _verificacion(ctx, v, accion="escribir", campo=campo)


def ejecutar_clic(ctx, loc, nombre: str) -> bool:
    page = ctx.page
    antes = ctx.seg.verificador.estado_pagina(page)
    try:
        loc.click()
        exito, error = True, None
    except Exception as e:
        exito, error = False, str(e)
    ctx.seg.auditor.registrar("DECISION_ACCION", "accion", nivel="INFO" if exito else "ERROR",
                              tipo="clic", boton=nombre, exito=exito, **({"error": error} if error else {}))
    if not exito:
        return False
    esperar_estabilidad(page)
    v = ctx.seg.verificador.verificar_clic(page, antes)
    return _verificacion(ctx, v, accion="clic", boton=nombre)


# ------------------------------------------------------------------ seleccionar

def elegir_opcion(ctx, opciones: list, valor: str):
    """(indice, confianza, metodo) de la opcion que corresponde al valor."""
    vn = normalizar(valor)
    for j, (v, etiqueta) in enumerate(opciones):
        if vn in (normalizar(v), normalizar(etiqueta)):
            return j, 1.0, "exacto"
    for j, (_, etiqueta) in enumerate(opciones):
        if vn and vn in normalizar(etiqueta):
            return j, 0.95, "contenido"
    j, s = ctx.ia.elegir_elemento(valor, [e for _, e in opciones])
    return j, s, metodo_grounding(ctx)


def ejecutar_seleccion(ctx, loc, lista: str, opciones: list, valor: str) -> bool:
    j, score, metodo = elegir_opcion(ctx, opciones, valor)
    if not registrar_decision(ctx, "opcion", [e for _, e in opciones], j, score, objetivo=valor, metodo=metodo):
        return False
    valor_opcion, etiqueta = opciones[j]
    try:
        loc.select_option(value=valor_opcion)
        exito, error = True, None
    except Exception as e:
        exito, error = False, str(e)
    ctx.seg.auditor.registrar("DECISION_ACCION", "accion", nivel="INFO" if exito else "ERROR",
                              tipo="seleccionar", lista=lista, opcion=etiqueta, exito=exito,
                              **({"error": error} if error else {}))
    if not exito:
        return False
    ctx.page.wait_for_timeout(300)   # la app puede mostrar u ocultar campos
    try:
        leido = loc.input_value()
    except Exception:
        leido = None
    v = {"resultado": "OK" if leido == valor_opcion else "FALLO",
         "criterio": "opción seleccionada == opción elegida", "valor_leido": leido}
    return _verificacion(ctx, v, accion="seleccionar", lista=lista)


# ------------------------------------------------------------------ navegar

def ejecutar_ir_a(ctx, destino: str) -> bool:
    page = ctx.page
    url = urljoin(page.url, destino)
    url_antes = page.url
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=15000)
        exito, error = True, None
    except Exception as e:
        exito, error = False, str(e)
    ctx.seg.auditor.registrar("DECISION_ACCION", "accion", nivel="INFO" if exito else "ERROR",
                              tipo="ir_a", destino=destino, exito=exito, **({"error": error} if error else {}))
    if not exito:
        return False
    page.wait_for_timeout(cfg.ESPERA_TRAS_ACCION_MS // 2)
    esperado, final = urlparse(url).path, urlparse(page.url).path
    v = {"resultado": "OK" if final == esperado else "FALLO",
         "criterio": "la URL final coincide con el destino", "url_antes": url_antes, "url_despues": page.url}
    if final != esperado:
        v["motivo"] = f"la aplicación redirigió a {final}"
    return _verificacion(ctx, v, accion="ir_a", destino=destino)


# ------------------------------------------------------------------ leer

def ejecutar_lectura(ctx, objetivo: str) -> tuple[bool, str]:
    page = ctx.page
    loc = localizar_exacto(page, objetivo)
    if loc is not None:
        try:
            loc.wait_for(state="visible", timeout=5000)
            texto = loc.inner_text()
        except Exception:
            texto = ""
        elemento = objetivo
        registrar_decision(ctx, "dato", [objetivo], 0, 1.0, objetivo=objetivo, metodo="exacto")
    else:
        candidatos = leer_textos(page)
        descripciones = [c["desc"] for c in candidatos]
        idx, score, metodo = elegir_elemento(ctx, objetivo, descripciones)
        if not registrar_decision(ctx, "dato", descripciones, idx, score, objetivo=objetivo, metodo=metodo):
            return False, ""
        texto, elemento = candidatos[idx]["texto"], candidatos[idx]["id"]

    texto = " ".join((texto or "").split())
    ctx.seg.auditor.registrar("DECISION_ACCION", "accion", nivel="INFO" if texto else "WARN",
                              tipo="leer", elemento=elemento, texto=texto, exito=bool(texto))
    v = {"resultado": "OK" if texto else "FALLO", "criterio": "el dato leído tiene contenido",
         "valor_leido": texto}
    if not texto:
        v["motivo"] = f"no encontré el dato «{objetivo}»"
    ok = _verificacion(ctx, v, accion="leer", elemento=elemento)
    if ok:
        print(f"[agente] >>> {texto}")
    return ok, texto
