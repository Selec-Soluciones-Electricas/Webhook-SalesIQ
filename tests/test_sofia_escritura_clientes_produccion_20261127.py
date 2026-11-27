"""Pruebas aisladas: no salen a la red ni escriben CRM real."""
import os
import unittest
from unittest.mock import Mock, patch

from services.sofia.escritura_clientes_produccion import resolver_clientes_cotizacion_comercial

ENV = {"SOFIA_PROD_COMMERCIAL_ENABLED": "true",
       "SOFIA_PROD_COMMERCIAL_CLIENTS_WRITES_ENABLED": "true"}

BORRADOR = {"estado": "borrador_preparado", "call_id": "call_cliente_prueba",
            "cuenta": {"empresa": "Empresa Prueba", "rut": "76.111.111-6"},
            "contacto": {"nombre": "Ana Ejemplo", "correo": "ana@example.com", "telefono": "+56912345678"},
            "negocio": {"etapa": "Pendiente por cotizar", "direccion_entrega": "Santiago"},
            "productos": [{"descripcion": "Computador", "marca": "HP", "cantidad": "2"}]}


def resp(status, data=None):
    r = Mock(status_code=status)
    r.json.return_value = data
    return r


class EscrituraClientesSegura(unittest.TestCase):
    def setUp(self):
        self.get = Mock()
        self.post = Mock()
        self.conexion = {"base": "https://www.zohoapis.com", "obtener_token": lambda: "token_test",
                         "http_get": self.get}

    def resolver(self, borrador=BORRADOR, **kwargs):
        return resolver_clientes_cotizacion_comercial(
            borrador, conexion=self.conexion, http_post=self.post, **kwargs)

    def test_por_defecto_no_hace_peticion(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self.resolver(autorizar=True)["estado"], "desactivado")
            self.get.assert_not_called()
            self.post.assert_not_called()

    def test_rechaza_si_modo_de_prueba_sigue_activo(self):
        with patch.dict(os.environ, {**ENV, "SOFIA_PROD_AUTO_TEST_ONLY": "true"}, clear=True):
            self.assertEqual(self.resolver(autorizar=True)["estado"], "desactivado")
            self.get.assert_not_called()

    def test_exige_autorizacion_por_llamada(self):
        with patch.dict(os.environ, ENV, clear=True):
            self.assertEqual(self.resolver()["estado"], "desactivado")
            self.get.assert_not_called()

    def test_rechaza_rut_ficticio_antes_de_consultar(self):
        fake = dict(BORRADOR, cuenta={"empresa": "Prueba", "rut": "76.111.111-1"})
        with patch.dict(os.environ, ENV, clear=True):
            self.assertEqual(self.resolver(fake, autorizar=True)["motivo"], "rut_real_invalido")
            self.get.assert_not_called()

    def test_ambos_existentes_reutiliza_y_no_escribe(self):
        with patch.dict(os.environ, ENV, clear=True), patch(
            "services.sofia.escritura_clientes_produccion.buscar_cuenta_por_rut",
            return_value={"estado": "encontrado", "account_id": "100"},
        ), patch("services.sofia.escritura_clientes_produccion.buscar_contacto_por_correo",
                 return_value={"estado": "encontrado", "contact_id": "200", "account_id": "100"}):
            self.get.side_effect = [
                resp(200, {"data": [{"id": "100", "Billing_Code": "76111111-6"}]}),
                resp(200, {"data": [{"id": "200", "Email": "ana@example.com", "Account_Name": {"id": "100"}}]}),
            ]
            r = self.resolver(autorizar=True)
            self.assertEqual(r, {"estado": "resueltos", "account_id": "100", "contact_id": "200"})
            self.post.assert_not_called()

    def test_conflicto_de_cuenta_detiene(self):
        with patch.dict(os.environ, ENV, clear=True), patch(
            "services.sofia.escritura_clientes_produccion.buscar_cuenta_por_rut",
            return_value={"estado": "encontrado", "account_id": "100"},
        ), patch("services.sofia.escritura_clientes_produccion.buscar_contacto_por_correo",
                 return_value={"estado": "encontrado", "contact_id": "200", "account_id": "300"}):
            self.assertEqual(self.resolver(autorizar=True)["motivo"], "contacto_no_pertenece_a_cuenta")
            self.post.assert_not_called()

    def test_crear_cuenta_y_contacto_tras_ausencia_verificada(self):
        with patch.dict(os.environ, ENV, clear=True), patch(
            "services.sofia.escritura_clientes_produccion.buscar_cuenta_por_rut",
            return_value={"estado": "no_encontrado", "account_id": None},
        ), patch("services.sofia.escritura_clientes_produccion.buscar_contacto_por_correo",
                 return_value={"estado": "no_encontrado", "contact_id": None}):
            self.get.side_effect = [
                resp(204),
                resp(200, {"data": [{"id": "100", "Billing_Code": "76111111-6"}]}),
                resp(204),
                resp(200, {"data": [{"id": "200", "Email": "ana@example.com", "Account_Name": {"id": "100"}}]}),
            ]
            self.post.side_effect = [
                resp(201, {"data": [{"code": "SUCCESS", "status": "success", "details": {"id": "100"}}]}),
                resp(201, {"data": [{"code": "SUCCESS", "status": "success", "details": {"id": "200"}}]}),
            ]
            r = self.resolver(autorizar=True)
            self.assertEqual(r, {"estado": "resueltos", "account_id": "100", "contact_id": "200"})
            self.assertEqual(self.post.call_count, 2)
            self.assertIn("Account_Name", self.post.call_args.kwargs["json"]["data"][0])

    def test_busqueda_ambigua_no_escribe(self):
        with patch.dict(os.environ, ENV, clear=True), patch(
            "services.sofia.escritura_clientes_produccion.buscar_cuenta_por_rut",
            return_value={"estado": "bloqueado", "motivo": "rut_duplicado"},
        ), patch("services.sofia.escritura_clientes_produccion.buscar_contacto_por_correo",
                 return_value={"estado": "no_encontrado", "contact_id": None}):
            self.assertEqual(self.resolver(autorizar=True)["motivo"], "cuenta_no_verificable")
            self.post.assert_not_called()

    def test_un_solo_post_si_zoho_no_confirma(self):
        with patch.dict(os.environ, ENV, clear=True), patch(
            "services.sofia.escritura_clientes_produccion.buscar_cuenta_por_rut",
            return_value={"estado": "no_encontrado", "account_id": None},
        ), patch("services.sofia.escritura_clientes_produccion.buscar_contacto_por_correo",
                 return_value={"estado": "no_encontrado", "contact_id": None}):
            self.get.return_value = resp(204)
            self.post.return_value = resp(503, {})
            self.assertEqual(self.resolver(autorizar=True)["estado"], "resultado_incierto")
            self.assertEqual(self.post.call_count, 1)


if __name__ == "__main__":
    unittest.main()
