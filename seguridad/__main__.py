"""
Herramientas del Modulo de Seguridad y Verificacion
===================================================
  python -m seguridad crear                      crea la billetera cifrada
  python -m seguridad agregar --app ID --nombre "..." --origen URL
  python -m seguridad listar                     aplicativos (sin mostrar secretos)
  python -m seguridad eliminar --app ID
  python -m seguridad enrolar-rostro             registra tu rostro (opcional)
  python -m seguridad verificar auditoria/<sesion>   integridad del log
  python -m seguridad csv       auditoria/<sesion>   exporta el log a CSV
"""

import argparse
import getpass

from .auditoria import exportar_csv, verificar_integridad
from .billetera import RUTA_DEFECTO, Billetera, BilleteraError, pedir_clave_maestra


def main():
    ap = argparse.ArgumentParser(prog="python -m seguridad",
                                 description="Modulo de Seguridad y Verificacion del agente")
    ap.add_argument("--billetera", default=str(RUTA_DEFECTO), help="ruta del archivo .wallet")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("crear", help="Crea una billetera vacia")
    a = sub.add_parser("agregar", help="Agrega o reemplaza un aplicativo")
    a.add_argument("--app", required=True, help="identificador, ej. banco_sandbox")
    a.add_argument("--nombre", required=True)
    a.add_argument("--origen", required=True, help="ej. http://localhost:5173")
    sub.add_parser("listar", help="Lista aplicativos (sin mostrar secretos)")
    e = sub.add_parser("eliminar", help="Elimina un aplicativo")
    e.add_argument("--app", required=True)
    sub.add_parser("enrolar-rostro", help="Registra tu rostro para la verificacion facial")
    v = sub.add_parser("verificar", help="Comprueba la cadena de hashes de una sesion")
    v.add_argument("ruta")
    c = sub.add_parser("csv", help="Exporta el log de una sesion a CSV")
    c.add_argument("ruta")
    c.add_argument("--destino")
    args = ap.parse_args()

    # --- Auditoria ---
    if args.cmd == "verificar":
        ok, n, detalle = verificar_integridad(args.ruta)
        print(f"{'INTEGRO' if ok else 'ALTERADO'}: {n} eventos revisados ({detalle})")
        return
    if args.cmd == "csv":
        print(f"CSV generado: {exportar_csv(args.ruta, args.destino)}")
        return

    # --- Billetera ---
    b = Billetera(args.billetera)
    try:
        if args.cmd == "crear":
            b.crear(pedir_clave_maestra(confirmar=True))
            print(f"Billetera creada en {b.ruta.resolve()}")
            return

        print(f"Billetera: {b.ruta.resolve()}")
        b.desbloquear(pedir_clave_maestra())

        if args.cmd == "agregar":
            secretos = {"usuario": input("Usuario: ").strip(),
                        "clave": getpass.getpass("Clave: ")}
            while True:
                nombre = input("NOMBRE de otro secreto (ej. clave_dinamica) o Enter para terminar: ").strip()
                if not nombre:
                    break
                secretos[nombre] = getpass.getpass(f"Valor de '{nombre}': ")
            b.agregar_aplicativo(args.app, args.nombre, args.origen, secretos)
            print(f"Aplicativo '{args.app}' guardado con: {', '.join(secretos)}")

        elif args.cmd == "listar":
            for app in b.listar():
                print(f"- {app['app_id']:<16} {app['nombre']:<20} {app['origen']:<28} "
                      f"secretos: {', '.join(app['secretos'])}")
            print(f"Rostro enrolado: {'si' if b.obtener_biometria() else 'no'}")

        elif args.cmd == "eliminar":
            b.eliminar_aplicativo(args.app)
            print(f"Aplicativo '{args.app}' eliminado.")

        elif args.cmd == "enrolar-rostro":
            from .biometria import VerificadorFacial
            muestras = VerificadorFacial().enrolar()
            b.guardar_biometria(muestras)
            print(f"Rostro enrolado con {len(muestras)} muestras (cifradas en la billetera).")

    except KeyboardInterrupt:
        print("\n[seguridad] Cancelado. No se guardaron cambios.")
    except BilleteraError as e:
        print(f"[seguridad] Error: {e}")
    except Exception as e:  # p. ej. BiometriaError: camara o modelos
        print(f"[seguridad] Error: {e}")
    finally:
        b.bloquear()


if __name__ == "__main__":
    main()
