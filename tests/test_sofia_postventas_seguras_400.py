"""Pruebas de fecha y limite de postventas. Sin APIs."""

import unittest

from services.sofia.seleccion_postventas_auto import (
    seleccionar_postventas_prueba_segura,
)

FECHA_MINIMA = 1795468500000


def postventa(call_id, fecha):
    return {
        "call_id": call_id,
        "tipo": "postventa",
        "estado": "candidata_caso",
        "faltantes": [],
        "start_timestamp": fecha,
    }


class TestPostventasSeguras400(unittest.TestCase):

    def seleccionar(self, datos, fecha=FECHA_MINIMA):
        return seleccionar_postventas_prueba_segura(
            datos,
            inicio_minimo_ms=fecha,
        )

    def test_una_postventa_nueva(self):
        datos = [postventa(
            "call_nueva_400", FECHA_MINIMA + 1000
        )]
        resultado = self.seleccionar(datos)
        self.assertEqual(len(resultado), 1)

    def test_postventa_antigua_excluida(self):
        datos = [postventa(
            "call_antigua_400", FECHA_MINIMA - 1000
        )]
        self.assertEqual(self.seleccionar(datos), [])

    def test_fecha_exacta_permitida(self):
        datos = [postventa(
            "call_exacta_400", FECHA_MINIMA
        )]
        self.assertEqual(len(self.seleccionar(datos)), 1)

    def test_una_nueva_y_una_antigua(self):
        datos = [
            postventa("call_antigua_400", FECHA_MINIMA - 1000),
            postventa("call_nueva_400", FECHA_MINIMA + 1000),
        ]
        resultado = self.seleccionar(datos)
        self.assertEqual(
            [x["call_id"] for x in resultado],
            ["call_nueva_400"],
        )

    def test_dos_nuevas_bloqueadas(self):
        datos = [
            postventa("call_nueva_a_400", FECHA_MINIMA + 1000),
            postventa("call_nueva_b_400", FECHA_MINIMA + 2000),
        ]
        with self.assertRaises(ValueError):
            self.seleccionar(datos)

    def test_fecha_ausente_bloqueada(self):
        datos = [postventa("call_sin_fecha_400", None)]
        with self.assertRaises(ValueError):
            self.seleccionar(datos)

    def test_fecha_booleana_bloqueada(self):
        datos = [postventa("call_bool_400", True)]
        with self.assertRaises(ValueError):
            self.seleccionar(datos)

    def test_fecha_minima_invalida(self):
        datos = [postventa("call_prueba_400", FECHA_MINIMA)]
        with self.assertRaises(ValueError):
            self.seleccionar(datos, fecha=0)

    def test_consulta_general_rechazada(self):
        datos = [postventa("call_general_400", FECHA_MINIMA)]
        datos[0]["tipo"] = "consulta_general"
        with self.assertRaises(ValueError):
            self.seleccionar(datos)

    def test_identificador_duplicado(self):
        datos = [
            postventa("call_repetida_400", FECHA_MINIMA),
            postventa("call_repetida_400", FECHA_MINIMA),
        ]
        with self.assertRaises(ValueError):
            self.seleccionar(datos)


if __name__ == "__main__":
    unittest.main()
