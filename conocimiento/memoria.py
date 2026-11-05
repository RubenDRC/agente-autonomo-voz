"""
conocimiento/memoria.py
=======================
Memoria de procedimientos (rutas) del agente. Es el resultado del
"entrenamiento" con la guia Word y se guarda como JSON legible y editable.

En el framework de Wang et al. (2025) corresponde a la memoria externa de
construccion manual: conocimiento sobre la interfaz que el agente consulta
para planificar, sin reentrenar ningun modelo.
"""

import json
from pathlib import Path


class MemoriaProcedimientos:
    def __init__(self, ruta):
        self.ruta = Path(ruta)
        datos = json.loads(self.ruta.read_text(encoding="utf-8"))
        self.aplicativo = datos.get("aplicativo", "")
        self.origen = datos.get("origen", "")
        self.fuente = datos.get("fuente", {})
        self.contactos = datos.get("contactos", [])
        self.procedimientos = datos.get("procedimientos", [])
        self._por_id = {p["id"]: p for p in self.procedimientos}

    @property
    def ids(self) -> set:
        return set(self._por_id)

    def obtener(self, pid: str) -> dict:
        return self._por_id[pid]

    def resumen(self) -> str:
        return (f"{self.aplicativo}: {len(self.procedimientos)} procedimientos, "
                f"{len(self.contactos)} contactos")

    @staticmethod
    def guardar(guia: dict, ruta) -> Path:
        ruta = Path(ruta)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(json.dumps(guia, ensure_ascii=False, indent=2), encoding="utf-8")
        return ruta
