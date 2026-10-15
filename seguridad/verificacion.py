"""
seguridad/verificacion.py
=========================
Verificacion de postcondiciones: despues de cada accion, comprueba si el
entorno quedo en el estado esperado y lee la retroalimentacion que muestra
la aplicacion (alertas, errores bajo los campos, mensajes de exito).

Resultados posibles:
  OK          -> la accion tuvo el efecto esperado
  FALLO       -> el campo no quedo con el valor, o la app mostro un error
  SIN_EFECTO  -> el clic no cambio ni la URL ni el contenido visible
"""

import hashlib
import re

from .auditoria import MASCARA

# Recolecta mensajes visibles. Clasifica por clase/rol/testid del elemento.
_JS_MENSAJES = """
() => {
  const visible = el => !el.hidden && !!(el.offsetWidth || el.offsetHeight
                     || el.getClientRects().length);
  const vistos = new Set(), salida = [];
  const sel = '[role=alert], [role=status], .alert, .error, [data-testid=mensaje-exito]';
  for (const el of document.querySelectorAll(sel)) {
    const texto = (el.innerText || '').trim();
    if (!texto || !visible(el) || vistos.has(texto)) continue;
    vistos.add(texto);
    const firma = [el.className, el.getAttribute('role'), el.dataset.testid]
                  .join(' ').toLowerCase();
    let tipo = 'info';
    if (/exito|success/.test(firma)) tipo = 'exito';
    else if (/error/.test(firma) || el.getAttribute('role') === 'alert') tipo = 'error';
    salida.push({tipo, texto: texto.slice(0, 200), origen: el.id || el.dataset.testid || ''});
  }
  return salida;
}
"""


def _compacto(texto: str) -> str:
    """Quita separadores que las apps suelen reformatear: '$ 150.000' -> '150000'."""
    return re.sub(r"[\s.,$'-]", "", texto.lower())


class Verificador:

    @staticmethod
    def estado_pagina(page) -> dict:
        """Instantanea minima para comparar antes/despues de una accion."""
        try:
            texto = page.evaluate("() => document.body ? document.body.innerText : ''")
        except Exception:
            texto = ""
        return {
            "url": page.url,
            "titulo": page.title(),
            "huella": hashlib.sha1(texto.encode("utf-8")).hexdigest()[:12],
            "errores": [m["texto"] for m in Verificador.leer_mensajes(page)
                        if m["tipo"] == "error"],
        }

    @staticmethod
    def leer_mensajes(page) -> list[dict]:
        try:
            return page.evaluate(_JS_MENSAJES)
        except Exception:
            return []

    def verificar_escritura(self, locator, esperado: str, sensible=False) -> dict:
        try:
            leido = locator.input_value()
        except Exception as e:
            return {"resultado": "FALLO", "motivo": f"no se pudo leer el campo: {e}"}
        coincide = leido == esperado
        ajustado = not coincide and bool(leido) and _compacto(leido) == _compacto(esperado)
        datos = {
            "resultado": "OK" if (coincide or ajustado) else "FALLO",
            "criterio": "valor del campo == texto esperado",
            "valor_leido": MASCARA if sensible else leido,
        }
        if ajustado:
            datos["nota"] = "la aplicacion ajusto el formato (ej. 150.000 -> 150000)"
        elif not coincide:
            datos["motivo"] = ("el campo recorto o transformo el valor"
                               if leido and leido in esperado else "el valor no quedo escrito")
        return datos

    def verificar_clic(self, page, antes: dict) -> dict:
        despues = self.estado_pagina(page)
        mensajes = self.leer_mensajes(page)
        errores = [m for m in mensajes if m["tipo"] == "error"]
        exitos = [m for m in mensajes if m["tipo"] == "exito"]
        cambio_url = despues["url"] != antes["url"]
        cambio_contenido = despues["huella"] != antes["huella"]
        # Un error que ya estaba visible antes del clic no se atribuye a este
        # clic, salvo que la pantalla no haya cambiado en absoluto.
        nuevos = [m for m in errores if m["texto"] not in antes.get("errores", [])]
        persistentes = [m for m in errores if m not in nuevos]

        if nuevos or (persistentes and not cambio_url and not cambio_contenido):
            resultado = "FALLO"
        elif cambio_url or exitos or cambio_contenido:
            resultado = "OK"
        else:
            resultado = "SIN_EFECTO"

        return {
            "resultado": resultado,
            "criterio": "sin errores visibles y con cambio de URL o contenido",
            "url_antes": antes["url"],
            "url_despues": despues["url"],
            "cambio_url": cambio_url,
            "cambio_contenido": cambio_contenido,
            "errores_nuevos": len(nuevos),
            "mensajes": mensajes,
        }
