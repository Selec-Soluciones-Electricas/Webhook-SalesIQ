"""Contrato de las búsquedas directas del escritor comercial: sin red ni escrituras."""
import unittest
from unittest.mock import Mock

from services.sofia.registro_negocios_comerciales import _buscar_negocio_unico
from services.sofia.escritura_clientes_produccion import _listar_busqueda_segura

CALL_ID = "call_abc123"
URL_BASE = "https://www.zohoapis.com/crm/v8"


def respuesta(status, body=None):
    r = Mock(status_code=status)
    r.json.return_value = body
    return r


class BusquedasDirectasSeguras(unittest.TestCase):
    def test_deal_ausente_204_solo_consulta_search(self):
        get = Mock(return_value=respuesta(204))
        r = _buscar_negocio_unico({"http_get": get}, "token_simulado", CALL_ID)
        self.assertEqual(r["estado"], "no_encontrado")
        get.assert_called_once()
        self.assertEqual(get.call_args.args[0], URL_BASE + "/Deals/search")
        self.assertEqual(get.call_args.kwargs["params"]["criteria"],
                         "(Retell_Call_ID:equals:" + CALL_ID + ")")

    def test_deal_existente_se_reutiliza(self):
        get = Mock(return_value=respuesta(200, {"data": [
            {"id": "501", "Retell_Call_ID": CALL_ID},
        ], "info": {"more_records": False}}))
        r = _buscar_negocio_unico({"http_get": get}, "token_simulado", CALL_ID)
        self.assertEqual(r, {"estado": "ya_registrado", "deal_id": "501"})
        get.assert_called_once()

    def test_deal_respuesta_inexacta_no_se_toma_por_ausencia(self):
        get = Mock(return_value=respuesta(200, {"data": [
            {"id": "501", "Retell_Call_ID": "call_otro"},
        ], "info": {"more_records": False}}))
        r = _buscar_negocio_unico({"http_get": get}, "token_simulado", CALL_ID)
        self.assertEqual(r["estado"], "bloqueado")
        self.assertEqual(r["motivo"], "busqueda_sin_coincidencia_exacta")

    def test_deal_pagina_incompleta_bloquea(self):
        get = Mock(return_value=respuesta(200, {"data": [
            {"id": "501", "Retell_Call_ID": CALL_ID},
        ], "info": {"more_records": True}}))
        r = _buscar_negocio_unico({"http_get": get}, "token_simulado", CALL_ID)
        self.assertEqual(r["estado"], "bloqueado")

    def test_deal_duplicado_bloquea(self):
        get = Mock(return_value=respuesta(200, {"data": [
            {"id": "501", "Retell_Call_ID": CALL_ID},
            {"id": "502", "Retell_Call_ID": CALL_ID},
        ], "info": {"more_records": False}}))
        r = _buscar_negocio_unico({"http_get": get}, "token_simulado", CALL_ID)
        self.assertEqual(r["estado"], "bloqueado")
        self.assertEqual(r["motivo"], "deals_duplicados")

    def test_cuenta_busqueda_inconclusa_no_autoriza_crear(self):
        from unittest.mock import patch
        with patch("services.sofia.escritura_clientes_produccion.buscar_cuenta_por_rut",
                   return_value={"estado": "bloqueado", "motivo": "consulta_inconclusa"}) as buscar:
            r = _listar_busqueda_segura(
                {"base": "https://www.zohoapis.com"}, "token_simulado",
                "Accounts", "Billing_Code", "76111111-6",
            )
        self.assertEqual(r["estado"], "bloqueado")
        buscar.assert_called_once()


if __name__ == "__main__":
    unittest.main()
