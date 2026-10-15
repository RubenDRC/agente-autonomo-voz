"""
agente_voz.py  (v2: con Modulo de Seguridad y Verificacion)
===========================================================
Modulos del agente y donde viven en este archivo:

  CAPTURA DE INSTRUCCIONES  -> capturar()            (usa voz.py)
  PERCEPCION DEL ENTORNO    -> percibir()            (Playwright: campos y botones)
  PLANIFICACION DE TAREAS   -> planificar()          (intencion del comando)
  DECISION Y ACCION         -> escribir_en_campo(), pulsar_boton(),
                               autenticar_con_billetera()
  SEGURIDAD Y VERIFICACION  -> paquete seguridad/    (transversal)
        - Auditoria: cada modulo registra lo que hace, con fecha y hora
        - Credenciales: billetera cifrada por aplicativo (+ facial opcional)
        - Verificacion: comprueba el efecto de cada accion y lee errores

Flujo de un paso (un comando de voz):
  1. CAPTURA        -> transcribe lo que dices                     [log]
  2. PLANIFICACION  -> decide si es ESCRIBIR, CLIC o AUTENTICAR    [log]
  3. DECISION       -> elige el campo/boton y su % de similitud    [log]
  4. ACCION         -> escribe (texto por voz o de la billetera)   [log]
                       o hace clic
  5. VERIFICACION   -> valida el resultado; si falla, retroalimenta [log]
  6. PERCEPCION     -> vuelve a leer la pantalla (+ captura)       [log]

Politica de seguridad: los campos sensibles (clave, clave dinamica, PIN)
NUNCA se llenan dictando por voz; el valor sale de la billetera cifrada.
"""

import os
import re
import time
import traceback
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import sync_playwright
from sentence_transformers import SentenceTransformer, util

import voz  # <-- modulo de voz (voz.py en la misma carpeta)
from seguridad import MASCARA, ModuloSeguridadVerificacion

# ============================================================
# CONFIGURACION
# ============================================================

URL = "http://localhost:5173/login.html"
UMBRAL = 0.35  # similitud minima para aceptar un emparejamiento
MODELO_EMBEDDINGS = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
HEADLESS = os.getenv("AGENTE_HEADLESS") == "1"
ESPERA_TRAS_ACCION_MS = 1200  # la app simula latencias de 600-900 ms

# El "Panel de pruebas" del sandbox no es parte del aplicativo: se ignora
# para que el agente no pulse "Reiniciar" por error.
ZONAS_EXCLUIDAS = "[data-testid='panel-pruebas']"

# --- Seguridad y Verificacion ---
# Rutas relativas a ESTE archivo: funciona igual desde VS Code o cualquier carpeta
DIR_BASE = Path(__file__).resolve().parent
RUTA_BILLETERA = DIR_BASE / "credenciales.wallet"
CARPETA_AUDITORIA = DIR_BASE / "auditoria"
AUTENTICACION_FACIAL = False  # True = pide rostro antes de entregar cada clave
MINUTOS_DESBLOQUEO = 5        # la billetera se re-bloquea tras inactividad

# Palabras que activan intenciones especiales (se comparan sin tildes)
PALABRAS_SALIR = ("salir", "terminar")
PALABRAS_CREDENCIALES = ("credencial", "autentica", "billetera", "wallet")

print("[agente] Cargando modelo de embeddings multilingue...")
modelo = SentenceTransformer(MODELO_EMBEDDINGS)
print("[agente] Modelo listo.")


# ============================================================
# UTILIDADES
# ============================================================

def normalizar(texto: str) -> str:
    """Minusculas y sin tildes: 'Contraseña Dinámica' -> 'contrasena dinamica'."""
    sin_tildes = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in sin_tildes if not unicodedata.combining(c)).lower()


def pct(score: float) -> float:
    """Similitud coseno expresada en porcentaje (no es una probabilidad)."""
    return round(score * 100, 1)


def mejor_match(consulta: str, descripciones: list[str]):
    """Devuelve (indice, score) del elemento mas parecido a la consulta."""
    if not descripciones:
        return -1, 0.0
    emb_consulta = modelo.encode(consulta, convert_to_tensor=True)
    emb_items = modelo.encode(descripciones, convert_to_tensor=True)
    sims = util.cos_sim(emb_consulta, emb_items)[0]
    idx = int(sims.argmax())
    return idx, float(sims[idx])


def en_zona_excluida(elemento) -> bool:
    try:
        return elemento.evaluate("(el, sel) => !!el.closest(sel)", ZONAS_EXCLUIDAS)
    except Exception:
        return False


