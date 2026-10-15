"""
voz.py
=======
Modulo de reconocimiento de voz en espanol (offline) con faster-whisper.

Captura audio del microfono y lo transcribe a texto SIN internet y SIN costo
por API.

Instalacion:
    pip install sounddevice soundfile numpy faster-whisper

La primera vez que se ejecuta, faster-whisper descarga el modelo elegido
(por defecto "small") y lo cachea localmente. Las siguientes veces ya no
descarga nada.
"""

import queue
import tempfile
import threading

import numpy as np
import sounddevice as sd
import soundfile as sf
from faster_whisper import WhisperModel

# ============================================================
# CONFIGURACION
# ============================================================

FRECUENCIA = 16000          # Whisper trabaja a 16 kHz
CANALES = 1                 # mono
TAMANO_MODELO = "small"     # tiny | base | small | medium | large-v3
IDIOMA = "es"               # forzamos espanol para mas precision

# Para maxima precision en espanol podrias usar:
#   TAMANO_MODELO = "medium"
# o el fine-tune de HuggingFace (requiere transformers/otro backend):
#   "adriszmar/whisper-large-v3-turbo-es"


# ============================================================
# CARGA DEL MODELO (una sola vez)
# ============================================================

# Se carga al importar el modulo para no repetir la carga en cada llamada.
# device="cpu" y compute_type="int8" funcionan en cualquier PC sin GPU.
# Si tienes GPU NVIDIA: device="cuda", compute_type="float16".
print(f"[voz] Cargando modelo Whisper '{TAMANO_MODELO}'...")
_modelo = WhisperModel(TAMANO_MODELO, device="cpu", compute_type="int8")
print("[voz] Modelo listo.")


# ============================================================
# 1) GRABACION POR DURACION FIJA
# ============================================================

def grabar_fijo(segundos: float = 5.0) -> np.ndarray:
    """Graba un numero fijo de segundos y devuelve el audio como array."""
    print(f"[voz] Grabando {segundos:.0f} s... habla ahora.")
    audio = sd.rec(
        int(segundos * FRECUENCIA),
        samplerate=FRECUENCIA,
        channels=CANALES,
        dtype="float32",
    )
    sd.wait()
    print("[voz] Grabacion terminada.")
    return audio


# ============================================================
# 2) GRABACION "PUSH TO TALK" (Enter para empezar / Enter para parar)
# ============================================================

def grabar_hasta_enter() -> np.ndarray:
    """
    Graba desde que presionas Enter hasta que vuelves a presionar Enter.
    Mas natural que una duracion fija: hablas el tiempo que necesites.
    """
    input("[voz] Presiona ENTER para empezar a grabar...")

    bloques = queue.Queue()
    grabando = threading.Event()
    grabando.set()

    def _callback(indata, frames, tiempo, status):
        if status:
            print(f"[voz] aviso: {status}")
        bloques.put(indata.copy())

    stream = sd.InputStream(
        samplerate=FRECUENCIA,
        channels=CANALES,
        dtype="float32",
        callback=_callback,
    )

    with stream:
        print("[voz] Grabando... presiona ENTER para detener.")
        input()
        grabando.clear()

    # Vaciar la cola en un solo array
    partes = []
    while not bloques.empty():
        partes.append(bloques.get())

    if not partes:
        return np.zeros((0, CANALES), dtype="float32")

    audio = np.concatenate(partes, axis=0)
    print("[voz] Grabacion terminada.")
    return audio


# ============================================================
# 3) TRANSCRIPCION
# ============================================================

def transcribir(audio: np.ndarray) -> str:
    """Convierte un array de audio a texto usando faster-whisper."""
    if audio.size == 0:
        return ""

    # Guardamos a un WAV temporal (faster-whisper acepta ruta o array;
    # el WAV es lo mas robusto entre versiones).
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        ruta = tmp.name
    sf.write(ruta, audio, FRECUENCIA)

    segmentos, info = _modelo.transcribe(ruta, language=IDIOMA, vad_filter=True)
    texto = " ".join(seg.text.strip() for seg in segmentos).strip()
    return texto


# ============================================================
# 4) FUNCION DE ALTO NIVEL (la que usaras normalmente)
# ============================================================

def escuchar(modo: str = "enter", segundos: float = 5.0) -> str:
    """
    Captura voz y devuelve el texto transcrito.

    modo="enter"  -> push to talk (recomendado)
    modo="fijo"   -> graba 'segundos' segundos
    """
    if modo == "fijo":
        audio = grabar_fijo(segundos)
    else:
        audio = grabar_hasta_enter()

    texto = transcribir(audio)
    print(f"[voz] Texto reconocido: {texto!r}")
    return texto


# ============================================================
# PRUEBA RAPIDA
# ============================================================

if __name__ == "__main__":
    print("\n=== Prueba del modulo de voz ===")
    resultado = escuchar(modo="enter")
    print("\nResultado final:", resultado)
