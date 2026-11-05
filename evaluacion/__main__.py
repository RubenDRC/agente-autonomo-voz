"""
evaluacion/__main__.py
======================
Compara modelos de IA en la planificacion: con las mismas instrucciones,
mide que tan bien cada modelo identifica la ruta y extrae los parametros.
No abre el navegador ni ejecuta acciones: la ejecucion de los pasos es
deterministica (sigue la guia), asi que la diferencia entre modelos esta en
la planificacion.

    python -m evaluacion --listar-modelos claude gemini groq ollama
    python -m evaluacion --ia local claude ollama@qwen2.5:7b ollama@llama3.1:8b
    python -m evaluacion --ia claude --repeticiones 3 --pausa 1

Metricas por modelo (y por categoria de instruccion):
  acierto_ruta_pct     ruta correcta (o ninguna, cuando no corresponde ninguna)
  exactitud_datos_pct  parametros esperados extraidos con el valor correcto
  casos_completos_pct  ruta y todos los parametros correctos
  latencia_media_ms / latencia_max_ms, tokens de entrada y salida, errores

Resultados en evaluacion/resultados/<fecha>_*:
  _resumen.csv          una fila por modelo
  _por_categoria.csv    una fila por modelo y categoria
  _detalle.csv          una fila por caso, modelo y repeticion
  _metadatos.json       configuracion exacta de la corrida (para reproducirla)
"""

import argparse
import csv
import json
import platform
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

import configuracion as cfg
from comun.texto import normalizar
from conocimiento import MemoriaProcedimientos
from ia import crear_proveedor, listar_modelos

DIR = Path(__file__).resolve().parent


def _igual(esperado, obtenido, tipo: str) -> bool:
    if obtenido in (None, ""):
        return False
    if tipo == "texto":
        e, o = normalizar(str(esperado)).strip(), normalizar(str(obtenido)).strip()
        return e in o or o in e
    if tipo == "monto":
        try:
            return int(esperado) == int(obtenido)
        except (TypeError, ValueError):
            return False
    return normalizar(str(esperado)).strip() == normalizar(str(obtenido)).strip()


def revisar_fuga(casos, memoria) -> list[str]:
    """Casos cuya instruccion es igual a (o contiene / esta contenida en) una frase de
    ejemplo de la guia. Si los hay, los resultados quedan sesgados a favor del modelo local."""
    frases = [normalizar(f).strip(" ¿?¡!.,") for p in memoria.procedimientos for f in p.get("frases", [])]
    fugas = []
    for c in casos:
        n = normalizar(c["instruccion"]).strip(" ¿?¡!.,")
        if any(n == f or n in f or f in n for f in frases):
            fugas.append(c["instruccion"])
    return fugas


def evaluar(proveedor, memoria, casos, repeticiones=1, pausa=0.0):
    filas = []
    for rep in range(1, repeticiones + 1):
        if repeticiones > 1:
            print(f"  -- repetición {rep}/{repeticiones}")
        for i, caso in enumerate(casos, start=1):
            r = proveedor.identificar(caso["instruccion"], memoria)
            predicha = r.procedimiento if (r.procedimiento and r.confianza >= cfg.UMBRAL_PROCEDIMIENTO) else None
            ruta_ok = predicha == caso["procedimiento"]
            tipos = ({p["nombre"]: p["tipo"] for p in memoria.obtener(caso["procedimiento"])["parametros"]}
                     if caso["procedimiento"] else {})
            esperados = caso.get("parametros", {})
            correctos = sum(_igual(v, r.parametros.get(k), tipos.get(k, "texto")) for k, v in esperados.items())
            filas.append({
                "modelo": proveedor.etiqueta, "repeticion": rep, "caso": i,
                "categoria": caso.get("categoria", "general"), "instruccion": caso["instruccion"],
                "ruta_esperada": caso["procedimiento"] or "—", "ruta_obtenida": predicha or "—",
                "confianza_pct": round(r.confianza * 100, 1), "ruta_ok": ruta_ok,
                "datos_esperados": len(esperados), "datos_correctos": correctos if ruta_ok else 0,
                "caso_completo": ruta_ok and correctos == len(esperados),
                "parametros_esperados": json.dumps(esperados, ensure_ascii=False),
                "parametros_obtenidos": json.dumps(r.parametros, ensure_ascii=False),
                "latencia_ms": r.latencia_ms,
                "tokens_entrada": (r.tokens or {}).get("entrada") or 0,
                "tokens_salida": (r.tokens or {}).get("salida") or 0,
                "error": r.error or "",
            })
            marca = "✔" if filas[-1]["caso_completo"] else ("~" if ruta_ok else "✘")
            print(f"  {marca} [{i:02d}] {caso['instruccion'][:58]:<58} -> {predicha or '—'}"
                  + (f"  ERROR: {r.error[:70]}" if r.error else ""))
            if pausa:
                time.sleep(pausa)
    return filas


