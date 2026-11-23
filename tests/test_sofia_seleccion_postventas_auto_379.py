"""Pruebas de seleccion automatica de postventas, sin APIs."""

import unittest

from services.sofia.seleccion_postventas_auto import (
    seleccionar_postventas_automaticas,
)


def postventa_valida(call_id="call_prueba_379"):
    return {
        "tipo": "postventa",
        "estado": "candidata_caso",
        "call_id": call_id,
        "faltantes": [],
    }


class TestSeleccionPostventasAuto(unittest.TestCase):

    def test_postventa_valida(self):
        original = postventa_valida()
        resultado = seleccionar_postventas_automaticas([original])
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado[0]["call_id"], original["call_id"])
        self.assertIsNot(resultado[0], original)

    def test_lista_vacia(self):
        self.assertEqual(
            seleccionar_postventas_automaticas([]),
            [],
        )

    def test_consulta_general_rechazada(self):
        datos = postventa_valida()
        datos["tipo"] = "consulta_general"
        with self.assertRaises(ValueError):
            seleccionar_postventas_automaticas([datos])

    def test_estado_incorrecto(self):
        datos = postventa_valida()
        datos["estado"] = "revision"
        with self.assertRaises(ValueError):
            seleccionar_postventas_automaticas([datos])

    def test_datos_faltantes(self):
        datos = postventa_valida()
        datos["faltantes"] = ["rut_cliente"]
        with self.assertRaises(ValueError):
            seleccionar_postventas_automaticas([datos])

    def test_call_id_invalido(self):
        datos = postventa_valida("identificador_invalido")
        with self.assertRaises(ValueError):
            seleccionar_postventas_automaticas([datos])

    def test_duplicados(self):
        datos = [
            postventa_valida("call_duplicada"),
            postventa_valida("call_duplicada"),
        ]
        with self.assertRaises(ValueError):
            seleccionar_postventas_automaticas(datos)

    def test_entrada_invalida(self):
        with self.assertRaises(ValueError):
            seleccionar_postventas_automaticas(None)


if __name__ == "__main__":
    unittest.main()
