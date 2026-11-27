"""Pruebas offline del correo de Negocios Sofía: nunca conectan a Zoho/Retell."""
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from services.sofia.notificaciones_negocios_comerciales import notificar_negocio_comercial_creado
from services.sofia.cron_comercial_produccion import procesar_cron_comercial

CALL_ID = "call_prueba_correo_comercial_123"
DEAL_ID = "12345"
ENV_MAIL = {
    "SOFIA_PROD_COMMERCIAL_DEALS_MAILS_ENABLED": "true",
    "SOFIA_PROD_COMMERCIAL_DEALS_MAIL_TEST_TO": "ederth@selec.cl",
    "SOFIA_PROD_COMMERCIAL_DEALS_MAIL_FROM": "operaciones@selec.cl",
    "SOFIA_RETELL_CALL_URL_TEMPLATE": "https://beta.retellai.com/dashboard/call-history/{call_id}",
}


def resp(status, data=None):
    r = Mock(status_code=status)
    r.json.return_value = data or {}
    return r


def conexion():
    get = Mock(return_value=resp(200, {"data": [{
        "id": DEAL_ID,
        "Retell_Call_ID": CALL_ID,
        "Account_Name": {"id": "100"},
        "Contact_Name": {"id": "200"},
        "Deal_Name": "Cotización automática",
        "Description": "Producto: motor, cantidad 2",
    }]}))
    return {"base": "https://www.zohoapis.com", "http_get": get, "obtener_token": lambda: "token_test"}, get


class AvisoNegocio(unittest.TestCase):
    def setUp(self):
        self.decision = {"estado": "creado", "deal_id": DEAL_ID, "account_id": "100", "contact_id": "200"}
        self.llamada = {"call_id": CALL_ID}
        self.conn, self.get = conexion()
        self.post = Mock(return_value=resp(200, {"data": [{"code": "SUCCESS", "status": "success"}]}))

    def enviar(self):
        return notificar_negocio_comercial_creado(self.decision, self.llamada, conexion=self.conn, http_post=self.post)

    def test_apagado_no_consulta_ni_envia(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self.enviar()["estado"], "desactivado")
        self.get.assert_not_called()
        self.post.assert_not_called()

    def test_correo_solo_tras_creacion_confirmada(self):
        self.decision["estado"] = "ya_registrado"
        with patch.dict(os.environ, ENV_MAIL, clear=True):
            self.assertEqual(self.enviar()["motivo"], "negocio_no_recien_creado")
        self.get.assert_not_called()
        self.post.assert_not_called()

    def test_envio_de_prueba_contiene_enlaces_y_datos(self):
        with patch.dict(os.environ, ENV_MAIL, clear=True):
            self.assertEqual(self.enviar()["estado"], "enviado")
        self.get.assert_called_once()
        self.post.assert_called_once()
        payload = self.post.call_args.kwargs["json"]["data"][0]
        self.assertEqual([e["email"] for e in payload["to"]], ["ederth@selec.cl"])
        self.assertIn("Nuevo Negocio", payload["subject"])
        self.assertIn("Abrir Negocio", payload["content"])
        self.assertIn("Abrir llamada", payload["content"])
        self.assertIn("cantidad 2", payload["content"])

    def test_sin_aprobacion_destinatarios_reales_bloquea(self):
        env = {**ENV_MAIL, "SOFIA_PROD_COMMERCIAL_DEALS_MAIL_REAL_RECIPIENTS_ENABLED": "true",
               "SOFIA_PROD_COMMERCIAL_DEALS_MAIL_TO": "gerencia@selec.cl"}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(self.enviar()["motivo"], "destinatarios_no_autorizados")
        self.get.assert_not_called()
        self.post.assert_not_called()

    def test_vinculo_no_coincidente_bloquea_sin_post(self):
        self.decision["contact_id"] = "999"
        with patch.dict(os.environ, ENV_MAIL, clear=True):
            self.assertEqual(self.enviar()["motivo"], "vinculos_no_verificables")
        self.post.assert_not_called()

    def test_error_remoto_no_reintenta(self):
        self.post.return_value = resp(500)
        with patch.dict(os.environ, ENV_MAIL, clear=True):
            self.assertEqual(self.enviar()["estado"], "bloqueado")
        self.assertEqual(self.post.call_count, 1)

    def test_contenido_html_escapado(self):
        self.get.return_value = resp(200, {"data": [{"id": DEAL_ID, "Retell_Call_ID": CALL_ID,
            "Account_Name": {"id": "100"}, "Contact_Name": {"id": "200"},
            "Deal_Name": "<script>alert(1)</script>", "Description": "<b>secreto</b>"}]})
        with patch.dict(os.environ, ENV_MAIL, clear=True):
            self.assertEqual(self.enviar()["estado"], "enviado")
        html = self.post.call_args.kwargs["json"]["data"][0]["content"]
        self.assertNotIn("<script>", html)
        self.assertNotIn("<b>secreto</b>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_cron_no_reenvia_por_negocio_existente(self):
        ahora = int(datetime.now(timezone.utc).timestamp() * 1000)
        env = {
            "SOFIA_PROD_COMMERCIAL_CRON_ENABLED": "true",
            "SOFIA_PROD_COMMERCIAL_ENABLED": "true",
            "SOFIA_PROD_COMMERCIAL_CLIENTS_WRITES_ENABLED": "true",
            "SOFIA_PROD_COMMERCIAL_DEALS_WRITES_ENABLED": "true",
            "SOFIA_PROD_COMMERCIAL_START_MS": str(ahora - 120000),
            "SOFIA_PROD_COMMERCIAL_MAX_PER_RUN": "1",
        }
        writer = Mock(side_effect=[{"estado": "ya_registrado", "deal_id": "2"}, self.decision])
        aviso = Mock(return_value={"estado": "enviado"})
        entradas = {"estado": "simulacion", "cotizaciones_sandbox_candidatas": [
            {"call_id": "call_vieja", "start_timestamp": ahora - 60000},
            {"call_id": "call_nueva", "start_timestamp": ahora - 59000},
        ]}
        with patch.dict(os.environ, env, clear=True):
            res = procesar_cron_comercial(entradas, diagnosticar=lambda: {"estado": "listo"}, escribir=writer, notificar=aviso)
        self.assertEqual(writer.call_count, 2)
        aviso.assert_called_once()
        self.assertEqual(res["recuento"]["ya_registrados"], 1)
        self.assertEqual(res["recuento"]["creados"], 1)
        self.assertEqual(res["correos"]["enviados"], 1)


if __name__ == "__main__":
    unittest.main()
