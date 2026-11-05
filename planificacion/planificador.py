"""
planificacion/planificador.py
=============================
Modulo de Planificacion de Tareas (modo "tarea"). Convierte una instruccion
en un plan de pasos concretos:

  1. El modelo de IA elegido identifica la ruta de la guia y sus parametros.
  2. Si falta un parametro obligatorio, se le pregunta al usuario.
  3. Se aplican los valores por defecto de los parametros opcionales.
  4. Se instancian los pasos de la ruta con los parametros; los pasos que usan
     un parametro opcional no indicado se omiten.

Las credenciales quedan como referencias {credencial:...}: las resuelve el
modulo de seguridad en el momento de escribir, nunca el planificador ni la IA.
"""

import re
from dataclasses import dataclass, field

import configuracion as cfg
from comun.texto import normalizar, pct
from ia.extraccion import extraer_parametro, valor_por_defecto

from .comandos import es_salida

_REF = re.compile(r"\{([^}]+)\}")


@dataclass
class PasoPlan:
    n: int
    accion: str
    objetivo: str
    valor: "str | None" = None
    confirmar: bool = False
    esperado: str = ""

    @property
    def credencial(self):
        m = re.fullmatch(r"\{credencial:([^}]+)\}", self.valor or "")
        return m.group(1) if m else None

    def describir(self) -> str:
        if not self.valor:
            return f"{self.accion} «{self.objetivo}»"
        valor = f"[credencial: {self.credencial}]" if self.credencial else self.valor
        return f"{self.accion} «{self.objetivo}» = {valor}"


@dataclass
class Plan:
    id: str
    nombre: str
    parametros: dict
    pasos: list = field(default_factory=list)
    confianza: float = 1.0
    proveedor: str = ""
    explicacion: str = ""


def formatear(param: dict, valor) -> str:
    if param and param.get("tipo") == "monto":
        try:
            return "$" + f"{int(valor):,}".replace(",", ".")
        except (TypeError, ValueError):
            pass
    return str(valor)


def resumen_parametros(plan: Plan, procedimiento: dict) -> str:
    declarados = {p["nombre"]: p for p in procedimiento.get("parametros", [])}
    return " · ".join(f"{k}: {formatear(declarados.get(k), v)}" for k, v in plan.parametros.items())


def instanciar(procedimiento: dict, parametros: dict) -> list:
    pasos = []
    for paso in procedimiento["pasos"]:
        plantilla = f"{paso['objetivo']} {paso.get('valor') or ''}"
        referencias = [r for r in _REF.findall(plantilla) if not r.startswith("credencial:")]
        if any(parametros.get(r) in (None, "") for r in referencias):
            continue   # usa un parametro opcional que no se indico

        def sustituir(texto):
            if texto is None:
                return None
            return _REF.sub(lambda m: m.group(0) if m.group(1).startswith("credencial:")
                            else str(parametros[m.group(1)]), texto)

        pasos.append(PasoPlan(len(pasos) + 1, paso["accion"], sustituir(paso["objetivo"]),
                              sustituir(paso.get("valor")), paso.get("confirmar", False),
                              paso.get("esperado", "")))
    return pasos


class Planificador:
    def __init__(self, memoria, ia, captura, seg):
        self.memoria = memoria
        self.ia = ia
        self.captura = captura
        self.seg = seg

    def planificar(self, instruccion: str):
        aud = self.seg.auditor
        r = self.ia.identificar(instruccion, self.memoria)
        aud.registrar("PLANIFICACION", "identificacion", nivel="WARN" if r.error else "INFO",
                      proveedor=self.ia.nombre, modelo=self.ia.modelo, instruccion=instruccion,
                      procedimiento=r.procedimiento, confianza_pct=pct(r.confianza),
                      umbral_pct=pct(cfg.UMBRAL_PROCEDIMIENTO), parametros=r.parametros,
                      explicacion=r.explicacion, latencia_ms=r.latencia_ms, tokens=r.tokens,
                      **({"error": r.error} if r.error else {}))
        if r.error:
            print(f"[agente] El modelo {self.ia.etiqueta} no respondió: {r.error}")
            return None
        if not r.procedimiento or r.confianza < cfg.UMBRAL_PROCEDIMIENTO:
            return None

        proc = self.memoria.obtener(r.procedimiento)
        print(f"[agente] Entendí: {proc['nombre']}  (confianza {pct(r.confianza)} % · {self.ia.etiqueta})")
        parametros = dict(r.parametros)
        for p in proc.get("parametros", []):
            if parametros.get(p["nombre"]) not in (None, ""):
                continue
            if p.get("obligatorio"):
                valor = self._preguntar(p)
                if valor is None:
                    aud.registrar("PLANIFICACION", "plan_cancelado", nivel="WARN", procedimiento=proc["id"],
                                  motivo=f"no se obtuvo el parámetro obligatorio '{p['nombre']}'")
                    print("[agente] Cancelo la tarea: faltó un dato obligatorio.")
                    return None
                parametros[p["nombre"]] = valor
            else:
                defecto = valor_por_defecto(p)
                if defecto not in (None, ""):
                    parametros[p["nombre"]] = defecto

        plan = Plan(proc["id"], proc["nombre"], parametros, instanciar(proc, parametros),
                    r.confianza, self.ia.etiqueta, r.explicacion)
        aud.registrar("PLANIFICACION", "plan", procedimiento=plan.id, nombre=plan.nombre,
                      parametros=parametros, pasos=[f"{x.n}. {x.describir()}" for x in plan.pasos])
        if parametros:
            print(f"[agente] Datos: {resumen_parametros(plan, proc)}")
        return plan

    def _preguntar(self, param: dict):
        pregunta = param.get("pregunta") or f"¿Cuál es el valor de «{param['nombre']}»?"
        for _ in range(2):
            respuesta = self.captura.preguntar(pregunta, proposito=f"parametro:{param['nombre']}")
            if not respuesta:
                continue
            if es_salida(respuesta) or "cancel" in normalizar(respuesta):
                return None
            valor = extraer_parametro(param, respuesta, self.memoria.contactos)
            self.seg.auditor.registrar("PLANIFICACION", "parametro_solicitado",
                                       nivel="INFO" if valor not in (None, "") else "WARN",
                                       parametro=param["nombre"], respuesta=respuesta, valor=valor)
            if valor not in (None, ""):
                return valor
            print("[agente] No entendí ese dato.")
        return None

    def plan_por_id(self, pid: str, parametros=None) -> Plan:
        """Plan de una ruta sin pasar por la IA (p. ej. 'ingresar' como precondicion)."""
        proc = self.memoria.obtener(pid)
        parametros = parametros or {}
        return Plan(pid, proc["nombre"], parametros, instanciar(proc, parametros), 1.0, "guía", "precondición")