def resumir(filas, **extra):
    n = len(filas)
    datos = sum(f["datos_esperados"] for f in filas)
    latencias = [f["latencia_ms"] for f in filas]
    return {
        "modelo": filas[0]["modelo"], **extra, "casos": n,
        "acierto_ruta_pct": round(100 * sum(f["ruta_ok"] for f in filas) / n, 1),
        "exactitud_datos_pct": round(100 * sum(f["datos_correctos"] for f in filas) / datos, 1) if datos else "",
        "casos_completos_pct": round(100 * sum(f["caso_completo"] for f in filas) / n, 1),
        "latencia_media_ms": round(statistics.mean(latencias)),
        "latencia_mediana_ms": round(statistics.median(latencias)),
        "latencia_max_ms": max(latencias),
        "tokens_entrada": sum(f["tokens_entrada"] for f in filas),
        "tokens_salida": sum(f["tokens_salida"] for f in filas),
        "errores": sum(1 for f in filas if f["error"]),
    }


def _csv(ruta, filas):
    with open(ruta, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0]), delimiter=";")
        w.writeheader()
        w.writerows(filas)


def _listar(nombres):
    for nombre in nombres:
        print(f"\n=== {nombre} ===")
        try:
            modelos = listar_modelos(nombre)
            print("\n".join(f"  {m}" for m in modelos) if modelos else "  (el proveedor no devolvió modelos)")
        except (ValueError, RuntimeError) as e:
            print(f"  No se pudo consultar: {e}")


