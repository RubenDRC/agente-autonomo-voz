"""
ia/llm.py
=========
Base comun para los proveedores basados en modelos de lenguaje (LLM).
Construye las instrucciones (prompts), interpreta la respuesta JSON y
normaliza los parametros. Cada proveedor concreto solo implementa
_completar(), es decir, la llamada HTTP a su API.

Privacidad: al modelo solo se le envian la instruccion, el catalogo de rutas
(sin pasos) y los contactos de la guia. Nunca credenciales ni datos de pantalla
sensibles.
"""

import json
import re
import time
import urllib.error
import urllib.request

import configuracion as cfg

from .base import ProveedorIA, ResultadoIdentificacion
from .extraccion import normalizar_parametros

SISTEMA_PLAN = (
    "Eres el módulo de planificación de un agente que opera un aplicativo web por "
    "instrucciones de voz en español. Tu única tarea es identificar qué procedimiento "
    "del catálogo corresponde a la instrucción del usuario y extraer sus parámetros. "
    "No inventes procedimientos, pasos ni parámetros. Responde solo con un objeto JSON "
    "válido, sin texto adicional ni bloques de código."
)

FORMATO_PLAN = (
    'Responde con este JSON: {"procedimiento": "<id del catálogo o null>", '
    '"confianza": <número de 0 a 1>, "parametros": {"<nombre>": "<valor>"}, '
    '"explicacion": "<una frase corta>"}\n'
    "Reglas: (1) Si la instrucción no corresponde a ningún procedimiento, usa null. "
    "(2) Para parámetros de tipo opcion usa exactamente una de sus etiquetas. "
    "(3) Para monto usa un entero en pesos, sin puntos ni símbolos. "
    "(4) Para llave: si el usuario nombra a un contacto, usa la llave de ese contacto. "
    "(5) Omite los parámetros que el usuario no mencionó; no los inventes."
)

SISTEMA_ELEMENTO = (
    "Eliges el elemento de una interfaz gráfica que corresponde a la descripción de un "
    "paso. Responde solo con JSON válido, sin texto adicional."
)


def extraer_json(texto: str, claves=("procedimiento", "indice")) -> dict:
    """Interpreta la respuesta del modelo aunque venga con texto, ``` o un bloque
    de razonamiento <think>...</think> alrededor. Prefiere el objeto JSON que
    contenga alguna de las claves esperadas."""
    limpio = re.sub(r"<think>.*?</think>", "", texto or "", flags=re.S)
    limpio = re.sub(r"```(?:json)?", "", limpio).strip()
    decodificador = json.JSONDecoder()
    encontrados = []
    for i, caracter in enumerate(limpio):
        if caracter != "{":
            continue
        try:
            objeto, _ = decodificador.raw_decode(limpio[i:])
        except json.JSONDecodeError:
            continue
        if isinstance(objeto, dict):
            if any(k in objeto for k in claves):
                return objeto
            encontrados.append(objeto)
    if encontrados:
        return encontrados[0]
    raise ValueError(f"la respuesta no contiene JSON: {limpio[:120]!r}")


REINTENTABLES = {429, 500, 502, 503, 529}   # limites de uso o sobrecarga temporal


def _solicitar(req, timeout):
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def http_json(url: str, encabezados: dict, cuerpo=None, timeout: int = 60, intentos: int = 3) -> dict:
    """GET (sin cuerpo) o POST JSON, con reintentos ante limites de uso (429) o sobrecarga."""
    datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
    for intento in range(1, intentos + 1):
        req = urllib.request.Request(url, data=datos, headers=encabezados,
                                     method="POST" if datos is not None else "GET")
        try:
            return _solicitar(req, timeout)
        except urllib.error.HTTPError as e:
            detalle = e.read().decode("utf-8", errors="replace")[:400]
            if e.code in REINTENTABLES and intento < intentos:
                espera = min(float(e.headers.get("retry-after") or 2 * 3 ** (intento - 1)), 30)
                print(f"[ia] HTTP {e.code}: reintento en {espera:.0f} s ({intento}/{intentos - 1})")
                time.sleep(espera)
                continue
            raise RuntimeError(f"HTTP {e.code}: {detalle}") from None
        except urllib.error.URLError as e:
            raise RuntimeError(f"sin conexión con {url}: {e.reason}") from None


