"""
seguridad/auditoria.py
======================
Registro de auditoria del agente (memoria interna + trazabilidad).

Cada evento que produce cualquier modulo del agente se guarda como una linea
JSON (formato JSONL) con:

  - ts         : fecha y hora ISO-8601 con milisegundos y zona horaria
  - t_rel_s    : segundos transcurridos desde el inicio de la sesion
  - sesion     : identificador unico de la sesion
  - paso       : numero de ciclo (un comando de voz = un paso)
  - modulo     : CAPTURA | PERCEPCION | PLANIFICACION | DECISION_ACCION |
                 SEGURIDAD | VERIFICACION | SISTEMA
  - evento     : que ocurrio (ej. 'texto_capturado', 'decision', 'accion')
  - datos      : detalle del evento (los secretos se enmascaran)
  - hash_previo, hash : encadenamiento SHA-256. Si alguien edita o borra una
                 linea del log, la cadena se rompe y verificar_integridad()
                 lo detecta (log a prueba de manipulacion).

Por sesion se crea la carpeta  auditoria/<sesion>/  con:
  auditoria.jsonl  -> registro estructurado (para analisis / validacion)
  auditoria.log    -> version legible para humanos
  capturas/        -> evidencia visual de cada paso (campos sensibles tapados)

Herramientas (ver seguridad/__main__.py):
  python -m seguridad verificar auditoria/<sesion>
  python -m seguridad csv       auditoria/<sesion>
"""

import csv
import hashlib
import json
import time
import uuid
from datetime import datetime
from pathlib import Path

GENESIS = "0" * 64
MASCARA = "••••••"


