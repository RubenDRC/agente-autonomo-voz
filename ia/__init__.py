"""
Modelos de IA intercambiables
=============================
    from ia import crear_proveedor, listar_modelos
    ia = crear_proveedor("claude")                 # nombres en configuracion.PROVEEDORES_IA
    ia = crear_proveedor("ollama", modelo="llama3.1:8b")
    ia = crear_proveedor("ollama@llama3.1:8b")     # equivalente, util en la linea de comandos
    listar_modelos("gemini")                       # modelos que ofrece el proveedor hoy
"""

import os

import configuracion as cfg
from comun.entorno import cargar_env

from .base import ProveedorIA, ResultadoIdentificacion


def _separar(nombre, modelo):
    """'ollama@llama3.1:8b' -> ('ollama', 'llama3.1:8b')."""
    if nombre and "@" in nombre and not modelo:
        nombre, modelo = nombre.split("@", 1)
    return nombre, modelo


def _configuracion(nombre):
    cargar_env(cfg.DIR_BASE / ".env")
    nombre = nombre or cfg.IA_POR_DEFECTO
    if nombre not in cfg.PROVEEDORES_IA:
        raise ValueError(f"Proveedor de IA desconocido: '{nombre}'. "
                         f"Disponibles: {', '.join(cfg.PROVEEDORES_IA)}")
    conf = cfg.PROVEEDORES_IA[nombre]
    variable = conf.get("variable_llave")
    llave = os.getenv(variable) if variable else None
    if variable and not llave:
        raise ValueError(f"Falta la llave de API de '{nombre}': define {variable} "
                         "en el entorno o en el archivo .env")
    return nombre, conf, llave


def crear_proveedor(nombre=None, modelo=None) -> ProveedorIA:
    nombre, modelo = _separar(nombre, modelo)
    nombre, conf, llave = _configuracion(nombre)
    tipo = conf["tipo"]
    modelo = modelo or conf.get("modelo", "")
    grounding = cfg.GROUNDING == "ia"
    temperatura = conf.get("temperatura", 0)

    if tipo == "local":
        from .local import ProveedorLocal
        return ProveedorLocal(nombre)
    if tipo == "anthropic":
        from .anthropic import ProveedorAnthropic
        return ProveedorAnthropic(nombre, modelo, llave, conf.get("url"), grounding, temperatura)
    if tipo == "openai_compatible":
        from .openai_compatible import ProveedorOpenAICompatible
        return ProveedorOpenAICompatible(nombre, modelo, conf["url_base"], llave, grounding, temperatura)
    raise ValueError(f"Tipo de proveedor no soportado: {tipo}")


def listar_modelos(nombre) -> list[str]:
    """Identificadores de modelo que el proveedor ofrece hoy (consulta su API)."""
    from .llm import http_json
    nombre, _ = _separar(nombre, None)
    nombre, conf, llave = _configuracion(nombre)
    tipo = conf["tipo"]
    if tipo == "local":
        return ["embeddings + reglas (no requiere modelo externo)"]
    if tipo == "anthropic":
        from .anthropic import URL_MENSAJES, VERSION_API
        url = (conf.get("url") or URL_MENSAJES).rsplit("/messages", 1)[0] + "/models?limit=100"
        r = http_json(url, {"x-api-key": llave, "anthropic-version": VERSION_API}, timeout=30)
    else:
        encabezados = {"authorization": f"Bearer {llave}"} if llave else {}
        r = http_json(conf["url_base"].rstrip("/") + "/models", encabezados, timeout=30)
    return sorted(m.get("id", "") for m in r.get("data", []) if m.get("id"))


__all__ = ["crear_proveedor", "listar_modelos", "ProveedorIA", "ResultadoIdentificacion"]
