"""Pruebas aisladas, sin requests HTTP ni escrituras de CRM."""

import os
import time
import unittest
from unittest.mock import patch

from services.sofia.autorizacion_produccion import (
    configuracion_automatica, llamada_autorizada,
)
from services.sofia.cron_automatico_produccion import procesar_produccion_automatica

NOW = int(time.time() * 1000)
START = NOW - 60000
CALL_CASE = "call_postventa_automatica_01"
CALL_DEAL = "call_cotizacion_automatica_01"

ENV = {
    "SOFIA_PROD_CRON_AUTO_ENABLED": "true",
    "SOFIA_PROD_CRON_PILOT_ENABLED": "false",
    "SOFIA_PROD_AUTO_TEST_ONLY": "true",
    "SOFIA_PROD_AUTO_START_MS": str(START),
    "SOFIA_PROD_AUTO_MAX_PER_RUN": "2",
    "SOFIA_PROD_CASES_WRITES_ENABLED": "true",
    "SOFIA_PROD_DEALS_WRITES_ENABLED": "true",
    "SOFIA_PROD_CASES_MAILS_ENABLED": "true",
    "SOFIA_PROD_CASES_MAIL_REAL_RECIPIENTS_ENABLED": "false",
}


def caso(call_id=CALL_CASE, fecha=NOW):
    return {"call_id": call_id, "tipo": "postventa", "tipo_solicitud": "postventa",
            "estado": "candidata_caso", "start_timestamp": fecha,
            "contacto": {"telefono_cliente": "+56911111111"}}


def deal(call_id=CALL_DEAL, fecha=NOW):
    return {"call_id": call_id, "start_timestamp": fecha, "agent_id": "agent_prueba"}


def resultado(cases=None, deals=None):
    return {"estado": "simulacion", "consultas_detectadas": [],
            "postventas_detectadas": cases if cases is not None else [],
            "cotizaciones_sandbox_candidatas": deals if deals is not None else []}