def main():
    ap = argparse.ArgumentParser(prog="python -m evaluacion", description="Compara modelos de IA en la planificación")
    ap.add_argument("--ia", nargs="+", default=["local"],
                    help=f"modelos a comparar: {', '.join(cfg.PROVEEDORES_IA)} (o proveedor@modelo)")
    ap.add_argument("--modelo", default=None, help="identificador del modelo (si se evalúa un solo proveedor)")
    ap.add_argument("--casos", default=str(DIR / "casos.json"))
    ap.add_argument("--conocimiento", default=str(cfg.RUTA_CONOCIMIENTO))
    ap.add_argument("--repeticiones", type=int, default=1, help="repite cada caso (mide la estabilidad del modelo)")
    ap.add_argument("--pausa", type=float, default=0.0, help="segundos entre llamadas (útil con planes gratuitos)")
    ap.add_argument("--listar-modelos", nargs="+", metavar="PROVEEDOR",
                    help="muestra los modelos que ofrece hoy cada proveedor y termina")
    args = ap.parse_args()

    if args.listar_modelos:
        _listar(args.listar_modelos)
        return

    memoria = MemoriaProcedimientos(args.conocimiento)
    datos_casos = json.loads(Path(args.casos).read_text(encoding="utf-8"))
    casos = datos_casos["casos"]
    print(f"Memoria: {memoria.resumen()}  ·  {len(casos)} casos  ·  umbral de ruta {cfg.UMBRAL_PROCEDIMIENTO}")

    fugas = revisar_fuga(casos, memoria)
    if fugas:
        print(f"\n[advertencia] {len(fugas)} casos coinciden con frases de ejemplo de la guía; "
              "los resultados del modelo local quedarán inflados:")
        for f in fugas:
            print(f"   - {f}")

    detalle, resumen, por_categoria, evaluados = [], [], [], []
    for nombre in args.ia:
        try:
            proveedor = crear_proveedor(nombre, args.modelo if len(args.ia) == 1 else None)
        except ValueError as e:
            print(f"\n[{nombre}] omitido: {e}")
            continue
        print(f"\n=== {proveedor.etiqueta} ===")
        t0 = time.perf_counter()
        filas = evaluar(proveedor, memoria, casos, args.repeticiones, args.pausa)
        detalle += filas
        resumen.append(resumir(filas))
        for categoria in dict.fromkeys(f["categoria"] for f in filas):
            por_categoria.append(resumir([f for f in filas if f["categoria"] == categoria], categoria=categoria))
        evaluados.append({"nombre": nombre, "proveedor": proveedor.nombre, "modelo": proveedor.modelo,
                          "tipo": proveedor.tipo, "duracion_s": round(time.perf_counter() - t0, 1)})

    if not resumen:
        sys.exit("No se evaluó ningún modelo.")

    print(f"\n{'Modelo':<36}{'Ruta %':>8}{'Datos %':>9}{'Completo %':>12}{'Lat. mediana':>14}{'Errores':>9}")
    for r in resumen:
        print(f"{r['modelo'][:35]:<36}{r['acierto_ruta_pct']:>8}{r['exactitud_datos_pct']:>9}"
              f"{r['casos_completos_pct']:>12}{str(r['latencia_mediana_ms']) + ' ms':>14}{r['errores']:>9}")
    categorias = list(dict.fromkeys(c["categoria"] for c in por_categoria))
    print(f"\nCasos completos (%) por categoría:\n{'Modelo':<36}" + "".join(f"{c[:11]:>12}" for c in categorias))
    for r in resumen:
        fila = {c["categoria"]: c["casos_completos_pct"] for c in por_categoria if c["modelo"] == r["modelo"]}
        print(f"{r['modelo'][:35]:<36}" + "".join(f"{fila.get(c, ''):>12}" for c in categorias))

    carpeta = DIR / "resultados"
    carpeta.mkdir(exist_ok=True)
    sello = datetime.now().strftime("%Y%m%d_%H%M%S")
    _csv(carpeta / f"{sello}_resumen.csv", resumen)
    _csv(carpeta / f"{sello}_por_categoria.csv", por_categoria)
    _csv(carpeta / f"{sello}_detalle.csv", detalle)
    metadatos = {
        "fecha": datetime.now().astimezone().isoformat(timespec="seconds"),
        "modelos": evaluados, "repeticiones": args.repeticiones, "pausa_s": args.pausa,
        "casos": {"archivo": Path(args.casos).name, "total": len(casos),
                  "por_categoria": {c: sum(1 for x in casos if x.get("categoria") == c) for c in categorias},
                  "coincidencias_con_la_guia": fugas},
        "conocimiento": {"archivo": Path(args.conocimiento).name, "fuente": memoria.fuente,
                         "procedimientos": len(memoria.procedimientos), "contactos": len(memoria.contactos)},
        "configuracion": {"umbral_procedimiento": cfg.UMBRAL_PROCEDIMIENTO,
                          "modelo_embeddings": cfg.MODELO_EMBEDDINGS},
        "entorno": {"python": platform.python_version(), "sistema": platform.platform()},
    }
    (carpeta / f"{sello}_metadatos.json").write_text(json.dumps(metadatos, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nResultados en {carpeta}:  {sello}_resumen.csv · _por_categoria.csv · _detalle.csv · _metadatos.json")


if __name__ == "__main__":
    main()