def describir_input(elemento) -> str:
    """Construye una descripcion legible de un input a partir de sus atributos."""
    partes = []
    for attr in ("placeholder", "aria-label", "name", "id", "type"):
        valor = elemento.get_attribute(attr)
        if valor:
            partes.append(valor)

    # Texto del <label> asociado (muy util para identificar el campo)
    try:
        etiqueta = elemento.evaluate(
            """el => {
                if (el.labels && el.labels.length) return el.labels[0].innerText;
                const id = el.getAttribute('id');
                if (id) {
                    const l = document.querySelector(`label[for="${id}"]`);
                    if (l) return l.innerText;
                }
                return '';
            }"""
        )
        if etiqueta:
            partes.append(etiqueta)
    except Exception:
        pass

    return " ".join(partes).strip()


def tipo_secreto(elemento, descripcion: str):
    """Clasifica un campo como sensible. Devuelve el nombre del secreto
    en la billetera ('clave', 'clave_dinamica') o None si no es sensible."""
    d = normalizar(descripcion)
    if re.search(r"dinamica|otp|token|codigo de (verificacion|seguridad)", d):
        return "clave_dinamica"
    tipo = (elemento.get_attribute("type") or "").lower()
    if tipo == "password" or re.search(r"contrasena|password|\bclave\b|\bpin\b", d):
        return "clave"
    return None


# ============================================================
# MODULO: PERCEPCION DEL ENTORNO
# ============================================================

@dataclass
class EstadoInterfaz:
    inputs: object
    desc_inputs: list
    idx_inputs: list
    secretos: list      # por campo: None o nombre del secreto
    botones: object
    txt_botones: list
    idx_botones: list

    def mascaras(self):
        """Locators de campos sensibles, para taparlos en las capturas."""
        return [self.inputs.nth(i) for i, s in zip(self.idx_inputs, self.secretos) if s]


def explorar_inputs(page):
    """Devuelve (locator, descripciones, indices, secretos) de inputs visibles."""
    inputs = page.locator("input, textarea")
    total = inputs.count()
    descripciones, indices, secretos = [], [], []

    print(f"\n[agente] Inputs/textarea encontrados: {total}")
    for i in range(total):
        el = inputs.nth(i)
        try:
            tipo = el.get_attribute("type")
            if tipo == "hidden" or not el.is_visible() or en_zona_excluida(el):
                continue
        except Exception:
            continue

        desc = describir_input(el)
        if desc:
            secreto = tipo_secreto(el, desc)
            descripciones.append(desc)
            indices.append(i)
            secretos.append(secreto)
            marca = f"  [SENSIBLE: {secreto}]" if secreto else ""
            print(f"  - input[{i}]: {desc}{marca}")

    return inputs, descripciones, indices, secretos


def explorar_botones(page):
    """Devuelve (locator, textos, indices) de botones y enlaces visibles."""
    # Los accesos del inicio (Enviar dinero, Movimientos...) son enlaces <a>
    botones = page.locator("button, [role='button'], input[type='submit'], a[href]")
    total = botones.count()
    textos, indices = [], []

    print(f"\n[agente] Botones/enlaces encontrados: {total}")
    for i in range(total):
        b = botones.nth(i)
        try:
            if not b.is_visible() or en_zona_excluida(b):
                continue
            texto = b.inner_text().strip()
            if not texto:
                texto = (b.get_attribute("aria-label")
                         or b.get_attribute("value") or "")
            texto = " ".join(texto.split())  # colapsa saltos de linea
        except Exception:
            continue

        if texto:
            textos.append(texto)
            indices.append(i)
            print(f"  - boton[{i}]: {texto}")

    return botones, textos, indices


def percibir(page, seg, motivo: str) -> EstadoInterfaz:
    ui = EstadoInterfaz(*explorar_inputs(page), *explorar_botones(page))
    captura = seg.auditor.captura(page, "percepcion", ui.mascaras())
    seg.auditor.registrar(
        "PERCEPCION", "estado_interfaz",
        motivo=motivo, url=page.url, titulo=page.title(),
        n_campos=len(ui.desc_inputs), n_botones=len(ui.txt_botones),
        campos=[d + (f" [sensible:{s}]" if s else "")
                for d, s in zip(ui.desc_inputs, ui.secretos)],
        botones=ui.txt_botones, captura=captura,
    )
    return ui


# ============================================================
# MODULO: CAPTURA DE INSTRUCCIONES
# ============================================================

