"""
Conocimiento del agente: guias de procedimientos (Word) convertidas en rutas.

    python -m conocimiento entrenar guias/Guia_Banco_Sandbox.docx
    python -m conocimiento listar
    python -m conocimiento ver transferencia_breb
"""

from .memoria import MemoriaProcedimientos

__all__ = ["MemoriaProcedimientos"]
