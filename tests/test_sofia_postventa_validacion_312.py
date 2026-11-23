import unittest
from services.retell_postventas import clasificar_postventa_sofia

AGENTE = "agente_ficticio"

BASE = {
    "nombre_cliente": "Cliente de prueba",
    "rut_cliente": "11111111-1",
    "descripcion_problema": "Producto defectuoso",
}

def crear_llamada(datos, resumen="Cliente reporta problema"):
    return {
        "agent_id": AGENTE,
        "call_type": "phone_call",
        "call_status": "ended",
        "call_id": "call_prueba_segura_312",
        "call_analysis": {
            "call_summary": resumen,
            "custom_analysis_data": {
                "tipo_solicitud": "postventa",
                **datos,
            },
        },
    }

class ValidacionPostventa(unittest.TestCase):

    def clasificar(self, datos, resumen="Cliente reporta problema"):
        return clasificar_postventa_sofia(
            crear_llamada(datos, resumen),
            AGENTE,
        )

    def test_sin_datos(self):
        resultado = self.clasificar({})
        self.assertEqual(resultado["estado"], "revision")
        self.assertEqual(len(resultado["faltantes"]), 5)

    def test_solo_nombre(self):
        resultado = self.clasificar({
            "nombre_cliente": "Cliente ficticio",
        })
        self.assertEqual(resultado["estado"], "revision")
        self.assertIn("rut_cliente", resultado["faltantes"])

    def test_telefono_y_factura(self):
        resultado = self.clasificar({
            **BASE,
            "telefono_cliente": "912345678",
            "numero_factura": "FAC-PRUEBA",
        })
        self.assertEqual(resultado["estado"], "candidata_caso")

    def test_email_y_oc(self):
        resultado = self.clasificar({
            **BASE,
            "email_cliente": "prueba@example.com",
            "numero_oc": "OC-PRUEBA",
        })
        self.assertEqual(resultado["estado"], "candidata_caso")

    def test_sin_descripcion(self):
        datos = {
            **BASE,
            "telefono_cliente": "912345678",
            "numero_factura": "FAC-PRUEBA",
            "descripcion_problema": "",
        }
        resultado = self.clasificar(datos)
        self.assertEqual(resultado["estado"], "revision")
        self.assertIn(
            "descripcion_problema",
            resultado["faltantes"],
        )

    def test_sin_rut(self):
        datos = {
            **BASE,
            "telefono_cliente": "912345678",
            "numero_factura": "FAC-PRUEBA",
        }
        del datos["rut_cliente"]
        resultado = self.clasificar(datos)
        self.assertEqual(resultado["estado"], "revision")
        self.assertIn("rut_cliente", resultado["faltantes"])

    def test_descripcion_sin_resumen(self):
        resultado = self.clasificar({
            **BASE,
            "telefono_cliente": "912345678",
            "numero_factura": "FAC-PRUEBA",
        }, resumen="")
        self.assertEqual(resultado["estado"], "candidata_caso")


if __name__ == "__main__":
    unittest.main()
