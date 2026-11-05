"""Modulo de Percepcion del Entorno."""

from .percepcion import (EstadoInterfaz, describir_input, en_zona_excluida, leer_textos,
                         percibir, tipo_secreto)

__all__ = ["EstadoInterfaz", "percibir", "leer_textos", "describir_input", "tipo_secreto",
           "en_zona_excluida"]
