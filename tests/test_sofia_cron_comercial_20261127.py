"""Pruebas offline: nunca se llama a Retell ni Zoho real."""
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from services.sofia.cron_comercial_produccion import procesar_cron_comercial
from services.sofia.metadatos_comerciales import diagnosticar_campos_comerciales, CAMPOS, CLAVES_UNICAS

NOW = int(datetime.now(timezone.utc).timestamp() * 1000)
ENV = {
    "SOFIA_PROD_COMMERCIAL_CRON_ENABLED": "true",
    "SOFIA_PROD_COMMERCIAL_ENABLED": "true",
    "SOFIA_PROD_COMMERCIAL_CLIENTS_WRITES_ENABLED": "true",
    "SOFIA_PROD_COMMERCIAL_DEALS_WRITES_ENABLED": "true",
    "SOFIA_PROD_COMMERCIAL_START_MS": str(NOW - 300_000),
    "RETELL_SOFIA_AGENT_ID": "agent_test",
    "SOFIA_PROD_COMMERCIAL_MAX_PER_RUN": "1",
}


def llamada(ident, fecha=NOW - 60000):
    return {"call_id": ident, "start_timestamp": fecha}


def entradas(items):
    return {"estado": "simulacion", "cotizaciones_sandbox_candidatas": items}


def listo():
    return {"estado": "listo"}


class CronComercial(unittest.TestCase):
    def test_apagado_por_defecto(self):
        verificar, escritor = Mock(), Mock()
        with patch.dict(os.environ, {}, clear=True):
            r = procesar_cron_comercial(entradas([llamada("call_1")]), diagnosticar=verificar, escribir=escritor)
        self.assertEqual(r["estado"], "desactivado")
        verificar.assert_not_called()
        escritor.assert_not_called()

    def test_modo_prueba_incompatible_bloquea(self):
        escritor = Mock()
        with patch.dict(os.environ, {**ENV, "SOFIA_PROD_AUTO_TEST_ONLY": "true"}, clear=True):
            r = procesar_cron_comercial(entradas([llamada("call_1")]), escribir=escritor)
        self.assertEqual(r["motivo"], "modo_prueba_incompatible")
        escritor.assert_not_called()

    def test_escritura_casos_prueba_incompatible(self):
        escritor = Mock()
        with patch.dict(os.environ, {**ENV, "SOFIA_PROD_CASES_WRITES_ENABLED": "true"}, clear=True):
            r = procesar_cron_comercial(entradas([llamada("call_1")]), escribir=escritor)
        self.assertEqual(r["motivo"], "modo_prueba_incompatible")
        escritor.assert_not_called()

    def test_escritura_sandbox_incompatible(self):
        escritor = Mock()
        with patch.dict(os.environ, {**ENV, "SOFIA_SANDBOX_DEALS_WRITES_ENABLED": "true"}, clear=True):
            r = procesar_cron_comercial(entradas([llamada("call_1")]), escribir=escritor)
        self.assertEqual(r["motivo"], "modo_prueba_incompatible")
        escritor.assert_not_called()

    def test_fecha_vieja_no_escribe(self):
        escritor = Mock()
        with patch.dict(os.environ, ENV, clear=True):
            r = procesar_cron_comercial(entradas([llamada("call_vieja", NOW - 900000)]), escribir=escritor)
        self.assertEqual(r["estado"], "comercial_sin_nuevas")
        escritor.assert_not_called()

    def test_metadatos_no_listos_impiden_escritura(self):
        escritor = Mock()
        with patch.dict(os.environ, ENV, clear=True):
            r = procesar_cron_comercial(entradas([llamada("call_nueva")]),
                                       diagnosticar=lambda: {"estado": "bloqueado"}, escribir=escritor)
        self.assertEqual(r["motivo"], "metadatos_no_listos")
        escritor.assert_not_called()

    def test_creacion_real_unica(self):
        escritor = Mock(return_value={"estado": "creado", "deal_id": "987"})
        with patch.dict(os.environ, ENV, clear=True):
            r = procesar_cron_comercial(entradas([llamada("call_a")]),
                                       diagnosticar=listo, escribir=escritor)
        self.assertEqual(r["recuento"]["creados"], 1)
        escritor.assert_called_once()
        self.assertTrue(escritor.call_args.kwargs["autorizar"])

    def test_ya_registrado_no_consume_limite(self):
        escritor = Mock(side_effect=[{"estado": "ya_registrado"}, {"estado": "creado"}])
        with patch.dict(os.environ, ENV, clear=True):
            r = procesar_cron_comercial(entradas([llamada("call_a"), llamada("call_b", NOW - 59000)]),
                                       diagnosticar=listo, escribir=escritor)
        self.assertEqual(r["recuento"]["creados"], 1)
        self.assertEqual(r["recuento"]["ya_registrados"], 1)
        self.assertEqual(r["pendientes_por_continuar"], 0)
        self.assertEqual(escritor.call_count, 2)

    def test_limite_un_registro_por_cron(self):
        escritor = Mock(return_value={"estado": "creado"})
        with patch.dict(os.environ, ENV, clear=True):
            r = procesar_cron_comercial(entradas([llamada("call_a"), llamada("call_b", NOW - 59000)]),
                                       diagnosticar=listo, escribir=escritor)
        self.assertEqual(r["pendientes_por_continuar"], 1)
        escritor.assert_called_once()

    def test_error_incierto_detiene_sin_reintentar(self):
        escritor = Mock(side_effect=[{"estado": "resultado_incierto"}, {"estado": "creado"}])
        with patch.dict(os.environ, ENV, clear=True):
            r = procesar_cron_comercial(entradas([llamada("call_a"), llamada("call_b", NOW - 59000)]),
                                       diagnosticar=listo, escribir=escritor)
        self.assertEqual(r["recuento"]["resultado_incierto"], 1)
        escritor.assert_called_once()

    def test_duplicado_en_lote_impide_todo(self):
        escritor = Mock()
        with patch.dict(os.environ, ENV, clear=True):
            r = procesar_cron_comercial(entradas([llamada("call_igual"), llamada("call_igual")]),
                                       diagnosticar=listo, escribir=escritor)
        self.assertEqual(r["motivo"], "duplicado_en_lote")
        escritor.assert_not_called()

    def test_id_invalido_impide_escritura(self):
        escritor = Mock()
        with patch.dict(os.environ, ENV, clear=True):
            r = procesar_cron_comercial(entradas([llamada("invalido")]),
                                       diagnosticar=listo, escribir=escritor)
        self.assertEqual(r["motivo"], "identificador_invalido")
        escritor.assert_not_called()