def post_json(url: str, encabezados: dict, cuerpo: dict, timeout: int) -> dict:
    return http_json(url, encabezados, cuerpo, timeout)


def catalogo_para_modelo(memoria) -> dict:
    procedimientos = []
    for p in memoria.procedimientos:
        procedimientos.append({
            "id": p["id"], "nombre": p["nombre"], "descripcion": p.get("descripcion", ""),
            "frases_de_ejemplo": p.get("frases", [])[:6],
            "parametros": [{
                "nombre": q["nombre"], "tipo": q["tipo"], "obligatorio": q.get("obligatorio", False),
                **({"etiquetas": [e for v in q.get("valores", []) for e in v.get("etiquetas", [])]}
                   if q["tipo"] == "opcion" else {}),
                **({"descripcion": q["pregunta"]} if q.get("pregunta") else {}),
            } for q in p.get("parametros", [])],
        })
    contactos = [{"nombre": c["nombre"], "alias": c.get("alias", []), "llave": c["llave"]}
                 for c in memoria.contactos]
    return {"procedimientos": procedimientos, "contactos": contactos}


class ProveedorLLM(ProveedorIA):
    tipo = "llm"

    def __init__(self, nombre, modelo, grounding_ia=False, temperatura=0):
        super().__init__(nombre, modelo)
        self.grounding_ia = grounding_ia
        self.temperatura = temperatura
        self.timeout = cfg.TIEMPO_MAXIMO_IA_S

    def _completar(self, sistema: str, usuario: str) -> tuple[str, dict]:
        """Devuelve (texto de la respuesta, uso de tokens). Lo implementa cada proveedor."""
        raise NotImplementedError

    def _completar_con_reintento(self, sistema, usuario):
        try:
            return self._completar(sistema, usuario)
        except RuntimeError as e:
            # Algunos modelos no aceptan 'temperature': se reintenta sin ella.
            if self.temperatura is not None and "temperature" in str(e).lower():
                self.temperatura = None
                return self._completar(sistema, usuario)
            raise

    def identificar(self, instruccion, memoria) -> ResultadoIdentificacion:
        t0 = time.perf_counter()
        usuario = (f"Catálogo y contactos:\n{json.dumps(catalogo_para_modelo(memoria), ensure_ascii=False)}\n\n"
                   f"{FORMATO_PLAN}\n\nInstrucción del usuario: «{instruccion}»")
        try:
            texto, tokens = self._completar_con_reintento(SISTEMA_PLAN, usuario)
            datos = extraer_json(texto, claves=("procedimiento",))
            pid = datos.get("procedimiento")
            if pid not in memoria.ids:
                pid = None
            confianza = max(0.0, min(1.0, float(datos.get("confianza") or 0)))
            parametros = (normalizar_parametros(memoria.obtener(pid), datos.get("parametros") or {},
                                                memoria.contactos) if pid else {})
            return ResultadoIdentificacion(pid, confianza, parametros, str(datos.get("explicacion", ""))[:200],
                                           int((time.perf_counter() - t0) * 1000), tokens)
        except Exception as e:
            return ResultadoIdentificacion(None, 0.0, latencia_ms=int((time.perf_counter() - t0) * 1000),
                                           error=str(e)[:300])

    def elegir_elemento(self, objetivo, candidatos):
        if not self.grounding_ia or not candidatos:
            return super().elegir_elemento(objetivo, candidatos)
        lista = "\n".join(f"{i}. {c}" for i, c in enumerate(candidatos))
        usuario = (f"Descripción del paso: «{objetivo}»\nElementos visibles:\n{lista}\n\n"
                   'Responde: {"indice": <número del elemento, o -1 si ninguno corresponde>, '
                   '"confianza": <0 a 1>}')
        try:
            texto, _ = self._completar_con_reintento(SISTEMA_ELEMENTO, usuario)
            datos = extraer_json(texto, claves=("indice",))
            indice = int(datos.get("indice", -1))
            if 0 <= indice < len(candidatos):
                return indice, max(0.0, min(1.0, float(datos.get("confianza") or 0)))
            return -1, 0.0
        except Exception as e:
            print(f"[ia] {self.etiqueta} no pudo elegir el elemento ({e}); uso similitud local.")
            return super().elegir_elemento(objetivo, candidatos)
