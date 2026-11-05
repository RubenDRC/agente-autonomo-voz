"""
percepcion/percepcion.py
========================
Modulo de Percepcion del Entorno: lee la pantalla actual del aplicativo y la
convierte en una lista de elementos con descripcion legible:

  - campos de texto (marcando los sensibles: clave, clave dinamica, PIN)
  - listas desplegables con sus opciones
  - botones, enlaces y preguntas desplegables (<summary>)
  - textos con identificador, para la accion "leer" (saldos, folios...)

Cada percepcion queda en la auditoria con una captura de pantalla en la que
los campos sensibles aparecen tapados.
"""

import re
from dataclasses import dataclass, field

import configuracion as cfg
from comun.texto import normalizar


@dataclass
class EstadoInterfaz:
    inputs: object = None
    desc_inputs: list = field(default_factory=list)
    idx_inputs: list = field(default_factory=list)
    secretos: list = field(default_factory=list)       # por campo: None o nombre del secreto
    selects: object = None
    desc_selects: list = field(default_factory=list)
    idx_selects: list = field(default_factory=list)
    opciones_selects: list = field(default_factory=list)  # por lista: [(valor, etiqueta), ...]
    botones: object = None
    txt_botones: list = field(default_factory=list)
    idx_botones: list = field(default_factory=list)

    def mascaras(self):
        """Locators de campos sensibles, para taparlos en las capturas."""
        return [self.inputs.nth(i) for i, s in zip(self.idx_inputs, self.secretos) if s]

    def tiene_ingreso(self) -> bool:
        """True si la pantalla actual es un formulario de ingreso (campo de clave)."""
        return "clave" in self.secretos


def _mostrar(texto):
    if cfg.DETALLE_PERCEPCION:
        print(texto)


def en_zona_excluida(elemento) -> bool:
    try:
        return elemento.evaluate("(el, sel) => !!el.closest(sel)", cfg.ZONAS_EXCLUIDAS)
    except Exception:
        return False


TIPOS_INFORMATIVOS = {"password", "email", "number", "tel", "search", "date"}


def describir_input(elemento) -> str:
    """Descripcion legible de un campo: la etiqueta visible primero y luego los
    atributos que aporten algo. Se descartan los textos sin letras ni numeros
    (p. ej. el placeholder '••••••••') y los repetidos, porque diluyen la
    similitud semantica: 'Clave · password' en lugar de '•••••••• clave clave password Clave'."""
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
            }""")
    except Exception:
        etiqueta = ""
    partes = [etiqueta] + [elemento.get_attribute(a) for a in ("aria-label", "placeholder", "name", "id")]
    tipo = (elemento.get_attribute("type") or "").lower()
    if tipo in TIPOS_INFORMATIVOS:
        partes.append(tipo)

    limpias, vistas = [], set()
    for parte in partes:
        texto = " ".join((parte or "").split())
        clave = normalizar(texto)
        if not re.search(r"[a-z0-9]", clave) or clave in vistas:
            continue
        vistas.add(clave)
        limpias.append(texto)
    return " · ".join(limpias)


def tipo_secreto(elemento, descripcion: str):
    """'clave', 'clave_dinamica' o None. Los campos sensibles nunca se llenan por voz."""
    d = normalizar(descripcion)
    if re.search(r"dinamica|otp|token|codigo de (verificacion|seguridad)", d):
        return "clave_dinamica"
    tipo = (elemento.get_attribute("type") or "").lower()
    if tipo == "password" or re.search(r"contrasena|password|\bclave\b|\bpin\b", d):
        return "clave"
    return None


def explorar_inputs(page):
    inputs = page.locator("input, textarea")
    descripciones, indices, secretos = [], [], []
    for i in range(inputs.count()):
        el = inputs.nth(i)
        try:
            tipo = el.get_attribute("type")
            if tipo in ("hidden", "submit", "button") or not el.is_visible() or en_zona_excluida(el):
                continue
        except Exception:
            continue
        desc = describir_input(el)
        if desc:
            secreto = tipo_secreto(el, desc)
            descripciones.append(desc)
            indices.append(i)
            secretos.append(secreto)
            _mostrar(f"  - campo[{i}]: {desc}" + (f"  [SENSIBLE: {secreto}]" if secreto else ""))
    return inputs, descripciones, indices, secretos


def explorar_selects(page):
    selects = page.locator("select")
    descripciones, indices, opciones = [], [], []
    for i in range(selects.count()):
        el = selects.nth(i)
        try:
            if not el.is_visible() or en_zona_excluida(el):
                continue
            ops = el.evaluate("el => Array.from(el.options).map(o => [o.value, o.text.trim()])")
        except Exception:
            continue
        desc = describir_input(el)
        if desc:
            descripciones.append(desc)
            indices.append(i)
            opciones.append([tuple(o) for o in ops])
            _mostrar(f"  - lista[{i}]: {desc} -> {[o[1] for o in ops]}")
    return selects, descripciones, indices, opciones


def explorar_botones(page):
    botones = page.locator("button, [role='button'], input[type='submit'], a[href], summary")
    textos, indices = [], []
    for i in range(botones.count()):
        b = botones.nth(i)
        try:
            if not b.is_visible() or en_zona_excluida(b):
                continue
            texto = b.inner_text().strip() or b.get_attribute("aria-label") or b.get_attribute("value") or ""
            texto = " ".join(texto.split())
        except Exception:
            continue
        if texto:
            textos.append(texto)
            indices.append(i)
            _mostrar(f"  - boton[{i}]: {texto}")
    return botones, textos, indices


def leer_textos(page) -> list[dict]:
    """Textos visibles con identificador (data-testid o id), para la accion 'leer'."""
    try:
        return page.evaluate(
            """(excluir) => {
                const visible = el => !el.hidden && !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
                const salida = [];
                for (const el of document.querySelectorAll('[data-testid],[id]')) {
                    if (el.closest(excluir)) continue;
                    if (['INPUT','SELECT','TEXTAREA','BUTTON','SCRIPT','STYLE'].includes(el.tagName)) continue;
                    const texto = (el.innerText || '').trim().replace(/\\s+/g, ' ');
                    if (!texto || texto.length > 160 || !visible(el)) continue;
                    const id = el.dataset.testid || el.id;
                    salida.push({id, texto, desc: `${id.replace(/[-_]/g, ' ')} ${el.getAttribute('aria-label') || ''} ${texto.slice(0, 80)}`});
                }
                return salida;
            }""", cfg.ZONAS_EXCLUIDAS)
    except Exception:
        return []


def percibir(page, seg, motivo: str) -> EstadoInterfaz:
    ui = EstadoInterfaz(*explorar_inputs(page), *explorar_selects(page), *explorar_botones(page))
    captura = seg.auditor.captura(page, "percepcion", ui.mascaras())
    seg.auditor.registrar(
        "PERCEPCION", "estado_interfaz",
        motivo=motivo, url=page.url, titulo=page.title(),
        n_campos=len(ui.desc_inputs), n_listas=len(ui.desc_selects), n_botones=len(ui.txt_botones),
        campos=[d + (f" [sensible:{s}]" if s else "") for d, s in zip(ui.desc_inputs, ui.secretos)],
        listas=ui.desc_selects, botones=ui.txt_botones, captura=captura,
    )
    return ui
