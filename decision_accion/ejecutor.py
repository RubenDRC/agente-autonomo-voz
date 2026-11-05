"""
decision_accion/ejecutor.py
===========================
Ejecuta un plan (una ruta de la guia con sus parametros) paso a paso:

  para cada paso:  percibir pantalla -> elegir elemento -> actuar -> verificar

Reglas que se cumplen aunque la guia este mal escrita:
  - Un campo sensible (clave, clave dinamica) solo se llena desde la billetera.
  - Un secreto de la billetera solo se escribe en un campo sensible.
  - Los pasos marcados "Confirmar = Sí" piden aprobacion explicita del usuario.

Recuperacion: si un paso falla porque la aplicacion pidio iniciar sesion, se
ejecuta la ruta "ingresar" y se reintenta el paso una vez.
"""

import re
import time
from dataclasses import dataclass, field

from percepcion import describir_input, percibir, tipo_secreto
from planificacion import resumen_parametros
from seguridad import IDENTIFICADORES

from .acciones import (ejecutar_clic, ejecutar_escritura, ejecutar_ir_a, ejecutar_lectura,
                       ejecutar_seleccion, elegir_elemento, localizar_exacto, registrar_decision)


@dataclass
class ResultadoPlan:
    exito: bool
    pasos_ok: int
    total: int
    duracion_s: float
    fallo_en: "int | None" = None
    motivo: str = ""
    lecturas: list = field(default_factory=list)


