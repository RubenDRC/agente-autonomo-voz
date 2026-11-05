"""
ia/openai_compatible.py
=======================
Proveedor para cualquier API con el formato de "chat completions" de OpenAI:
OpenAI, Google Gemini, Groq, Ollama (modelos locales), LM Studio, vLLM...
Solo cambian la URL base, el modelo y la variable de la llave (configuracion.py).
"""

from .llm import ProveedorLLM, post_json


class ProveedorOpenAICompatible(ProveedorLLM):
    tipo = "openai_compatible"

    def __init__(self, nombre, modelo, url_base, llave=None, grounding_ia=False, temperatura=0):
        super().__init__(nombre, modelo, grounding_ia, temperatura)
        self.url = url_base.rstrip("/") + "/chat/completions"
        self._llave = llave

    def _completar(self, sistema, usuario):
        cuerpo = {"model": self.modelo,
                  "messages": [{"role": "system", "content": sistema},
                               {"role": "user", "content": usuario}]}
        if self.temperatura is not None:
            cuerpo["temperature"] = self.temperatura
        encabezados = {"content-type": "application/json"}
        if self._llave:
            encabezados["authorization"] = f"Bearer {self._llave}"
        r = post_json(self.url, encabezados, cuerpo, self.timeout)
        texto = (r.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        uso = r.get("usage", {})
        return texto, {"entrada": uso.get("prompt_tokens"), "salida": uso.get("completion_tokens")}
