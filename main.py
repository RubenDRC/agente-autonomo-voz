"""
main.py
=======
Punto de entrada del agente autonomo. Integra los modulos:

  captura/          Captura de Instrucciones (voz o texto)
  percepcion/       Percepcion del Entorno (Playwright)
  planificacion/    Planificacion de Tareas (rutas de la guia + IA)
  decision_accion/  Decision y Accion (ejecucion paso a paso con verificacion)
  seguridad/        Seguridad y Verificacion (transversal)
  conocimiento/     Memoria de rutas aprendidas de la guia Word
  ia/               Modelos de IA intercambiables

Uso:
  python main.py                                   voz + IA local
  python main.py --entrada texto                   escribir en vez de hablar
  python main.py --ia claude                       planificar con Claude
  python main.py --ia ollama --modelo llama3.1:8b  modelo local con Ollama

Ciclo por instruccion:
  1. CAPTURA        lo que dice el usuario
  2. PLANIFICACION  ¿es una tarea de la guia? -> plan de pasos con parametros
                    si no, se trata como un paso individual (modo v1)
  3. DECISION Y ACCION  cada paso: percibir, elegir elemento, actuar, verificar
  4. PERCEPCION     nuevo estado de la pantalla
"""

import argparse
import sys
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright

import configuracion as cfg
from captura import Captura
from comun.texto import pct
from conocimiento import MemoriaProcedimientos
from decision_accion import Contexto, Ejecutor, paso_a_paso
from ia import crear_proveedor
from percepcion import percibir
from planificacion import Planificador, clasificar_comando, es_comando_de_pantalla, es_salida
from seguridad import ModuloSeguridadVerificacion


def argumentos():
    ap = argparse.ArgumentParser(description="Agente autónomo por voz para aplicativos web")
    ap.add_argument("--entrada", choices=["voz", "texto"], default="voz",
                    help="voz (micrófono) o texto (teclado, para pruebas)")
    ap.add_argument("--ia", default=None, help=f"modelo de IA: {', '.join(cfg.PROVEEDORES_IA)}")
    ap.add_argument("--modelo", default=None, help="identificador del modelo (reemplaza el de configuracion.py)")
    ap.add_argument("--conocimiento", default=str(cfg.RUTA_CONOCIMIENTO), help="memoria de rutas (JSON)")
    ap.add_argument("--url", default=cfg.URL_INICIO)
    ap.add_argument("--headless", action="store_true", help="navegador oculto")
    return ap.parse_args()


def main():
    args = argumentos()
    try:
        ia = crear_proveedor(args.ia, args.modelo)
    except ValueError as e:
        sys.exit(f"[agente] {e}")

    memoria = None
    if Path(args.conocimiento).exists():
        memoria = MemoriaProcedimientos(args.conocimiento)
    else:
        print("[agente] No hay memoria de rutas: solo funcionará el modo paso a paso.\n"
              "         Entrena con: python -m conocimiento entrenar guias/<guia>.docx")

    seg = ModuloSeguridadVerificacion(cfg.RUTA_BILLETERA, cfg.CARPETA_AUDITORIA,
                                      cfg.AUTENTICACION_FACIAL, cfg.MINUTOS_DESBLOQUEO)
    aud = seg.auditor
    captura = Captura(seg, args.entrada)
    aud.registrar("SISTEMA", "inicio_sesion", url=args.url, entrada=args.entrada,
                  ia=ia.nombre, modelo=ia.modelo, grounding=cfg.GROUNDING,
                  conocimiento=memoria.resumen() if memoria else "sin memoria",
                  fuente_conocimiento=memoria.fuente if memoria else None,
                  umbral_elemento_pct=pct(cfg.UMBRAL_ELEMENTO),
                  umbral_procedimiento_pct=pct(cfg.UMBRAL_PROCEDIMIENTO),
                  billetera="disponible" if seg.billetera.existe else "no existe")

    print("\n" + "=" * 64)
    print(f" IA: {ia.etiqueta}   ·   Entrada: {args.entrada}")
    print(f" Conocimiento: {memoria.resumen() if memoria else 'sin memoria (solo paso a paso)'}")
    print(f" Billetera: {'encontrada' if seg.billetera.existe else 'NO ENCONTRADA'} ({cfg.RUTA_BILLETERA})")
    print("=" * 64)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless or cfg.HEADLESS)
        page = browser.new_page()
        ctx = Contexto(page, seg, ia, captura)
        planificador = Planificador(memoria, ia, captura, seg) if memoria else None
        ejecutor = Ejecutor(ctx, planificador, memoria) if memoria else None
        ui = None
        try:
            page.goto(args.url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(1500)
            ui = percibir(page, seg, "estado_inicial")

            print("\nDime qué quieres hacer, por ejemplo: «envía cien mil pesos a Lucía»,")
            print("«¿cuánto tengo en ahorros?» o un paso suelto como «continuar». Di «salir» para terminar.")

            while True:
                aud.nuevo_paso()
                print("\n--- Nueva instrucción ---")
                instruccion = captura.capturar("instruccion")
                if not instruccion:
                    print("[agente] No entendí nada, intenta de nuevo.")
                    continue
                if es_salida(instruccion):
                    aud.registrar("PLANIFICACION", "modo", modo="salir")
                    print("[agente] Saliendo.")
                    break

                es_comando, puntajes = es_comando_de_pantalla(instruccion, ui)
                plan = planificador.planificar(instruccion) if planificador and not es_comando else None

                if plan:
                    aud.registrar("PLANIFICACION", "modo", modo="tarea", procedimiento=plan.id)
                    ejecutor.ejecutar(plan)
                else:
                    motivo = ("coincide con un elemento visible" if es_comando else
                              "no se reconoció una tarea de la guía" if planificador else "sin memoria de rutas")
                    aud.registrar("PLANIFICACION", "modo", modo="paso a paso", motivo=motivo)
                    if planificador and not es_comando:
                        print("[agente] No reconocí una tarea de la guía; lo intento como un paso individual.")
                    intencion = clasificar_comando(instruccion, ui, seg, puntajes)
                    paso_a_paso.ejecutar(ctx, ui, intencion, instruccion)

                ui = percibir(page, seg, "tras_instruccion")

        except (KeyboardInterrupt, EOFError):
            aud.registrar("SISTEMA", "interrupcion", nivel="WARN", motivo="interrupción del usuario")
        except Exception as e:
            aud.registrar("SISTEMA", "error_inesperado", nivel="ERROR", error=repr(e),
                          traza=traceback.format_exc(limit=3))
            raise
        finally:
            ruta = aud.captura(page, "final", ui.mascaras() if ui else [])
            print(f"\n[agente] Captura final: {aud.dir / ruta if ruta else '-'}")
            seg.cerrar()
            browser.close()


if __name__ == "__main__":
    main()
