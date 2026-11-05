"""
comun/entorno.py
================
Carga variables de un archivo .env (si existe) sin dependencias externas.
Las llaves de API de los modelos de IA van ahi o en variables de entorno,
nunca en el codigo ni en configuracion.py. El .gitignore excluye .env.

Ejemplo de .env:
    ANTHROPIC_API_KEY=sk-ant-...
    OPENAI_API_KEY=sk-...
"""

import os
from pathlib import Path


def cargar_env(ruta) -> int:
    ruta = Path(ruta)
    if not ruta.exists():
        return 0
    n = 0
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        clave, valor = clave.strip(), valor.strip().strip('"').strip("'")
        if clave and clave not in os.environ:   # el entorno real tiene prioridad
            os.environ[clave] = valor
            n += 1
    return n
