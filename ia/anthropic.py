"""
ia/anthropic.py
===============
Proveedor para los modelos Claude (API de mensajes de Anthropic).
Requiere la variable de entorno ANTHROPIC_API_KEY (o en el archivo .env).
Documentacion: https://platform.claude.com/docs/en/api
"""

from .llm import ProveedorLLM, post_json

URL_MENSAJES = "https://api.anthropic.com/v1/messages"
VERSION_API = "2023-06-01"


class ProveedorAnthropic(ProveedorLLM):
    tipo = "anthropic"

    def __init__(self, nombre, modelo, llave, url=None, grounding_ia=False, temperatura=0):
        super().__init__(nombre, modelo, grounding_ia, temperatura)
        self._llave = llave
        self.url = url or URL_MENSAJES

    def _completar(self, sistema, usuario):
        cuerpo = {"model": self.modelo, "max_tokens": 1024, "system": sistema,
                  "messages": [{"role": "user", "content": usuario}]}
        if self.temperatura is not None:
            cuerpo["temperature"] = self.temperatura
        r = post_json(self.url, {"x-api-key": self._llave, "anthropic-version": VERSION_API,
                                 "content-type": "application/json"}, cuerpo, self.timeout)
        texto = "".join(b.get("text", "") for b in r.get("content", []) if b.get("type") == "text")
        uso = r.get("usage", {})
        return texto, {"entrada": uso.get("input_tokens"), "salida": uso.get("output_tokens")}