def capturar(seg, proposito: str) -> str:
    t0 = time.perf_counter()
    try:
        texto = (voz.escuchar(modo="enter") or "").strip()
    except Exception as e:
        seg.auditor.registrar("CAPTURA", "error_captura", nivel="ERROR",
                              proposito=proposito, error=str(e))
        return ""
    seg.auditor.registrar(
        "CAPTURA", "texto_capturado" if texto else "captura_vacia",
        nivel="INFO" if texto else "WARN",
        proposito=proposito, texto=texto,
        duracion_s=round(time.perf_counter() - t0, 2),
    )
    return texto


def limpiar_dictado(texto: str) -> str:
    """Ajusta lo que devuelve el reconocimiento de voz antes de escribirlo:
    'Arroba Lucía.' -> '@lucia'   |   '310 555 8842' -> '3105558842'
    '150.000'       -> '150000'   |   quita puntuacion al inicio y al final."""
    t = texto.strip().strip("¿¡.,;:!? ")
    t = re.sub(r"\barroba\s*", "@", t, flags=re.IGNORECASE)
    t = re.sub(r"(?<=\d)[\s.](?=\d)", "", t)             # une grupos de digitos
    t = re.sub(r"@\S+", lambda m: normalizar(m.group()), t)  # llaves sin tildes
    return t


# ============================================================
# MODULO: PLANIFICACION DE TAREAS
# ============================================================

def planificar(accion: str, ui: EstadoInterfaz, seg) -> str:
    """Clasifica el comando en SALIR | AUTENTICAR | CLIC | ESCRIBIR."""
    t = normalizar(accion)
    score_campo = score_boton = 0.0

    if any(p in t for p in PALABRAS_SALIR):
        intencion, regla = "SALIR", "palabra clave de salida"
    elif any(p in t for p in PALABRAS_CREDENCIALES):
        intencion, regla = "AUTENTICAR", "palabra clave de credenciales"
    else:
        # Heuristica: si el comando se parece mas a un boton que a un campo,
        # es un clic; si no, es escribir en un campo.
        _, score_campo = mejor_match(accion, ui.desc_inputs)
        _, score_boton = mejor_match(accion, ui.txt_botones)
        if score_boton > score_campo and score_boton >= UMBRAL:
            intencion, regla = "CLIC", "similitud con boton > similitud con campo"
        else:
            intencion, regla = "ESCRIBIR", "similitud con campo >= similitud con boton"

    seg.auditor.registrar(
        "PLANIFICACION", "intencion", comando=accion, intencion=intencion, regla=regla,
        similitud_campo_pct=pct(score_campo), similitud_boton_pct=pct(score_boton),
    )
    return intencion


# ============================================================
# MODULO: DECISION Y ACCION (+ verificacion de cada accion)
# ============================================================

def registrar_decision(seg, tipo, candidatos, idx_rel, score) -> bool:
    aceptado = idx_rel != -1 and score >= UMBRAL
    seg.auditor.registrar(
        "DECISION_ACCION", "decision", nivel="INFO" if aceptado else "WARN",
        tipo=tipo,
        elemento=candidatos[idx_rel] if idx_rel != -1 else None,
        similitud=round(score, 4), confianza_pct=pct(score),
        umbral_pct=pct(UMBRAL), aceptado=aceptado,
    )
    if not aceptado:
        print(f"[agente] Confianza {pct(score)} % por debajo del umbral "
              f"({pct(UMBRAL)} %). No actuo.")
    return aceptado


def retroalimentar(seg, verificacion: dict):
    """Si la verificacion falla, informa el motivo (retroalimentacion al plan)."""
    if verificacion["resultado"] == "OK":
        return
    errores = [m["texto"] for m in verificacion.get("mensajes", []) if m["tipo"] == "error"]
    mensaje = ("; ".join(errores) or verificacion.get("motivo")
               or "la accion no produjo cambios visibles")
    seg.auditor.registrar("VERIFICACION", "retroalimentacion", nivel="WARN",
                          destino="PLANIFICACION", mensaje=mensaje)
    print(f"[agente] La verificacion reporta: {mensaje}")


def ejecutar_escritura(seg, objetivo, campo: str, texto: str, sensible: bool, origen: str) -> bool:
    try:
        objetivo.click()
        objetivo.fill(texto)
        exito, error = True, None
    except Exception as e:
        exito, error = False, str(e)

    seg.auditor.registrar(
        "DECISION_ACCION", "accion", nivel="INFO" if exito else "ERROR",
        tipo="escribir", campo=campo,
        texto=MASCARA if sensible else texto, origen_texto=origen,
        exito=exito, **({"error": error} if error else {}),
    )
    if not exito:
        return False

    v = seg.verificador.verificar_escritura(objetivo, texto, sensible=sensible)
    seg.auditor.registrar("VERIFICACION", "verificacion",
                          nivel="INFO" if v["resultado"] == "OK" else "WARN",
                          accion="escribir", campo=campo, **v)
    retroalimentar(seg, v)
    return v["resultado"] == "OK"


