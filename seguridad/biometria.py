"""
seguridad/biometria.py
======================
Verificacion facial OPCIONAL (estilo "FaceID") para autorizar el uso de
credenciales. Usa dos modelos ligeros de OpenCV Zoo:

  - YuNet  -> detecta el rostro en la imagen de la camara
  - SFace  -> convierte el rostro en un vector de 128 dimensiones

El enrolamiento guarda varias muestras del vector DENTRO de la billetera
cifrada. La verificacion compara el rostro actual con esas muestras por
similitud coseno; se acepta si supera 0.363 (umbral recomendado por OpenCV
para SFace).

LIMITACION IMPORTANTE (declararla en el documento): no incluye deteccion de
vida (anti-spoofing), por lo que una fotografia podria engañarla. Aqui actua
como segundo factor de presencia del usuario, no como mecanismo criptografico.
Los modelos (~40 MB en total) se descargan la primera vez en ./modelos/.
"""

import time
import urllib.request
from pathlib import Path

import numpy as np

try:
    import cv2
except ImportError:  # la biometria es opcional
    cv2 = None

MODELOS = {
    "detector": (
        "face_detection_yunet_2023mar.onnx",
        "https://github.com/opencv/opencv_zoo/raw/main/models/"
        "face_detection_yunet/face_detection_yunet_2023mar.onnx",
    ),
    "reconocedor": (
        "face_recognition_sface_2021dec.onnx",
        "https://github.com/opencv/opencv_zoo/raw/main/models/"
        "face_recognition_sface/face_recognition_sface_2021dec.onnx",
    ),
}
UMBRAL_COSENO = 0.363
DIR_MODELOS = Path(__file__).resolve().parent.parent / "modelos"
TAMANO_MINIMO_MODELO = 100_000  # bytes; evita usar descargas corruptas


class BiometriaError(Exception):
    pass


class VerificadorFacial:
    def __init__(self, carpeta_modelos=DIR_MODELOS, camara=0,
                 umbral=UMBRAL_COSENO, mostrar_ventana=True):
        if cv2 is None:
            raise BiometriaError("Falta OpenCV: pip install opencv-python")
        self.camara = camara
        self.umbral = umbral
        self.mostrar_ventana = mostrar_ventana

        rutas = {clave: self._asegurar_modelo(Path(carpeta_modelos), nombre, url)
                 for clave, (nombre, url) in MODELOS.items()}
        self.detector = cv2.FaceDetectorYN.create(
            str(rutas["detector"]), "", (320, 320), 0.9, 0.3, 5000)
        self.reconocedor = cv2.FaceRecognizerSF.create(str(rutas["reconocedor"]), "")

    # ------------------------------------------------------------------

    @staticmethod
    def _asegurar_modelo(carpeta: Path, nombre: str, url: str) -> Path:
        ruta = carpeta / nombre
        if ruta.exists() and ruta.stat().st_size > TAMANO_MINIMO_MODELO:
            return ruta
        carpeta.mkdir(parents=True, exist_ok=True)
        print(f"[biometria] Descargando modelo {nombre}...")
        try:
            urllib.request.urlretrieve(url, ruta)
        except Exception as e:
            raise BiometriaError(f"No se pudo descargar {nombre}: {e}") from None
        if ruta.stat().st_size < TAMANO_MINIMO_MODELO:
            ruta.unlink(missing_ok=True)
            raise BiometriaError(f"Descarga invalida de {nombre}. "
                                 f"Descargalo manualmente desde {url}")
        return ruta

    def _vector_rostro(self, frame):
        """Devuelve (vector, n_rostros). Solo acepta exactamente un rostro."""
        alto, ancho = frame.shape[:2]
        self.detector.setInputSize((ancho, alto))
        _, rostros = self.detector.detect(frame)
        n = 0 if rostros is None else len(rostros)
        if n != 1:
            return None, n
        alineado = self.reconocedor.alignCrop(frame, rostros[0])
        return self.reconocedor.feature(alineado).flatten(), 1

    def _capturar(self, titulo: str, n_muestras: int, timeout_s: float) -> list:
        cap = cv2.VideoCapture(self.camara)
        if not cap.isOpened():
            raise BiometriaError("No se pudo abrir la camara.")
        muestras, t0 = [], time.time()
        try:
            while len(muestras) < n_muestras and time.time() - t0 < timeout_s:
                ok, frame = cap.read()
                if not ok:
                    continue
                vector, n = self._vector_rostro(frame)
                if self.mostrar_ventana:
                    aviso = {0: "No se detecta un rostro",
                             1: f"Rostro detectado ({len(muestras) + 1}/{n_muestras})"}.get(
                        n, "Solo una persona frente a la camara")
                    color = (0, 170, 0) if n == 1 else (0, 0, 220)
                    vista = frame.copy()
                    cv2.putText(vista, aviso, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
                    try:
                        cv2.imshow(titulo, vista)
                        cv2.waitKey(1)
                    except cv2.error:
                        self.mostrar_ventana = False   # sin entorno grafico
                if vector is not None:
                    muestras.append(vector)
                    time.sleep(0.35)  # espaciar muestras para variar la pose
        finally:
            cap.release()
            if self.mostrar_ventana:
                cv2.destroyAllWindows()
        return muestras

    # ------------------------------------------------------------------

    def enrolar(self, n_muestras=5, timeout_s=30) -> list:
        print("[biometria] Mira a la camara y mueve levemente la cabeza...")
        muestras = self._capturar("Enrolamiento facial", n_muestras, timeout_s)
        if len(muestras) < n_muestras:
            raise BiometriaError("No se obtuvieron suficientes muestras del rostro.")
        return [m.astype(float).round(6).tolist() for m in muestras]

    def verificar(self, referencia: list, n_muestras=3, timeout_s=12) -> tuple[bool, float]:
        """Devuelve (aceptado, mejor_similitud)."""
        print("[biometria] Verificacion facial: mira a la camara...")
        actuales = self._capturar("Verificacion facial", n_muestras, timeout_s)
        if not actuales:
            return False, 0.0
        modo = getattr(cv2, "FaceRecognizerSF_FR_COSINE", 0)
        mejor = max(
            float(self.reconocedor.match(np.asarray(ref, dtype=np.float32).reshape(1, -1),
                                         act.reshape(1, -1).astype(np.float32), modo))
            for ref in referencia for act in actuales
        )
        return mejor >= self.umbral, round(mejor, 4)
