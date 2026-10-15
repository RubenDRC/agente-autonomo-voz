"""
seguridad/billetera.py
======================
Billetera (wallet) de credenciales cifrada, organizada por aplicativo.

  - El archivo 'credenciales.wallet' esta cifrado con Fernet (AES-128-CBC +
    HMAC-SHA256). La llave se deriva de una CLAVE MAESTRA con
    PBKDF2-HMAC-SHA256 (600.000 iteraciones y sal aleatoria).
  - Cada aplicativo se identifica por su ORIGEN (esquema://host:puerto).
    El agente pide la credencial segun la URL de la pagina que esta operando,
    asi una credencial nunca se inyecta en un sitio distinto al registrado.
  - Las credenciales nunca pasan por la voz ni por el modelo de lenguaje:
    las entrega el modulo de seguridad directamente al campo.
  - Opcionalmente guarda la plantilla biometrica (rostro) cifrada.

Contenido descifrado:
{
  "version": 1,
  "aplicativos": {
     "banco_sandbox": {
        "nombre": "Banco Sandbox",
        "origen": "http://localhost:5173",
        "secretos": {"usuario": "...", "clave": "...", "clave_dinamica": "..."}
     }
  },
  "biometria": null | {"muestras": [[...128 floats...], ...], "enrolado": "..."}
}

Herramientas (ver seguridad/__main__.py):
  python -m seguridad crear
  python -m seguridad agregar --app banco_sandbox --nombre "Banco Sandbox" \
                              --origen http://localhost:5173
  python -m seguridad listar
  python -m seguridad eliminar --app banco_sandbox
  python -m seguridad enrolar-rostro
"""

import base64
import getpass
import json
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# Rutas fijas respecto al proyecto (carpeta que contiene seguridad/), no
# respecto a la carpeta desde donde se ejecuta el comando.
DIR_PROYECTO = Path(__file__).resolve().parent.parent
RUTA_DEFECTO = DIR_PROYECTO / "credenciales.wallet"
ITERACIONES = 600_000
VAR_ENTORNO = "AGENTE_CLAVE_MAESTRA"   # solo para pruebas automatizadas


class BilleteraError(Exception):
    pass


def _derivar_llave(clave_maestra: str, sal: bytes, iteraciones: int) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                     salt=sal, iterations=iteraciones)
    return base64.urlsafe_b64encode(kdf.derive(clave_maestra.encode("utf-8")))


def normalizar_origen(url: str) -> str:
    """'http://127.0.0.1:5173/login.html?x=1' -> 'http://localhost:5173'"""
    p = urlparse(url if "://" in url else "http://" + url)
    host = (p.hostname or "").lower()
    if host in ("127.0.0.1", "::1"):
        host = "localhost"
    puerto = p.port or (443 if p.scheme == "https" else 80)
    return f"{p.scheme}://{host}:{puerto}"


def pedir_clave_maestra(confirmar=False) -> str:
    """Pide la clave maestra por teclado (oculta). Nunca por voz."""
    desde_entorno = os.getenv(VAR_ENTORNO)
    if desde_entorno:
        return desde_entorno
    clave = getpass.getpass("Clave maestra de la billetera: ")
    if confirmar:
        if len(clave) < 8:
            raise BilleteraError("La clave maestra debe tener al menos 8 caracteres.")
        if clave != getpass.getpass("Repite la clave maestra: "):
            raise BilleteraError("Las claves no coinciden.")
    return clave