def respuesta_json(campos, status=200):
    r = Mock(status_code=status)
    r.json.return_value = {"fields": campos}
    return r


def lista_campos(modulo, *, solo_unicos=True, faltante=None):
    filas = []
    for nombre in CAMPOS[modulo]:
        if nombre == faltante:
            continue
        filas.append({"api_name": nombre, "operation_type": {"api_create": True},
                      "system_mandatory": nombre in {"Account_Name", "Last_Name", "Deal_Name"},
                      "unique": {"case_sensitive": False} if solo_unicos and nombre == CLAVES_UNICAS[modulo] else {}})
    return filas


class DiagnosticoMetadatos(unittest.TestCase):
    def setUp(self):
        self.get = Mock()
        self.conexion = {"base": "https://www.zohoapis.com",
                         "http_get": self.get, "obtener_token": lambda: "token_de_prueba"}

    def test_todo_correcto_sin_post(self):
        self.get.side_effect = [respuesta_json(lista_campos(m)) for m in CAMPOS]
        r = diagnosticar_campos_comerciales(conexion=self.conexion)
        self.assertEqual(r["estado"], "listo")
        self.assertEqual(self.get.call_count, 3)
        self.assertEqual({c.args[0].split("/")[-1] for c in self.get.call_args_list}, {"fields"})
        self.assertNotIn("token_de_prueba", str(r))

    def test_falta_unicidad_bloquea(self):
        self.get.side_effect = [respuesta_json(lista_campos(m, solo_unicos=m != "Accounts")) for m in CAMPOS]
        r = diagnosticar_campos_comerciales(conexion=self.conexion)
        self.assertEqual(r["estado"], "bloqueado")
        self.assertEqual(r["modulos"]["Accounts"]["sin_unicidad"], ["Billing_Code"])

    def test_falta_campo_bloquea(self):
        self.get.side_effect = [respuesta_json(lista_campos(m, faltante="Account_Name" if m == "Contacts" else None)) for m in CAMPOS]
        r = diagnosticar_campos_comerciales(conexion=self.conexion)
        self.assertEqual(r["estado"], "bloqueado")
        self.assertIn("Account_Name", r["modulos"]["Contacts"]["faltantes"])

    def test_obligatorio_extra_bloquea(self):
        respuestas = []
        for m in CAMPOS:
            campos = lista_campos(m)
            if m == "Accounts":
                campos.append({"api_name": "Extra_Obligatorio", "system_mandatory": True,
                               "operation_type": {"api_create": True}, "unique": {}})
            respuestas.append(respuesta_json(campos))
        self.get.side_effect = respuestas
        r = diagnosticar_campos_comerciales(conexion=self.conexion)
        self.assertEqual(r["estado"], "bloqueado")
        self.assertEqual(r["modulos"]["Accounts"]["obligatorios_extra"], ["Extra_Obligatorio"])

    def test_sin_scope_bloquea_sin_filtrar_datos(self):
        self.get.side_effect = [respuesta_json([], status=403) for _ in CAMPOS]
        r = diagnosticar_campos_comerciales(conexion=self.conexion)
        self.assertEqual(r["estado"], "bloqueado")
        self.assertTrue(r["modulos"]["Deals"]["sin_permisos_o_metadatos"])


if __name__ == "__main__":
    unittest.main()