def ejecutar_clic(seg, page, objetivo, nombre: str) -> bool:
    antes = seg.verificador.estado_pagina(page)
    try:
        objetivo.click()
        exito, error = True, None
    except Exception as e:
        exito, error = False, str(e)

    seg.auditor.registrar(
        "DECISION_ACCION", "accion", nivel="INFO" if exito else "ERROR",
        tipo="clic", boton=nombre, exito=exito, **({"error": error} if error else {}),
    )
    if not exito:
        return False

    try:
        page.wait_for_load_state("domcontentloaded", timeout=10000)
    except Exception:
        pass
    page.wait_for_timeout(ESPERA_TRAS_ACCION_MS)

    v = seg.verificador.verificar_clic(page, antes)
    seg.auditor.registrar("VERIFICACION", "verificacion",
                          nivel="INFO" if v["resultado"] == "OK" else "WARN",
                          accion="clic", boton=nombre, **v)
    retroalimentar(seg, v)
    return v["resultado"] == "OK"


def escribir_en_campo(page, ui: EstadoInterfaz, accion_voz: str, seg) -> bool:
    """Empareja el comando con un campo y escribe en el.
    Primero decide el campo; asi, si es sensible, no se pide dictar el valor."""
    idx_rel, score = mejor_match(accion_voz, ui.desc_inputs)
    if not registrar_decision(seg, "campo", ui.desc_inputs, idx_rel, score):
        return False

    campo = ui.desc_inputs[idx_rel]
    secreto = ui.secretos[idx_rel]
    objetivo = ui.inputs.nth(ui.idx_inputs[idx_rel])
    print(f"\n[agente] Campo elegido: '{campo}' ({pct(score)} %)")

    if secreto:
        seg.auditor.registrar("SEGURIDAD", "campo_sensible", campo=campo, secreto=secreto,
                              politica="no se dicta por voz; se toma de la billetera")
        print("[agente] Campo sensible: tomo el valor de la billetera (no lo dictes).")
        texto = seg.obtener_credencial(page.url, secreto)
        if texto is None:
            print("[agente] No se obtuvo la credencial. No escribo.")
            return False
        return ejecutar_escritura(seg, objetivo, campo, texto, sensible=True, origen="billetera")

    print("Ahora di QUE texto escribir.")
    texto = capturar(seg, "texto_a_escribir")
    if not texto:
        return False
    limpio = limpiar_dictado(texto)
    if limpio != texto:
        seg.auditor.registrar("CAPTURA", "texto_normalizado", original=texto,
                              normalizado=limpio)
        texto = limpio
    return ejecutar_escritura(seg, objetivo, campo, texto, sensible=False, origen="voz")


def pulsar_boton(page, ui: EstadoInterfaz, accion_voz: str, seg) -> bool:
    """Empareja el comando con un boton/enlace y hace clic."""
    idx_rel, score = mejor_match(accion_voz, ui.txt_botones)
    if not registrar_decision(seg, "boton", ui.txt_botones, idx_rel, score):
        return False
    nombre = ui.txt_botones[idx_rel]
    print(f"\n[agente] Boton elegido: '{nombre}' ({pct(score)} %)")
    return ejecutar_clic(seg, page, ui.botones.nth(ui.idx_botones[idx_rel]), nombre)


