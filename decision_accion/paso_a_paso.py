"""
decision_accion/paso_a_paso.py
==============================
Modo "paso a paso" (el comportamiento de la version 1): el usuario dicta cada
paso ("llave", "consultar", "continuar") y el agente ejecuta solo ese paso.
Se usa cuando la instruccion no corresponde a ninguna ruta de la guia, o
cuando es un comando corto que coincide con un elemento visible.
"""

from comun.texto import limpiar_dictado, pct

from .acciones import (ejecutar_clic, ejecutar_escritura, ejecutar_seleccion, elegir_elemento,
                       registrar_decision)


def ejecutar(ctx, ui, intencion: str, comando: str) -> bool:
    if intencion == "AUTENTICAR":
        return autenticar_con_billetera(ctx, ui)
    if intencion == "CLIC":
        return pulsar_boton(ctx, ui, comando)
    if intencion == "SELECCIONAR":
        return seleccionar_en_lista(ctx, ui, comando)
    if ui.desc_inputs:
        return escribir_en_campo(ctx, ui, comando)
    ctx.seg.auditor.registrar("DECISION_ACCION", "decision", nivel="WARN", tipo="campo", aceptado=False,
                              motivo="no hay campos de texto en esta pantalla")
    print("[agente] No hay campos de texto en esta pantalla.")
    return False


def escribir_en_campo(ctx, ui, comando: str) -> bool:
    """Primero decide el campo; asi, si es sensible, no se pide dictar el valor."""
    idx, score, metodo = elegir_elemento(ctx, comando, ui.desc_inputs)
    if not registrar_decision(ctx, "campo", ui.desc_inputs, idx, score, comando, metodo):
        return False
    campo, secreto = ui.desc_inputs[idx], ui.secretos[idx]
    loc = ui.inputs.nth(ui.idx_inputs[idx])
    print(f"[agente] Campo elegido: '{campo}' ({pct(score)} %)")

    if secreto:
        ctx.seg.auditor.registrar("SEGURIDAD", "campo_sensible", campo=campo, secreto=secreto,
                                  politica="no se dicta por voz; se toma de la billetera")
        print("[agente] Campo sensible: tomo el valor de la billetera (no lo dictes).")
        texto = ctx.seg.obtener_credencial(ctx.page.url, secreto)
        if texto is None:
            print("[agente] No se obtuvo la credencial. No escribo.")
            return False
        return ejecutar_escritura(ctx, loc, campo, texto, sensible=True, origen="billetera")

    texto = ctx.captura.preguntar("¿Qué texto escribo?", "texto_a_escribir")
    if not texto:
        return False
    limpio = limpiar_dictado(texto)
    if limpio != texto:
        ctx.seg.auditor.registrar("CAPTURA", "texto_normalizado", original=texto, normalizado=limpio)
    return ejecutar_escritura(ctx, loc, campo, limpio, sensible=False, origen="voz")


def pulsar_boton(ctx, ui, comando: str) -> bool:
    idx, score, metodo = elegir_elemento(ctx, comando, ui.txt_botones)
    if not registrar_decision(ctx, "boton", ui.txt_botones, idx, score, comando, metodo):
        return False
    nombre = ui.txt_botones[idx]
    print(f"[agente] Botón elegido: '{nombre}' ({pct(score)} %)")
    return ejecutar_clic(ctx, ui.botones.nth(ui.idx_botones[idx]), nombre)


def seleccionar_en_lista(ctx, ui, comando: str) -> bool:
    idx, score, metodo = elegir_elemento(ctx, comando, ui.desc_selects)
    if not registrar_decision(ctx, "lista", ui.desc_selects, idx, score, comando, metodo):
        return False
    opciones = ui.opciones_selects[idx]
    print(f"[agente] Lista elegida: '{ui.desc_selects[idx]}'. Opciones: "
          + ", ".join(e for _, e in opciones if e))
    valor = ctx.captura.preguntar("¿Qué opción elijo?", "opcion_a_elegir")
    if not valor:
        return False
    return ejecutar_seleccion(ctx, ui.selects.nth(ui.idx_selects[idx]), ui.desc_selects[idx], opciones, valor)


def autenticar_con_billetera(ctx, ui) -> bool:
    """Respaldo cuando no hay guia: usuario + clave desde la billetera y enviar."""
    seg = ctx.seg
    seg.auditor.registrar("PLANIFICACION", "subtareas", tarea="autenticacion",
                          plan=["escribir usuario", "escribir clave", "enviar formulario"])
    idx_clave = next((k for k, s in enumerate(ui.secretos) if s == "clave"), -1)
    if idx_clave == -1:
        print("[agente] No veo un formulario de inicio de sesión aquí.")
        return False
    candidatos = [k for k, s in enumerate(ui.secretos) if not s]
    descs = [ui.desc_inputs[k] for k in candidatos]
    rel, score, metodo = elegir_elemento(ctx, "usuario", descs)
    if not registrar_decision(ctx, "campo", descs, rel, score, "usuario", metodo):
        return False
    idx_usuario = candidatos[rel]
    usuario = seg.obtener_credencial(ctx.page.url, "usuario")
    clave = seg.obtener_credencial(ctx.page.url, "clave") if usuario is not None else None
    if usuario is None or clave is None:
        print("[agente] No se obtuvieron las credenciales.")
        return False
    ok = ejecutar_escritura(ctx, ui.inputs.nth(ui.idx_inputs[idx_usuario]), ui.desc_inputs[idx_usuario],
                           usuario, sensible=False, origen="billetera")
    ok = ejecutar_escritura(ctx, ui.inputs.nth(ui.idx_inputs[idx_clave]), ui.desc_inputs[idx_clave],
                            clave, sensible=True, origen="billetera") and ok
    if not ok:
        return False
    rel, score, metodo = elegir_elemento(ctx, "entrar", ui.txt_botones)
    if not registrar_decision(ctx, "boton", ui.txt_botones, rel, score, "entrar", metodo):
        return False
    return ejecutar_clic(ctx, ui.botones.nth(ui.idx_botones[rel]), ui.txt_botones[rel])
