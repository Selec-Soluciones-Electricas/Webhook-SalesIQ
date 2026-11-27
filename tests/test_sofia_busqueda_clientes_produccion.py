import unittest
from unittest.mock import Mock
from services.sofia.busqueda_clientes_produccion import (
    normalizar_rut, buscar_cuenta_por_rut, buscar_contacto_por_correo,
)


def respuesta(status, datos=None):
    r = Mock(status_code=status)
    r.json.return_value = datos
    return r


class BusquedaClientesSoloLectura(unittest.TestCase):
    def setUp(self):
        self.conexion = {"base": "https://www.zohoapis.com", "obtener_token": lambda: "token_prueba", "http_get": Mock()}

    def test_normaliza_rut(self):
        self.assertEqual(normalizar_rut("76.111.111-6"), "76111111-6")

    def test_cuenta_encontrada_sin_duplicados(self):
        self.conexion["http_get"].side_effect = lambda *args, **kwargs: respuesta(
            200, {"data": [{"id": "12345", "Billing_Code": "76.111.111-6"}], "info": {"more_records": False}}
        )
        r = buscar_cuenta_por_rut("76111111-6", conexion=self.conexion)
        self.assertEqual(r["estado"], "encontrado")
        self.assertEqual(r["account_id"], "12345")

    def test_cuenta_duplicada_bloquea(self):
        self.conexion["http_get"].side_effect = lambda *args, **kwargs: respuesta(
            200, {"data": [
                {"id": "12345", "Billing_Code": "76.111.111-6"},
                {"id": "12346", "Billing_Code": "76111111-6"},
            ], "info": {"more_records": False}}
        )
        self.assertEqual(buscar_cuenta_por_rut("76111111-6", conexion=self.conexion)["motivo"], "rut_duplicado")

    def test_cuenta_error_http_bloquea(self):
        self.conexion["http_get"].return_value = respuesta(500)
        self.assertEqual(buscar_cuenta_por_rut("76111111-6", conexion=self.conexion)["estado"], "bloqueado")

    def test_contacto_de_otra_cuenta_no_impide_crear_en_la_correcta(self):
        self.conexion["http_get"].return_value = respuesta(200, {
            "data": [{"id": "999", "Email": "cliente@example.com", "Account_Name": {"id": "888"}}],
            "info": {"more_records": False},
        })
        r = buscar_contacto_por_correo("cliente@example.com", account_id="777", conexion=self.conexion)
        self.assertEqual(r["estado"], "no_encontrado")

    def test_contacto_misma_cuenta(self):
        self.conexion["http_get"].return_value = respuesta(200, {
            "data": [{"id": "999", "Email": "cliente@example.com", "Account_Name": {"id": "777"}}],
            "info": {"more_records": False},
        })
        r = buscar_contacto_por_correo("cliente@example.com", account_id="777", conexion=self.conexion)
        self.assertEqual(r["estado"], "encontrado")
        self.assertEqual(r["contact_id"], "999")

    def test_contacto_duplicado_bloquea(self):
        self.conexion["http_get"].return_value = respuesta(200, {
            "data": [{"id": "999", "Email": "cliente@example.com"}, {"id": "1000", "Email": "cliente@example.com"}],
            "info": {"more_records": False},
        })
        self.assertEqual(buscar_contacto_por_correo("cliente@example.com", conexion=self.conexion)["motivo"], "correo_duplicado")

    def test_nunca_escribe(self):
        self.conexion["http_get"].return_value = respuesta(204)
        self.assertEqual(buscar_cuenta_por_rut("76111111-6", conexion=self.conexion)["estado"], "no_encontrado")
        self.assertEqual(buscar_contacto_por_correo("cliente@example.com", conexion=self.conexion)["estado"], "no_encontrado")
        self.assertEqual(self.conexion["http_get"].call_count, 4)

if __name__ == "__main__":
    unittest.main()