def autenticar_con_billetera(page, ui: EstadoInterfaz, seg) -> bool:
    """Tarea compuesta: usuario + clave desde la billetera y enviar el formulario."""
    seg.auditor.registrar("PLANIFICACION", "subtareas", tarea="autenticacion",
                          plan=["escribir usuario", "escribir clave", "enviar formulario"])

    idx_clave = next((k for k, s in enumerate(ui.secretos) if s == "clave"), -1)
    if idx_clave == -1:
        seg.auditor.registrar("DECISION_ACCION", "decision", nivel="WARN", tipo="campo",
                              aceptado=False, motivo="no hay campo de clave en esta pantalla")
        print("[agente] No veo un formulario de inicio de sesion aqui.")
        return False

    # Campo de usuario: el no sensible que mas se parezca a "usuario"
    candidatos = [k for k, s in enumerate(ui.secretos) if not s]
    descs = [ui.desc_inputs[k] for k in candidatos]
    rel, score = mejor_match("usuario nombre de usuario correo login", descs)
    if not registrar_decision(seg, "campo", descs, rel, score):
        return False
    idx_usuario = candidatos[rel]

    usuario = seg.obtener_credencial(page.url, "usuario")
    clave = seg.obtener_credencial(page.url, "clave") if usuario is not None else None
    if usuario is None or clave is None:
        print("[agente] No se obtuvieron las credenciales. Autenticacion cancelada.")
        return False

    ok = ejecutar_escritura(seg, ui.inputs.nth(ui.idx_inputs[idx_usuario]),
                            ui.desc_inputs[idx_usuario], usuario,
                            sensible=False, origen="billetera")
    ok = ejecutar_escritura(seg, ui.inputs.nth(ui.idx_inputs[idx_clave]),
                            ui.desc_inputs[idx_clave], clave,
                            sensible=True, origen="billetera") and ok
    if not ok:
        return False

    rel, score = mejor_match("entrar ingresar iniciar sesion", ui.txt_botones)
    if not registrar_decision(seg, "boton", ui.txt_botones, rel, score):
        return False
    return ejecutar_clic(seg, page, ui.botones.nth(ui.idx_botones[rel]), ui.txt_botones[rel])


# ============================================================
# PROGRAMA PRINCIPAL
# ============================================================

def main():
    seg = ModuloSeguridadVerificacion(
        ruta_billetera=RUTA_BILLETERA, carpeta_auditoria=CARPETA_AUDITORIA,
        autenticacion_facial=AUTENTICACION_FACIAL, minutos_desbloqueo=MINUTOS_DESBLOQUEO,
    )
    aud = seg.auditor
    aud.registrar("SISTEMA", "inicio_sesion", url=URL, modelo=MODELO_EMBEDDINGS,
                  umbral_pct=pct(UMBRAL), autenticacion_facial=AUTENTICACION_FACIAL,
                  billetera="disponible" if seg.billetera.existe else "no existe",
                  ruta_billetera=str(RUTA_BILLETERA))
    print(f"[seguridad] Billetera: {RUTA_BILLETERA} "
          f"({'encontrada' if seg.billetera.existe else 'NO ENCONTRADA'})")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        page = browser.new_page()
        ui = None
        try:
            print(f"\n[agente] Abriendo {URL}")
            page.goto(URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)

            # 1) Percepcion inicial
            ui = percibir(page, seg, "estado_inicial")

            # 2) Ciclo: captura -> plan -> decision/accion -> verificacion -> percepcion
            print("\n" + "=" * 50)
            print("MODO VOZ. Di 'salir' para terminar.")
            print("Di 'usar mis credenciales' para iniciar sesion con la billetera.")
            print("=" * 50)

            while True:
                aud.nuevo_paso()
                print("\n--- Nuevo comando ---")
                print("Di QUE quieres hacer (ej: 'escribir el usuario', "
                      "'campo de llave', 'continuar').")
                accion = capturar(seg, "comando").lower()
                if not accion:
                    print("[agente] No entendi nada, intenta de nuevo.")
                    continue

                intencion = planificar(accion, ui, seg)

                if intencion == "SALIR":
                    print("[agente] Saliendo.")
                    break
                elif intencion == "AUTENTICAR":
                    autenticar_con_billetera(page, ui, seg)
                elif intencion == "CLIC":
                    pulsar_boton(page, ui, accion, seg)
                elif ui.desc_inputs:
                    escribir_en_campo(page, ui, accion, seg)
                else:
                    aud.registrar("DECISION_ACCION", "decision", nivel="WARN",
                                  tipo="campo", aceptado=False,
                                  motivo="no hay campos de texto en esta pantalla")
                    print("[agente] No hay campos de texto en esta pantalla.")

                # Cierre del ciclo: nueva percepcion del estado resultante
                ui = percibir(page, seg, "tras_accion")

        except KeyboardInterrupt:
            aud.registrar("SISTEMA", "interrupcion", nivel="WARN", motivo="Ctrl+C")
        except Exception as e:
            aud.registrar("SISTEMA", "error_inesperado", nivel="ERROR", error=repr(e),
                          traza=traceback.format_exc(limit=3))
            raise
        finally:
            # 3) Evidencia final y cierre de la auditoria
            ruta = aud.captura(page, "final", ui.mascaras() if ui else [])
            print(f"\n[agente] Screenshot final: {aud.dir / ruta if ruta else '-'}")
            seg.cerrar()
            browser.close()


if __name__ == "__main__":
    main()
