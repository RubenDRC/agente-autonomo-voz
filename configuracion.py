"""
configuracion.py
================
Ajustes del agente en un solo lugar. Las llaves de API NO van aqui:
ponlas en variables de entorno o en un archivo .env (ver comun/entorno.py).
"""

from pathlib import Path

DIR_BASE = Path(__file__).resolve().parent

# ------------------------------------------------------------------ aplicativo
URL_INICIO = "http://localhost:5173/login.html"
HEADLESS = False                # True = navegador oculto (pruebas automaticas)
ESPERA_TRAS_ACCION_MS = 1200    # la app simula latencias de 600-900 ms
ZONAS_EXCLUIDAS = "[data-testid='panel-pruebas']"   # panel del sandbox: se ignora
DETALLE_PERCEPCION = False      # True = imprime cada campo y boton percibido

# ------------------------------------------------------------------ similitud semantica
MODELO_EMBEDDINGS = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
UMBRAL_ELEMENTO = 0.35          # confianza minima para elegir un campo o boton
UMBRAL_PROCEDIMIENTO = 0.55     # confianza minima para ejecutar una ruta completa
UMBRAL_COMANDO_PANTALLA = 0.75  # comando corto que coincide con un boton visible
                                # se trata como paso individual, no como tarea

# ------------------------------------------------------------------ conocimiento
# Memoria de rutas generada con:  python -m conocimiento entrenar guias/<guia>.docx
RUTA_CONOCIMIENTO = DIR_BASE / "conocimiento" / "rutas" / "banco_sandbox.json"

# ------------------------------------------------------------------ seguridad
RUTA_BILLETERA = DIR_BASE / "credenciales.wallet"
CARPETA_AUDITORIA = DIR_BASE / "auditoria"
AUTENTICACION_FACIAL = False
MINUTOS_DESBLOQUEO = 5

# ------------------------------------------------------------------ modelos de IA
# Se elige con:  python main.py --ia <nombre>     (y opcionalmente --modelo <id>)
#
# tipo "local"             : sin internet ni costo; embeddings + reglas.
# tipo "anthropic"         : API de Claude.
# tipo "openai_compatible" : cualquier API con el formato de OpenAI
#                            (OpenAI, Gemini, Groq, Ollama, LM Studio, vLLM...).
#
# Los nombres de modelo cambian con el tiempo. Para ver los vigentes:
#     python -m evaluacion --listar-modelos claude openai gemini groq ollama
# y usa cualquiera con  --ia proveedor@modelo  (p. ej. ollama@llama3.1:8b).
IA_POR_DEFECTO = "local"
PROVEEDORES_IA = {
    "local": {"tipo": "local"},
    "claude": {"tipo": "anthropic", "modelo": "claude-haiku-5-5",
               "variable_llave": "ANTHROPIC_API_KEY"},
    "claude-sonnet": {"tipo": "anthropic", "modelo": "claude-sonnet-5-5",
                      "variable_llave": "ANTHROPIC_API_KEY"},
    "openai": {"tipo": "openai_compatible", "url_base": "https://api.openai.com/v1",
               "modelo": "gpt-5.4-mini", "variable_llave": "OPENAI_API_KEY"},
    "gemini": {"tipo": "openai_compatible",
               "url_base": "https://generativelanguage.googleapis.com/v1beta/openai",
               "modelo": "gemini-3-flash-preview", "variable_llave": "GEMINI_API_KEY"},
    "groq": {"tipo": "openai_compatible", "url_base": "https://api.groq.com/openai/v1",
             "modelo": "llama-3.3-70b-versatile", "variable_llave": "GROQ_API_KEY"},
    "ollama": {"tipo": "openai_compatible", "url_base": "http://localhost:11434/v1",
               "modelo": "qwen2.5:7b"},          # modelo local, sin llave
}
TIEMPO_MAXIMO_IA_S = 60

# Quien elige el elemento en pantalla para cada paso:
#   "embeddings" -> similitud semantica local (rapido, sin costo)
#   "ia"         -> el modelo de IA elegido (solo proveedores LLM)
GROUNDING = "embeddings"
