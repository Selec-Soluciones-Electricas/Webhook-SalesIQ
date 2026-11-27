"""Pruebas sin red: correos compartidos y clave única de Contactos Sofía."""
import os
import unittest
from unittest.mock import Mock, patch

from services.sofia.busqueda_clientes_produccion import buscar_contacto_por_correo
from services.sofia.escritura_clientes_produccion import (
    clave_contacto_sofia, resolver_clientes_cotizacion_comercial,
    _listar_busqueda_segura,
)
from services.sofia.metadatos_comerciales import diagnosticar_campos_comerciales, CAMPOS, CLAVES_UNICAS

ENV = {
    "SOFIA_PROD_COMMERCIAL_ENABLED": "true",
    "SOFIA_PROD_COMMERCIAL_CLIENTS_WRITES_ENABLED": "true",
}
BORRADOR = {
    "estado": "borrador_preparado", "call_id": "call_abc123",
    "cuenta": {"empresa": "Empresa Prueba", "rut": "76.111.111-6"},
    "contacto": {"nombre": "Ana Ejemplo", "correo": "ana@example.com", "telefono": "+56912345678"},
    "negocio": {"etapa": "Pendiente por cotizar", "direccion_entrega": "Santiago"},
    "productos": [{"descripcion": "Computador", "marca": "HP", "cantidad": "2"}],
}


def respuesta(codigo, payload=None):
    r = Mock(status_code=codigo)
    r.json.return_value = payload
    return r


class ClaveYContactosCompartidos(unittest.TestCase):
    def test_clave_por_empresa_y_correo_normalizado(self):
        self.assertEqual(clave_contacto_sofia("100", "ANA@example.com"),
                         clave_contacto_sofia("100", " ana@EXAMPLE.com "))
        self.assertNotEqual(clave_contacto_sofia("100", "ana@example.com"),
                            clave_contacto_sofia("200", "ana@example.com"))
        self.assertNotIn("ana@", clave_contacto_sofia("100", "ana@example.com"))
        self.assertLess(len(clave_contacto_sofia("100", "ana@example.com")), 255)

    def test_correo_compartido_en_otra_empresa_no_bloquea(self):
        c = {"base": "https://www.zohoapis.com", "obtener_token": lambda: "prueba",
             "http_get": Mock(return_value=respuesta(200, {"data": [
                 {"id": "501", "Email": "ana@example.com", "Account_Name": {"id": "200"}},
             ], "info": {"more_records": False}}))}
        r = buscar_contacto_por_correo("ana@example.com", account_id="100", conexion=c)
        self.assertEqual(r["estado"], "no_encontrado")

    def test_correo_compartido_reutiliza_el_de_su_empresa(self):
        c = {"base": "https://www.zohoapis.com", "obtener_token": lambda: "prueba",
             "http_get": Mock(return_value=respuesta(200, {"data": [
                 {"id": "501", "Email": "ana@example.com", "Account_Name": {"id": "200"}},
                 {"id": "502", "Email": "ana@example.com", "Account_Name": {"id": "100"}},
             ], "info": {"more_records": False}}))}
        r = buscar_contacto_por_correo("ana@example.com", account_id="100", conexion=c)
        self.assertEqual(r["estado"], "encontrado")
        self.assertEqual(r["contact_id"], "502")

    def test_correo_duplicado_dentro_de_misma_empresa_bloquea(self):
        c = {"base": "https://www.zohoapis.com", "obtener_token": lambda: "prueba",
             "http_get": Mock(return_value=respuesta(200, {"data": [
                 {"id": "501", "Email": "ana@example.com", "Account_Name": {"id": "100"}},
                 {"id": "502", "Email": "ana@example.com", "Account_Name": {"id": "100"}},
             ], "info": {"more_records": False}}))}
        r = buscar_contacto_por_correo("ana@example.com", account_id="100", conexion=c)
        self.assertEqual(r["motivo"], "correo_duplicado_en_cuenta")

    def test_listado_exhaustivo_ignora_contacto_de_otra_cuenta(self):
        c = {"base": "https://www.zohoapis.com", "http_get": Mock(return_value=respuesta(200, {"data": [
            {"id": "501", "Email": "ana@example.com", "Account_Name": {"id": "200"}},
        ], "info": {"more_records": False}}))}
        r = _listar_busqueda_segura(c, "prueba", "Contacts", "Email", "ana@example.com", account_id="100")
        self.assertEqual(r["estado"], "no_encontrado")

    def test_creacion_de_contacto_usa_clave_unica_sin_alterar_otros(self):
        get = Mock(side_effect=[
            respuesta(200, {"data": [{"id": "100", "Billing_Code": "76111111-6"}]}),
            respuesta(200, {"data": [
                {"id": "501", "Email": "ana@example.com", "Account_Name": {"id": "200"}},
            ], "info": {"more_records": False}}),
            respuesta(200, {"data": [{
                "id": "502", "Email": "ana@example.com", "Account_Name": {"id": "100"},
                "Clave_Sof_a_Contacto": clave_contacto_sofia("100", "ana@example.com"),
            }]}),
        ])
        post = Mock(return_value=respuesta(201, {"data": [
            {"code": "SUCCESS", "status": "success", "details": {"id": "502"}}
        ]}))
        c = {"base": "https://www.zohoapis.com", "obtener_token": lambda: "prueba", "http_get": get}
        with patch.dict(os.environ, ENV, clear=True), patch(
            "services.sofia.escritura_clientes_produccion.buscar_cuenta_por_rut",
            return_value={"estado": "encontrado", "account_id": "100"},
        ), patch(
            "services.sofia.escritura_clientes_produccion.buscar_contacto_por_correo",
            return_value={"estado": "no_encontrado", "contact_id": None},
        ):
            r = resolver_clientes_cotizacion_comercial(BORRADOR, autorizar=True, conexion=c, http_post=post)
        self.assertEqual(r["estado"], "resueltos")
        self.assertEqual(r["contact_id"], "502")
        post.assert_called_once()
        envio = post.call_args.kwargs["json"]["data"][0]
        self.assertEqual(envio["Account_Name"]["id"], "100")
        self.assertEqual(envio["Clave_Sof_a_Contacto"], clave_contacto_sofia("100", "ana@example.com"))

    def test_metadatos_exigen_clave_unica_no_email_global(self):
        self.assertEqual(CLAVES_UNICAS["Contacts"], "Clave_Sof_a_Contacto")
        self.assertIn("Clave_Sof_a_Contacto", CAMPOS["Contacts"])
        def campos(modulo):
            return [{"api_name": nombre, "operation_type": {"api_create": True},
                     "system_mandatory": False,
                     "unique": {"case_sensitive": False} if nombre == CLAVES_UNICAS[modulo] else {}}
                    for nombre in CAMPOS[modulo]]
        c = {"base": "https://www.zohoapis.com", "obtener_token": lambda: "prueba", "http_get": Mock()}
        c["http_get"].side_effect = [respuesta(200, {"fields": campos(m)}) for m in CAMPOS]
        r = diagnosticar_campos_comerciales(conexion=c)
        self.assertEqual(r["estado"], "listo")
        self.assertEqual(r["modulos"]["Contacts"]["sin_unicidad"], [])


if __name__ == "__main__":
    unittest.main()
