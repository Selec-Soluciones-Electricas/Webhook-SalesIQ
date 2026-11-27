"""Pruebas aisladas: no llaman a Zoho ni a Retell."""

import os
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from services.sofia.registro_negocios_comerciales import registrar_negocio_comercial

AHORA = int(datetime.now(timezone.utc).timestamp() * 1000)
ENV = {
    "SOFIA_PROD_COMMERCIAL_ENABLED": "true",
    "SOFIA_PROD_COMMERCIAL_CLIENTS_WRITES_ENABLED": "true",
    "SOFIA_PROD_COMMERCIAL_DEALS_WRITES_ENABLED": "true",
    "SOFIA_PROD_COMMERCIAL_START_MS": str(AHORA - 120_000),
    "RETELL_SOFIA_AGENT_ID": "agent_sofia_prueba",
}


def llamada(rut="76.111.111-6"):
    return {
        "call_id": "call_comercial_prueba_a",
        "start_timestamp": AHORA - 60_000,
        "agent_id": "agent_sofia_prueba",
        "call_type": "phone_call",
        "call_status": "ended",
        "call_analysis": {"custom_analysis_data": {
            "tipo_solicitud": "cotizacion", "empresa": "Empresa de Prueba",
            "rut_cliente": rut, "nombre_cliente": "Ana Ejemplo",
            "email_cliente": "ana@example.com", "telefono_cliente": "+56912345678",
            "direccion_entrega": "Santiago",
            "productos_solicitados": "Producto 1 | Descripcion: Computador | Marca: HP | Cantidad: 2",
        }},
    }


def r(status, datos=None):
    respuesta = Mock(status_code=status)
    respuesta.json.return_value = datos
    return respuesta


class EscritorComercial(unittest.TestCase):
    def setUp(self):
        self.get = Mock()
        self.post = Mock()
        self.conexion = {
            "base": "https://www.zohoapis.com",
            "obtener_token": lambda: "token_prueba",
            "http_get": self.get,
        }

    def crear(self, data=None, **kwargs):
        return registrar_negocio_comercial(
            data or llamada(), conexion=self.conexion,
            http_post=self.post, **kwargs,
        )

    def test_apagado_por_defecto(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self.crear(autorizar=True)["estado"], "desactivado")
        self.get.assert_not_called()
        self.post.assert_not_called()

    def test_exige_autorizacion_explicita(self):
        with patch.dict(os.environ, ENV, clear=True):
            self.assertEqual(self.crear()["estado"], "desactivado")
        self.get.assert_not_called()

    def test_bloquea_modos_simultaneos(self):
        with patch.dict(os.environ, {**ENV, "SOFIA_PROD_CRON_AUTO_ENABLED": "true"}, clear=True):
            self.assertEqual(self.crear(autorizar=True)["motivo"], "modo_prueba_incompatible")
        self.get.assert_not_called()

    def test_fecha_y_agente_obligatorios(self):
        with patch.dict(os.environ, ENV, clear=True):
            data = llamada()
            data["agent_id"] = "agent_otro"
            self.assertEqual(self.crear(data, autorizar=True)["motivo"], "llamada_no_autorizada")
            data = llamada()
            data["start_timestamp"] = AHORA - 1_000_000
            self.assertEqual(self.crear(data, autorizar=True)["motivo"], "llamada_no_autorizada")
        self.get.assert_not_called()

    def test_rut_invalido_no_llega_a_zoho(self):
        with patch.dict(os.environ, ENV, clear=True):
            self.assertEqual(self.crear(llamada("76.111.111-1"), autorizar=True)["motivo"], "datos_por_revisar")
        self.get.assert_not_called()
        self.post.assert_not_called()

    def test_ya_registrado_nunca_crea_clientes(self):
        with patch.dict(os.environ, ENV, clear=True), patch(
            "services.sofia.registro_negocios_comerciales.resolver_clientes_cotizacion_comercial"
        ) as clientes:
            self.get.return_value = r(200, {"data": [{"id": "123", "Retell_Call_ID": "call_comercial_prueba_a"}],
                                            "info": {"more_records": False}})
            resultado = self.crear(autorizar=True)
            self.assertEqual(resultado["estado"], "ya_registrado")
            self.assertEqual(resultado["deal_id"], "123")
            clientes.assert_not_called()
        self.post.assert_not_called()

    def test_vincula_cuenta_contacto_y_crea_deal(self):
        with patch.dict(os.environ, ENV, clear=True), patch(
            "services.sofia.registro_negocios_comerciales.resolver_clientes_cotizacion_comercial",
            return_value={"estado": "resueltos", "account_id": "100", "contact_id": "200"}
        ) as clientes:
            self.get.side_effect = [r(204), r(204)]
            self.post.return_value = r(201, {"data": [{"code": "SUCCESS", "status": "success", "details": {"id": "300"}}]})
            resultado = self.crear(autorizar=True)
            self.assertEqual(resultado["estado"], "creado")
            self.assertEqual(resultado["deal_id"], "300")
            self.assertEqual(self.get.call_count, 2)
            self.assertEqual(self.post.call_count, 1)
            payload = self.post.call_args.kwargs["json"]["data"][0]
            self.assertEqual(payload["Account_Name"], {"id": "100"})
            self.assertEqual(payload["Contact_Name"], {"id": "200"})
            clientes.assert_called_once()

    def test_segunda_revision_detecta_duplicado(self):
        with patch.dict(os.environ, ENV, clear=True), patch(
            "services.sofia.registro_negocios_comerciales.resolver_clientes_cotizacion_comercial",
            return_value={"estado": "resueltos", "account_id": "100", "contact_id": "200"}
        ):
            self.get.side_effect = [r(204), r(200, {"data": [{"id": "301", "Retell_Call_ID": "call_comercial_prueba_a"}], "info": {"more_records": False}})]
            resultado = self.crear(autorizar=True)
            self.assertEqual(resultado["estado"], "ya_registrado")
        self.post.assert_not_called()

    def test_cliente_no_verificado_no_crea_deal(self):
        with patch.dict(os.environ, ENV, clear=True), patch(
            "services.sofia.registro_negocios_comerciales.resolver_clientes_cotizacion_comercial",
            return_value={"estado": "bloqueado", "motivo": "contacto_incorrecto"}
        ):
            self.get.return_value = r(204)
            resultado = self.crear(autorizar=True)
            self.assertEqual(resultado["estado"], "bloqueado")
        self.post.assert_not_called()

    def test_respuesta_incierta_sin_reintento(self):
        with patch.dict(os.environ, ENV, clear=True), patch(
            "services.sofia.registro_negocios_comerciales.resolver_clientes_cotizacion_comercial",
            return_value={"estado": "resueltos", "account_id": "100", "contact_id": "200"}
        ):
            self.get.return_value = r(204)
            self.post.return_value = r(503, {})
            resultado = self.crear(autorizar=True)
            self.assertEqual(resultado["estado"], "resultado_incierto")
        self.post.assert_called_once()


if __name__ == "__main__":
    unittest.main()
