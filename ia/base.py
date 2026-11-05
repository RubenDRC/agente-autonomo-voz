"""
ia/base.py
==========
Interfaz comun para todos los modelos de IA del agente. Cualquier proveedor
(local, Claude, OpenAI, Ollama...) implementa las mismas dos operaciones:

  identificar(instruccion, memoria) -> que ruta de la guia corresponde a la
                                       instruccion y con que parametros
  elegir_elemento(objetivo, lista)  -> que elemento de la pantalla corresponde
                                       a un paso de la ruta

La IA nunca ejecuta acciones ni ve credenciales: solo elige entre rutas y
elementos conocidos. La ejecucion es responsabilidad de decision_accion/.
"""

from dataclasses import dataclass, field


@dataclass
class ResultadoIdentificacion:
    procedimiento: "str | None"         # id de la ruta, o None si ninguna aplica
    confianza: float                    # 0 a 1
    parametros: dict = field(default_factory=dict)
    explicacion: str = ""
    latencia_ms: int = 0
    tokens: "dict | None" = None        # uso de tokens (solo modelos LLM)
    error: "str | None" = None


class ProveedorIA:
    tipo = "base"

    def __init__(self, nombre: str, modelo: str = ""):
        self.nombre = nombre
        self.modelo = modelo

    @property
    def etiqueta(self) -> str:
        return self.nombre + (f" ({self.modelo})" if self.modelo else "")

    def identificar(self, instruccion: str, memoria) -> ResultadoIdentificacion:
        raise NotImplementedError

    def elegir_elemento(self, objetivo: str, candidatos: list[str]) -> tuple[int, float]:
        """Por defecto: similitud semantica local (embeddings)."""
        from .embeddings import mejor_match
        return mejor_match(objetivo, candidatos)
