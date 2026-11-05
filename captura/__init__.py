"""Modulo de Captura de Instrucciones (voz o texto)."""

from comun.texto import limpiar_dictado

from .captura import Captura

__all__ = ["Captura", "limpiar_dictado"]