class Ejecutor:
    def __init__(self, ctx, planificador, memoria):
        self.ctx = ctx
        self.planificador = planificador
        self.memoria = memoria

    # ------------------------------------------------------------------ plan completo

    def ejecutar(self, plan) -> ResultadoPlan:
        aud = self.ctx.seg.auditor
        aud.registrar("DECISION_ACCION", "plan_inicio", procedimiento=plan.id, nombre=plan.nombre,
                      pasos=len(plan.pasos), proveedor=plan.proveedor)
        print(f"\n[agente] Ejecutando «{plan.nombre}» ({len(plan.pasos)} pasos)")
        t0, lecturas, pasos_ok, i, ingreso_intentado = time.perf_counter(), [], 0, 0, False

        while i < len(plan.pasos):
            paso = plan.pasos[i]
            print(f"[agente] Paso {paso.n}/{len(plan.pasos)}: {paso.describir()}")
            aud.registrar("DECISION_ACCION", "paso_plan", procedimiento=plan.id, n=paso.n,
                          total=len(plan.pasos), accion=paso.accion, objetivo=paso.objetivo,
                          valor=f"credencial:{paso.credencial}" if paso.credencial else paso.valor)

            if paso.confirmar and not self._confirmar(plan, paso):
                return self._fin(plan, t0, pasos_ok, lecturas, paso.n, "cancelado por el usuario")

            ok, lectura, motivo = self._ejecutar_paso(paso)
            if lectura:
                lecturas.append(lectura)
            if not ok:
                if (not ingreso_intentado and plan.id != "ingresar" and "ingresar" in self.memoria.ids
                        and self._pantalla_de_ingreso()):
                    ingreso_intentado = True
                    aud.registrar("PLANIFICACION", "precondicion", procedimiento=plan.id,
                                  motivo="la aplicación pidió iniciar sesión",
                                  accion="se ejecuta la ruta «ingresar» y se reintenta el paso")
                    print("[agente] La aplicación pide iniciar sesión: ingreso primero y luego continúo.")
                    if self.ejecutar(self.planificador.plan_por_id("ingresar")).exito:
                        continue   # reintenta el mismo paso
                return self._fin(plan, t0, pasos_ok, lecturas, paso.n, motivo or "el paso no se completó")
            pasos_ok += 1
            i += 1
        return self._fin(plan, t0, pasos_ok, lecturas)

    def _fin(self, plan, t0, pasos_ok, lecturas, fallo_en=None, motivo="") -> ResultadoPlan:
        r = ResultadoPlan(fallo_en is None, pasos_ok, len(plan.pasos),
                          round(time.perf_counter() - t0, 2), fallo_en, motivo, lecturas)
        self.ctx.seg.auditor.registrar(
            "DECISION_ACCION", "plan_resultado", nivel="INFO" if r.exito else "WARN",
            procedimiento=plan.id, exito=r.exito, pasos_ok=r.pasos_ok, total=r.total,
            duracion_s=r.duracion_s, fallo_en=r.fallo_en, motivo=r.motivo, lecturas=r.lecturas)
        if r.exito:
            print(f"[agente] ✔ «{plan.nombre}» completada: {r.pasos_ok}/{r.total} pasos en {r.duracion_s} s.")
            for texto in lecturas:
                print(f"[agente]   Resultado: {texto}")
        else:
            print(f"[agente] ✘ «{plan.nombre}» se detuvo en el paso {r.fallo_en}: {r.motivo}.")
        return r

    # ------------------------------------------------------------------ un paso

    def _ejecutar_paso(self, paso):
        """Devuelve (ok, texto_leido, motivo_si_falla)."""
        ctx = self.ctx
        if paso.accion == "ir_a":
            return ejecutar_ir_a(ctx, paso.objetivo), None, f"no se pudo abrir {paso.objetivo}"
        if paso.accion == "esperar":
            ms = int(re.sub(r"\D", "", f"{paso.objetivo}{paso.valor or ''}") or 1000)
            ctx.page.wait_for_timeout(ms)
            ctx.seg.auditor.registrar("DECISION_ACCION", "accion", tipo="esperar", ms=ms, exito=True)
            return True, None, ""
        if paso.accion == "leer":
            ok, texto = ejecutar_lectura(ctx, paso.objetivo)
            return ok, texto, f"no se pudo leer «{paso.objetivo}»"

        ui = percibir(ctx.page, ctx.seg, f"paso {paso.n}: {paso.accion}")
        exacto = localizar_exacto(ctx.page, paso.objetivo)

        if paso.accion == "clic":
            if exacto is not None:
                registrar_decision(ctx, "boton", [paso.objetivo], 0, 1.0, paso.objetivo, "exacto")
                return ejecutar_clic(ctx, exacto, paso.objetivo), None, "el clic no tuvo el efecto esperado"
            idx, score, metodo = elegir_elemento(ctx, paso.objetivo, ui.txt_botones)
            if not registrar_decision(ctx, "boton", ui.txt_botones, idx, score, paso.objetivo, metodo):
                return False, None, f"no encontré «{paso.objetivo}» en la pantalla"
            nombre = ui.txt_botones[idx]
            return (ejecutar_clic(ctx, ui.botones.nth(ui.idx_botones[idx]), nombre), None,
                    f"el clic en «{nombre}» no tuvo el efecto esperado")

        if paso.accion == "escribir":
            if exacto is not None:
                loc, campo = exacto, paso.objetivo
                secreto = tipo_secreto(loc, describir_input(loc))
                registrar_decision(ctx, "campo", [campo], 0, 1.0, paso.objetivo, "exacto")
            else:
                idx, score, metodo = elegir_elemento(ctx, paso.objetivo, ui.desc_inputs)
                if not registrar_decision(ctx, "campo", ui.desc_inputs, idx, score, paso.objetivo, metodo):
                    return False, None, f"no encontré el campo «{paso.objetivo}»"
                loc, campo, secreto = ui.inputs.nth(ui.idx_inputs[idx]), ui.desc_inputs[idx], ui.secretos[idx]
            valor, sensible, origen, motivo = self._resolver_valor(paso, secreto)
            if valor is None:
                return False, None, motivo
            return (ejecutar_escritura(ctx, loc, campo, valor, sensible, origen), None,
                    f"el campo «{paso.objetivo}» no quedó con el valor esperado")

        if paso.accion == "seleccionar":
            if exacto is not None:
                loc, lista = exacto, paso.objetivo
                opciones = [tuple(o) for o in loc.evaluate(
                    "el => Array.from(el.options).map(o => [o.value, o.text.trim()])")]
                registrar_decision(ctx, "lista", [lista], 0, 1.0, paso.objetivo, "exacto")
            else:
                idx, score, metodo = elegir_elemento(ctx, paso.objetivo, ui.desc_selects)
                if not registrar_decision(ctx, "lista", ui.desc_selects, idx, score, paso.objetivo, metodo):
                    return False, None, f"no encontré la lista «{paso.objetivo}»"
                loc, lista, opciones = (ui.selects.nth(ui.idx_selects[idx]), ui.desc_selects[idx],
                                        ui.opciones_selects[idx])
            return (ejecutar_seleccion(ctx, loc, lista, opciones, paso.valor or ""), None,
                    f"no se pudo elegir «{paso.valor}» en «{paso.objetivo}»")

        return False, None, f"acción desconocida '{paso.accion}'"

    # ------------------------------------------------------------------ seguridad del valor

    def _resolver_valor(self, paso, secreto_campo):
        """(valor, sensible, origen, motivo_si_falla)."""
        seg = self.ctx.seg
        cred = paso.credencial
        if cred:
            es_secreto = cred not in IDENTIFICADORES
            if es_secreto and not secreto_campo:
                seg.auditor.registrar("SEGURIDAD", "politica_bloqueo", nivel="ERROR", paso=paso.n,
                                      credencial=cred, regla="un secreto solo se escribe en un campo sensible")
                return None, False, "", "bloqueado: la ruta intenta escribir un secreto en un campo no sensible"
            valor = seg.obtener_credencial(self.ctx.page.url, cred)
            if valor is None:
                return None, False, "", f"no se obtuvo la credencial «{cred}»"
            return valor, es_secreto, "billetera", ""
        if secreto_campo:
            seg.auditor.registrar("SEGURIDAD", "politica_bloqueo", nivel="ERROR", paso=paso.n,
                                  regla="un campo sensible solo se llena desde la billetera")
            return None, False, "", "bloqueado: un campo sensible solo se llena desde la billetera"
        return paso.valor or "", False, "plan", ""

    def _confirmar(self, plan, paso) -> bool:
        detalle = resumen_parametros(plan, self.memoria.obtener(plan.id))
        aceptado, respuesta = self.ctx.captura.confirmar(
            f"Voy a «{paso.objetivo}» en «{plan.nombre}»" + (f" ({detalle})" if detalle else "") + ". ¿Confirmas?")
        self.ctx.seg.auditor.registrar("SEGURIDAD", "confirmacion_usuario", nivel="INFO" if aceptado else "WARN",
                                       procedimiento=plan.id, paso=paso.n, respuesta=respuesta,
                                       resultado="ACEPTADA" if aceptado else "RECHAZADA")
        if not aceptado:
            print("[agente] Entendido, no lo hago.")
        return aceptado

    def _pantalla_de_ingreso(self) -> bool:
        try:
            return self.ctx.page.locator("input[type=password]:visible").count() > 0
        except Exception:
            return False