class TestAutoProduccion(unittest.TestCase):
    def test_apagado_por_defecto(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(configuracion_automatica()["estado"], "desactivado")
            self.assertEqual(procesar_produccion_automatica(resultado())["estado"], "desactivado")

    def test_bloquea_piloto_simultaneo(self):
        with patch.dict(os.environ, {**ENV, "SOFIA_PROD_CRON_PILOT_ENABLED": "true"}, clear=True):
            self.assertEqual(configuracion_automatica()["motivo"], "piloto_y_automatico_incompatibles")

    def test_bloquea_destinatarios_reales(self):
        with patch.dict(os.environ, {**ENV, "SOFIA_PROD_CASES_MAIL_REAL_RECIPIENTS_ENABLED": "true"}, clear=True):
            self.assertEqual(configuracion_automatica()["motivo"], "destinatarios_reales_no_autorizados")

    def test_exige_cutoff_y_pruebas(self):
        with patch.dict(os.environ, {**ENV, "SOFIA_PROD_AUTO_START_MS": ""}, clear=True):
            self.assertEqual(configuracion_automatica()["motivo"], "fecha_inicio_invalida")
        with patch.dict(os.environ, {**ENV, "SOFIA_PROD_AUTO_TEST_ONLY": "false"}, clear=True):
            self.assertEqual(configuracion_automatica()["motivo"], "solo_pruebas_no_autorizado")

    def test_autorizacion_nuevas_sin_id_manual(self):
        with patch.dict(os.environ, ENV, clear=True):
            self.assertTrue(llamada_autorizada("Cases", CALL_CASE, NOW))
            self.assertTrue(llamada_autorizada("Deals", CALL_DEAL, NOW))
            self.assertFalse(llamada_autorizada("Cases", CALL_CASE, START-1))
            self.assertFalse(llamada_autorizada("Cases", CALL_CASE, None))
            self.assertFalse(llamada_autorizada("Deals", "call_espacio malo", NOW))

    def test_solo_nuevos_y_tope_por_ciclo(self):
        casos = [caso("call_vieja", START - 1000), caso("call_primera", NOW), caso("call_segunda", NOW + 1)]
        negocios = [deal("call_tercera", NOW + 2)]
        with patch.dict(os.environ, ENV, clear=True):
            with patch("services.sofia.registro_casos_produccion.procesar_caso_prueba_desde_clasificacion", return_value={"estado":"ya_registrado"}) as crear_case, patch("services.sofia.registro_cotizaciones_produccion.registrar_negocio_prueba_produccion", return_value={"estado":"creado"}) as crear_deal, patch("services.sofia.notificaciones_casos.notificar_caso_creado") as mail:
                salida=procesar_produccion_automatica(resultado(casos, negocios))
                self.assertEqual(salida["estado"], "automatico_pruebas_ejecutado")
                self.assertEqual(salida["pendientes_por_continuar"],0)
                self.assertEqual(crear_case.call_count,2)
                crear_deal.assert_called_once()
                mail.assert_not_called()
                self.assertEqual(salida["recuento"]["creados"], 1)
                self.assertEqual(salida["recuento"]["ya_registrados"], 2)
                self.assertEqual(salida["resultados"]["Deals"], "creado")

    def test_limite_dos_casos_nuevos(self):
        casos = [
            caso("call_nueva_a", NOW),
            caso("call_nueva_b", NOW + 1),
            caso("call_nueva_c", NOW + 2),
        ]
        with patch.dict(os.environ, ENV, clear=True):
            with patch(
                "services.sofia.registro_casos_produccion.procesar_caso_prueba_desde_clasificacion",
                return_value={"estado": "creado", "case_id": "1234"},
            ) as crear_case, patch(
                "services.sofia.notificaciones_casos.notificar_caso_creado",
                return_value={"estado": "enviado"},
            ) as mail:
                salida = procesar_produccion_automatica(resultado(casos))
                self.assertEqual(crear_case.call_count, 2)
                self.assertEqual(mail.call_count, 2)
                self.assertEqual(salida["recuento"]["creados"], 2)
                self.assertEqual(salida["pendientes_por_continuar"], 1)

    def test_caso_nuevo_notifica_una_sola_vez(self):
        with patch.dict(os.environ, ENV, clear=True):
            with patch("services.sofia.registro_casos_produccion.procesar_caso_prueba_desde_clasificacion", side_effect=[{"estado":"creado","case_id":"1234"},{"estado":"ya_registrado", "case_id":"1234"}]) as crear_case, patch("services.sofia.notificaciones_casos.notificar_caso_creado", return_value={"estado":"enviado"}) as mail:
                salida1=procesar_produccion_automatica(resultado([caso()]))
                salida2=procesar_produccion_automatica(resultado([caso()]))
                self.assertEqual(crear_case.call_count, 2)
                self.assertEqual(mail.call_count, 1)
                self.assertEqual(salida1["resultados"]["Cases_email"], "enviado")
                self.assertEqual(salida2["resultados"]["Cases"], "ya_registrado")

    def test_duplicado_bloquea_antes_de_crear(self):
        with patch.dict(os.environ, ENV, clear=True):
            with patch("services.sofia.registro_casos_produccion.procesar_caso_prueba_desde_clasificacion") as writer:
                salida = procesar_produccion_automatica(resultado([caso(), caso()]))
                self.assertEqual(salida["motivo"],"duplicado_en_resultados")
                writer.assert_not_called()

    def test_historial_fuera_de_fecha_no_crea(self):
        with patch.dict(os.environ, ENV, clear=True):
            with patch("services.sofia.registro_cotizaciones_produccion.registrar_negocio_prueba_produccion") as writer:
                salida=procesar_produccion_automatica(resultado([], [deal(fecha=START - 1)]))
                self.assertEqual(salida["resultados"]["Deals"], "sin_nuevas")
                writer.assert_not_called()

    def test_resultado_incierto_detiene_lote(self):
        with patch.dict(os.environ, ENV, clear=True):
            with patch("services.sofia.registro_casos_produccion.procesar_caso_prueba_desde_clasificacion", return_value={"estado":"resultado_incierto"}) as writer:
                salida=procesar_produccion_automatica(resultado([caso("call_a"),caso("call_b")]))
                self.assertEqual(writer.call_count,1)
                self.assertEqual(salida["recuento"]["resultado_incierto"],1)


if __name__ == "__main__":
    unittest.main()
