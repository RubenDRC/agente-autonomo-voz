"""Herramientas de entrenamiento: python -m conocimiento <comando>"""

import argparse
import hashlib
import sys
from datetime import datetime
from pathlib import Path

import configuracion as cfg
from comun.texto import slug

from .lector_word import leer_guia
from .memoria import MemoriaProcedimientos


def _entrenar(args):
    origen = Path(args.guia)
    if not origen.exists():
        sys.exit(f"No existe el archivo {origen}")
    guia, errores, advertencias = leer_guia(origen)

    for a in advertencias:
        print(f"  [advertencia] {a}")
    if errores:
        print("\nLa guía tiene errores; no se guardó la memoria:")
        for e in errores:
            print(f"  [error] {e}")
        sys.exit(1)

    guia["fuente"] = {
        "archivo": origen.name,
        "sha256": hashlib.sha256(origen.read_bytes()).hexdigest(),
        "entrenado": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    destino = Path(args.salida) if args.salida else (
        cfg.DIR_BASE / "conocimiento" / "rutas" / f"{slug(guia['aplicativo']) or origen.stem}.json")
    MemoriaProcedimientos.guardar(guia, destino)

    print(f"\nAplicativo: {guia['aplicativo']}  ·  Origen: {guia['origen']}")
    print(f"{'Procedimiento':<26}{'Frases':>8}{'Parámetros':>12}{'Pasos':>8}")
    for p in guia["procedimientos"]:
        print(f"{p['id']:<26}{len(p['frases']):>8}{len(p['parametros']):>12}{len(p['pasos']):>8}")
    print(f"Contactos: {len(guia['contactos'])}")
    print(f"\nMemoria guardada en {destino}")
    if destino.resolve() != Path(cfg.RUTA_CONOCIMIENTO).resolve():
        print(f"Para usarla, ajusta RUTA_CONOCIMIENTO en configuracion.py o usa --conocimiento {destino}")


def _cargar(args):
    return MemoriaProcedimientos(args.ruta or cfg.RUTA_CONOCIMIENTO)


def _listar(args):
    m = _cargar(args)
    print(m.resumen())
    for p in m.procedimientos:
        params = ", ".join(q["nombre"] + ("*" if q.get("obligatorio") else "") for q in p["parametros"])
        print(f"- {p['id']:<24} {p['nombre']:<32} parámetros: {params or '—'}")
    print("(* = obligatorio)")


def _ver(args):
    m = _cargar(args)
    if args.id not in m.ids:
        sys.exit(f"No existe el procedimiento '{args.id}'. Usa: python -m conocimiento listar")
    p = m.obtener(args.id)
    print(f"{p['nombre']} ({p['id']})\n{p.get('descripcion', '')}\n")
    print("Frases de ejemplo:")
    for f in p["frases"]:
        print(f"  · {f}")
    print("\nPasos:")
    for paso in p["pasos"]:
        valor = f" = {paso['valor']}" if paso.get("valor") else ""
        conf = "   [pide confirmación]" if paso.get("confirmar") else ""
        print(f"  {paso['n']}. {paso['accion']:<12} {paso['objetivo']}{valor}{conf}")


def main():
    ap = argparse.ArgumentParser(prog="python -m conocimiento",
                                 description="Entrenamiento del agente con guías de procedimientos")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("entrenar", help="Lee una guía .docx y guarda sus rutas")
    e.add_argument("guia")
    e.add_argument("--salida", help="ruta del JSON (por defecto conocimiento/rutas/<aplicativo>.json)")
    for nombre, ayuda in (("listar", "Lista los procedimientos aprendidos"), ("ver", "Muestra una ruta")):
        s = sub.add_parser(nombre, help=ayuda)
        if nombre == "ver":
            s.add_argument("id")
        s.add_argument("--ruta", help="memoria a consultar (por defecto la de configuracion.py)")
    args = ap.parse_args()
    {"entrenar": _entrenar, "listar": _listar, "ver": _ver}[args.cmd](args)


if __name__ == "__main__":
    main()