def _ahora() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _hash_registro(registro: dict) -> str:
    """Hash SHA-256 del registro SIN su propio campo 'hash'."""
    cuerpo = {k: v for k, v in registro.items() if k != "hash"}
    serial = json.dumps(cuerpo, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(serial.encode("utf-8")).hexdigest()


class Auditor:
    """Escribe la traza de auditoria de una sesion del agente."""

    def __init__(self, carpeta="auditoria", guardar_capturas=True,
                 eco_consola=True):
        inicio = datetime.now()
        self.sesion_id = inicio.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
        self.dir = Path(carpeta) / self.sesion_id
        self.dir_capturas = self.dir / "capturas"
        self.dir_capturas.mkdir(parents=True, exist_ok=True)

        self.ruta_jsonl = self.dir / "auditoria.jsonl"
        self.ruta_log = self.dir / "auditoria.log"

        self.paso = 0
        self.guardar_capturas = guardar_capturas
        self.eco = eco_consola

        self._hash_previo = GENESIS
        self._secretos: set[str] = set()
        self._t0 = time.perf_counter()
        self._n_capturas = 0
        self.contadores = {
            "eventos": 0,
            "acciones_ok": 0,
            "acciones_fallidas": 0,
            "verificaciones_ok": 0,
            "verificaciones_fallidas": 0,
            "alertas_seguridad": 0,
        }

    # ------------------------------------------------------------------
    # Pasos y proteccion de secretos
    # ------------------------------------------------------------------

    def nuevo_paso(self) -> int:
        self.paso += 1
        return self.paso

    def proteger(self, secreto) -> None:
        """Registra un valor secreto para que NUNCA aparezca en el log.

        Cualquier texto que se vaya a registrar y contenga este valor sera
        reemplazado por la mascara (defensa en profundidad: aunque un modulo
        intente registrar la clave por error, no quedara en disco).
        """
        if secreto is not None and len(str(secreto)) >= 3:
            self._secretos.add(str(secreto))

    def _redactar(self, valor):
        if isinstance(valor, str):
            for s in self._secretos:
                if s in valor:
                    valor = valor.replace(s, MASCARA)
            return valor
        if isinstance(valor, dict):
            return {k: self._redactar(v) for k, v in valor.items()}
        if isinstance(valor, (list, tuple)):
            return [self._redactar(v) for v in valor]
        return valor

    # ------------------------------------------------------------------
    # Registro de eventos
    # ------------------------------------------------------------------

    def registrar(self, modulo: str, evento: str, nivel: str = "INFO", **datos) -> dict:
        registro = {
            "ts": _ahora(),
            "t_rel_s": round(time.perf_counter() - self._t0, 3),
            "sesion": self.sesion_id,
            "paso": self.paso,
            "modulo": modulo,
            "evento": evento,
            "nivel": nivel,
            "datos": self._redactar(datos),
            "hash_previo": self._hash_previo,
        }
        registro["hash"] = _hash_registro(registro)
        self._hash_previo = registro["hash"]

        with open(self.ruta_jsonl, "a", encoding="utf-8") as f:
            f.write(json.dumps(registro, ensure_ascii=False) + "\n")

        linea = self._formatear(registro)
        with open(self.ruta_log, "a", encoding="utf-8") as f:
            f.write(linea + "\n")
        if self.eco:
            print(linea)

        self._contar(modulo, evento, nivel, registro["datos"])
        return registro

    def _contar(self, modulo, evento, nivel, datos):
        self.contadores["eventos"] += 1
        if modulo == "DECISION_ACCION" and evento == "accion":
            clave = "acciones_ok" if datos.get("exito") else "acciones_fallidas"
            self.contadores[clave] += 1
        if modulo == "VERIFICACION" and evento == "verificacion":
            clave = ("verificaciones_ok" if datos.get("resultado") == "OK"
                     else "verificaciones_fallidas")
            self.contadores[clave] += 1
        if modulo == "SEGURIDAD" and nivel in ("WARN", "ERROR"):
            self.contadores["alertas_seguridad"] += 1

    @staticmethod
    def _formatear(r: dict) -> str:
        fecha = r["ts"][:23].replace("T", " ")
        partes = []
        for k, v in r["datos"].items():
            if isinstance(v, (list, dict)):
                v = json.dumps(v, ensure_ascii=False)
            v = str(v)
            if len(v) > 90:
                v = v[:87] + "..."
            partes.append(f"{k}={v}")
        detalle = " | ".join(partes)
        return (f"{fecha} | paso {r['paso']:02d} | {r['nivel']:<5} | "
                f"{r['modulo']:<15} | {r['evento']:<24} | {detalle}")

    # ------------------------------------------------------------------
    # Evidencia visual
    # ------------------------------------------------------------------

    def captura(self, page, etiqueta: str, mascaras=None):
        """Guarda un screenshot; los locators en 'mascaras' se tapan."""
        if not self.guardar_capturas:
            return None
        self._n_capturas += 1
        nombre = f"paso{self.paso:02d}_{self._n_capturas:03d}_{etiqueta}.png"
        ruta = self.dir_capturas / nombre
        try:
            page.screenshot(path=str(ruta), mask=list(mascaras or []),
                            mask_color="#1F2937")
            return str(ruta.relative_to(self.dir))
        except Exception as e:  # la evidencia nunca debe tumbar al agente
            self.registrar("SISTEMA", "captura_fallida", nivel="WARN", error=str(e))
            return None

    # ------------------------------------------------------------------
    # Cierre de sesion
    # ------------------------------------------------------------------

    def cerrar(self) -> dict:
        resumen = dict(self.contadores)
        resumen["pasos"] = self.paso
        resumen["duracion_s"] = round(time.perf_counter() - self._t0, 2)
        self.registrar("SISTEMA", "fin_sesion", **resumen)
        ok, n, detalle = verificar_integridad(self.ruta_jsonl)
        print(f"\n[auditoria] Registro: {self.ruta_jsonl}")
        print(f"[auditoria] Integridad de la cadena: {'OK' if ok else 'ROTA'} "
              f"({n} eventos){'' if ok else ' -> ' + detalle}")
        return resumen


# ======================================================================
# Herramientas de analisis (usadas en la fase de validacion)
# ======================================================================

def _ruta_jsonl(ruta) -> Path:
    ruta = Path(ruta)
    return ruta / "auditoria.jsonl" if ruta.is_dir() else ruta


def verificar_integridad(ruta) -> tuple[bool, int, str]:
    """Recorre la cadena de hashes. Devuelve (ok, n_eventos, detalle)."""
    previo = GENESIS
    n = 0
    with open(_ruta_jsonl(ruta), encoding="utf-8") as f:
        for n, linea in enumerate(f, start=1):
            registro = json.loads(linea)
            if registro.get("hash_previo") != previo:
                return False, n, f"linea {n}: eslabon faltante o reordenado"
            if _hash_registro(registro) != registro.get("hash"):
                return False, n, f"linea {n}: contenido modificado"
            previo = registro["hash"]
    return True, n, "cadena integra"


def exportar_csv(ruta, destino=None, separador=";") -> Path:
    """Aplana el JSONL a CSV (una fila por evento) para tablas del informe.

    Usa ';' por defecto porque Excel en espanol (Colombia) lo espera asi; con
    ',' abriria todo en una sola columna. UTF-8 con BOM para que se vean tildes.
    """
    origen = _ruta_jsonl(ruta)
    destino = Path(destino) if destino else origen.with_suffix(".csv")
    columnas = ["fecha_hora", "paso", "modulo", "evento", "nivel", "tipo",
                "elemento", "texto", "confianza_pct", "resultado", "detalle"]
    with open(origen, encoding="utf-8") as f_in, \
         open(destino, "w", newline="", encoding="utf-8-sig") as f_out:
        w = csv.writer(f_out, delimiter=separador)
        w.writerow(columnas)
        for linea in f_in:
            r = json.loads(linea)
            d = r["datos"]
            if "resultado" in d:
                resultado = d["resultado"]
            elif "exito" in d:
                resultado = "OK" if d["exito"] else "FALLO"
            elif "aceptado" in d:
                resultado = "ACEPTADO" if d["aceptado"] else "RECHAZADO"
            else:
                resultado = ""
            w.writerow([
                r["ts"][:23].replace("T", " "), r["paso"], r["modulo"], r["evento"], r["nivel"],
                d.get("tipo") or d.get("accion") or d.get("proposito") or d.get("secreto") or "",
                d.get("elemento") or d.get("campo") or d.get("boton") or d.get("url") or "",
                d.get("texto") or d.get("normalizado") or d.get("comando") or "",
                d.get("confianza_pct", ""),
                resultado,
                json.dumps(d, ensure_ascii=False),
            ])
    return destino
