"""
Modulo de Seguridad y Verificacion
==================================
Componente transversal del agente con tres responsabilidades:

  1) Verificacion  -> seguridad/verificacion.py
  2) Auditoria     -> seguridad/auditoria.py
  3) Credenciales  -> seguridad/billetera.py (+ seguridad/biometria.py opcional)

El resto del agente solo interactua con la clase ModuloSeguridadVerificacion.
"""

import time

from .auditoria import MASCARA, Auditor, exportar_csv, verificar_integridad
from .billetera import (RUTA_DEFECTO, Billetera, BilleteraError, normalizar_origen,
                        pedir_clave_maestra)
from .verificacion import Verificador

__all__ = ["ModuloSeguridadVerificacion", "MASCARA", "verificar_integridad", "exportar_csv"]

# Datos de la billetera que identifican al usuario pero no son secretos:
# se registran en claro (la auditoria debe poder decir QUIEN ingreso) y no
# exigen verificacion facial. Todo lo demas se trata como secreto.
IDENTIFICADORES = ("usuario",)


class ModuloSeguridadVerificacion:

    def __init__(self, ruta_billetera=RUTA_DEFECTO, carpeta_auditoria="auditoria",
                 autenticacion_facial=False, minutos_desbloqueo=5, max_intentos=3,
                 minutos_bloqueo=2, guardar_capturas=True):
        self.auditor = Auditor(carpeta_auditoria, guardar_capturas=guardar_capturas)
        self.verificador = Verificador()
        self.billetera = Billetera(ruta_billetera)

        self.autenticacion_facial = autenticacion_facial
        self.segundos_desbloqueo = minutos_desbloqueo * 60
        self.max_intentos = max_intentos
        self.segundos_bloqueo = minutos_bloqueo * 60
        self._bloqueado_hasta = 0.0
        self._ultimo_uso = 0.0
        self._facial = None

    # ------------------------------------------------------------------
    # Autenticacion del usuario humano
    # ------------------------------------------------------------------

    def _expirar_si_inactiva(self):
        if (self.billetera.desbloqueada
                and time.time() - self._ultimo_uso > self.segundos_desbloqueo):
            self.billetera.bloquear()
            self.auditor.registrar("SEGURIDAD", "billetera_bloqueada",
                                   motivo="inactividad",
                                   minutos=self.segundos_desbloqueo // 60)

    def _desbloquear_billetera(self) -> bool:
        self._expirar_si_inactiva()
        if self.billetera.desbloqueada:
            return True
        restante = self._bloqueado_hasta - time.time()
        if restante > 0:
            self.auditor.registrar("SEGURIDAD", "acceso_bloqueado", nivel="WARN",
                                   motivo="bloqueo temporal por intentos fallidos",
                                   segundos_restantes=int(restante))
            print(f"[seguridad] Acceso bloqueado. Intenta en {int(restante)} s.")
            return False
        if not self.billetera.existe:
            ruta = str(self.billetera.ruta.resolve())
            self.auditor.registrar("SEGURIDAD", "billetera_inexistente", nivel="ERROR", ruta=ruta)
            print(f"[seguridad] No hay billetera en {ruta}\n"
                  "            Creala con: python -m seguridad crear")
            return False

        print("\n[seguridad] Se requiere autenticacion para usar credenciales.")
        for intento in range(1, self.max_intentos + 1):
            try:
                self.billetera.desbloquear(pedir_clave_maestra())
            except BilleteraError as e:
                self.auditor.registrar("SEGURIDAD", "autenticacion", nivel="WARN",
                                       metodo="clave_maestra", resultado="RECHAZADA",
                                       intento=intento, max_intentos=self.max_intentos,
                                       motivo=str(e))
                continue
            # A partir de aqui, ningun secreto de la billetera puede quedar en el log.
            for secreto in self.billetera.todos_los_secretos(excluir=IDENTIFICADORES):
                self.auditor.proteger(secreto)
            self._ultimo_uso = time.time()
            self.auditor.registrar("SEGURIDAD", "autenticacion", metodo="clave_maestra",
                                   resultado="ACEPTADA", intento=intento)
            return True

        self._bloqueado_hasta = time.time() + self.segundos_bloqueo
        self.auditor.registrar("SEGURIDAD", "acceso_bloqueado", nivel="ERROR",
                               motivo="intentos de clave maestra agotados",
                               minutos_bloqueo=self.segundos_bloqueo // 60)
        return False

    def _verificar_presencia(self) -> bool:
        """Segundo factor opcional: verificacion facial antes de entregar un secreto."""
        if not self.autenticacion_facial:
            return True
        referencia = self.billetera.obtener_biometria()
        if not referencia:
            self.auditor.registrar("SEGURIDAD", "verificacion_facial", nivel="ERROR",
                                   resultado="NO_ENROLADO",
                                   ayuda="python -m seguridad enrolar-rostro")
            return False
        try:
            if self._facial is None:
                from .biometria import VerificadorFacial
                self._facial = VerificadorFacial()
            aceptado, similitud = self._facial.verificar(referencia)
        except Exception as e:
            self.auditor.registrar("SEGURIDAD", "verificacion_facial", nivel="ERROR",
                                   resultado="ERROR", motivo=str(e))
            return False
        self.auditor.registrar("SEGURIDAD", "verificacion_facial",
                               nivel="INFO" if aceptado else "WARN",
                               resultado="ACEPTADA" if aceptado else "RECHAZADA",
                               similitud=similitud, umbral=self._facial.umbral)
        return aceptado

    # ------------------------------------------------------------------
    # Entrega de credenciales
    # ------------------------------------------------------------------

    def obtener_credencial(self, url: str, secreto: str):
        """Devuelve el secreto del aplicativo que corresponde a la URL, o None.

        El valor se entrega directamente al modulo de accion: nunca se dicta
        por voz, no se envia al modelo de lenguaje y no se escribe en el log.
        """
        origen = normalizar_origen(url)
        self.auditor.registrar("SEGURIDAD", "solicitud_credencial",
                               origen=origen, secreto=secreto)

        if not self._desbloquear_billetera():
            return None

        app_id, entrada = self.billetera.aplicativo_por_url(url)
        if app_id is None:
            self.auditor.registrar("SEGURIDAD", "credencial_denegada", nivel="WARN",
                                   motivo="el origen no esta registrado en la billetera",
                                   origen=origen)
            return None
        if secreto not in entrada["secretos"]:
            self.auditor.registrar("SEGURIDAD", "credencial_denegada", nivel="WARN",
                                   motivo=f"el aplicativo no tiene el secreto '{secreto}'",
                                   app=app_id)
            return None
        es_identificador = secreto in IDENTIFICADORES
        if not es_identificador and not self._verificar_presencia():
            return None

        valor = str(entrada["secretos"][secreto])
        if not es_identificador:
            self.auditor.proteger(valor)
        self._ultimo_uso = time.time()
        factores = "clave_maestra"
        if self.autenticacion_facial and not es_identificador:
            factores += "+facial"
        self.auditor.registrar("SEGURIDAD", "credencial_entregada", app=app_id,
                               secreto=secreto,
                               valor=valor if es_identificador else MASCARA,
                               factores=factores)
        return valor

    def cerrar(self) -> dict:
        if self.billetera.desbloqueada:
            self.billetera.bloquear()
            self.auditor.registrar("SEGURIDAD", "billetera_bloqueada", motivo="fin de sesion")
        return self.auditor.cerrar()
