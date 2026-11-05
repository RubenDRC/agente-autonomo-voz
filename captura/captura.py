"""
captura/captura.py
==================
Modulo de Captura de Instrucciones. Obtiene lo que el usuario quiere hacer:

  modo "voz"   -> microfono + reconocimiento de voz (captura/voz.py, faster-whisper)
  modo "texto" -> teclado; util para pruebas, evaluaciones y comparacion de modelos

Cada captura queda en la auditoria con su texto, proposito y duracion.
"""

import time

from comun.texto import normalizar

AFIRMACIONES = ("si", "sí", "claro", "confirmo", "dale", "de acuerdo", "hazlo", "adelante", "ok", "correcto")


class Captura:
    def __init__(self, seg, modo: str = "voz"):
        self.seg = seg
        self.modo = modo
        self._voz = None

    def _escuchar(self) -> str:
        if self.modo == "texto":
            return input("[tú] > ")
        if self._voz is None:
            from . import voz   # carga Whisper solo si se usa la voz
            self._voz = voz
        return self._voz.escuchar(modo="enter")

    def capturar(self, proposito: str) -> str:
        t0 = time.perf_counter()
        try:
            texto = (self._escuchar() or "").strip()
        except (EOFError, KeyboardInterrupt):
            raise
        except Exception as e:
            self.seg.auditor.registrar("CAPTURA", "error_captura", nivel="ERROR",
                                       proposito=proposito, error=str(e))
            return ""
        self.seg.auditor.registrar(
            "CAPTURA", "texto_capturado" if texto else "captura_vacia",
            nivel="INFO" if texto else "WARN", proposito=proposito, modo=self.modo,
            texto=texto, duracion_s=round(time.perf_counter() - t0, 2))
        return texto

    def preguntar(self, pregunta: str, proposito: str) -> str:
        print(f"\n[agente] {pregunta}")
        return self.capturar(proposito)

    def confirmar(self, pregunta: str) -> tuple[bool, str]:
        respuesta = self.preguntar(f"{pregunta} (responde «sí» o «no»)", "confirmacion")
        r = normalizar(respuesta).strip(" .!¡¿?")
        aceptado = any(r == a or r.startswith(a + " ") for a in map(normalizar, AFIRMACIONES))
        return aceptado, respuesta