class Billetera:
    def __init__(self, ruta=RUTA_DEFECTO):
        self.ruta = Path(ruta)
        self._datos = None
        self._fernet = None
        self._sal = None
        self._iteraciones = ITERACIONES

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------

    @property
    def existe(self) -> bool:
        return self.ruta.exists()

    @property
    def desbloqueada(self) -> bool:
        return self._datos is not None

    def crear(self, clave_maestra: str) -> None:
        if self.existe:
            raise BilleteraError(f"Ya existe una billetera en {self.ruta}")
        self._sal = os.urandom(16)
        self._fernet = Fernet(_derivar_llave(clave_maestra, self._sal, self._iteraciones))
        self._datos = {"version": 1, "aplicativos": {}, "biometria": None}
        self._guardar()

    def desbloquear(self, clave_maestra: str) -> None:
        if not self.existe:
            raise BilleteraError(f"No existe la billetera {self.ruta}. "
                                 "Creala con: python -m seguridad crear")
        contenedor = json.loads(self.ruta.read_text(encoding="utf-8"))
        self._sal = base64.b64decode(contenedor["sal"])
        self._iteraciones = contenedor["iteraciones"]
        fernet = Fernet(_derivar_llave(clave_maestra, self._sal, self._iteraciones))
        try:
            claro = fernet.decrypt(contenedor["datos"].encode("ascii"))
        except InvalidToken:
            raise BilleteraError("Clave maestra incorrecta.") from None
        self._fernet = fernet
        self._datos = json.loads(claro)

    def bloquear(self) -> None:
        """Descarta el contenido descifrado de la memoria del proceso."""
        self._datos = None
        self._fernet = None

    def _exigir_desbloqueo(self):
        if not self.desbloqueada:
            raise BilleteraError("La billetera esta bloqueada.")

    def _guardar(self) -> None:
        self._exigir_desbloqueo()
        token = self._fernet.encrypt(json.dumps(self._datos, ensure_ascii=False).encode("utf-8"))
        contenedor = {
            "formato": "agente-billetera/1",
            "kdf": "PBKDF2-HMAC-SHA256",
            "iteraciones": self._iteraciones,
            "sal": base64.b64encode(self._sal).decode("ascii"),
            "cifrado": "Fernet",
            "datos": token.decode("ascii"),
        }
        temporal = self.ruta.with_suffix(".tmp")
        temporal.write_text(json.dumps(contenedor, indent=2), encoding="utf-8")
        os.replace(temporal, self.ruta)          # escritura atomica
        try:
            os.chmod(self.ruta, 0o600)            # solo el propietario (Unix)
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Aplicativos y secretos
    # ------------------------------------------------------------------

    def agregar_aplicativo(self, app_id: str, nombre: str, origen: str, secretos: dict) -> None:
        self._exigir_desbloqueo()
        self._datos["aplicativos"][app_id] = {
            "nombre": nombre,
            "origen": normalizar_origen(origen),
            "secretos": dict(secretos),
        }
        self._guardar()

    def eliminar_aplicativo(self, app_id: str) -> None:
        self._exigir_desbloqueo()
        if self._datos["aplicativos"].pop(app_id, None) is None:
            raise BilleteraError(f"No existe el aplicativo '{app_id}'.")
        self._guardar()

    def listar(self) -> list[dict]:
        """Lista aplicativos y NOMBRES de secretos (nunca sus valores)."""
        self._exigir_desbloqueo()
        return [{"app_id": k, "nombre": v["nombre"], "origen": v["origen"],
                 "secretos": sorted(v["secretos"])}
                for k, v in self._datos["aplicativos"].items()]

    def aplicativo_por_url(self, url: str):
        """Devuelve (app_id, entrada) cuyo origen coincide con la URL, o (None, None)."""
        self._exigir_desbloqueo()
        origen = normalizar_origen(url)
        for app_id, entrada in self._datos["aplicativos"].items():
            if entrada["origen"] == origen:
                return app_id, entrada
        return None, None

    def todos_los_secretos(self, excluir=()) -> list[str]:
        """Valores de todos los secretos (para enmascararlos en la auditoria)."""
        self._exigir_desbloqueo()
        return [str(v) for app in self._datos["aplicativos"].values()
                for nombre, v in app["secretos"].items() if v and nombre not in excluir]

    # ------------------------------------------------------------------
    # Biometria (plantilla facial cifrada dentro de la billetera)
    # ------------------------------------------------------------------

    def guardar_biometria(self, muestras: list) -> None:
        self._exigir_desbloqueo()
        self._datos["biometria"] = {
            "muestras": muestras,
            "enrolado": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        self._guardar()

    def obtener_biometria(self):
        self._exigir_desbloqueo()
        bio = self._datos.get("biometria")
        return bio["muestras"] if bio else None
