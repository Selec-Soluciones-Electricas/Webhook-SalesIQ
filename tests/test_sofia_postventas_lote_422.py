"""Pruebas del procesamiento por lotes de Sofia. Sin APIs."""

import unittest

from services.sofia.seleccion_postventas_auto import (
    seleccionar_postventas_lote_seguro,
)

FECHA_MINIMA = 1795521600000


def postventa(call_id, fecha=FECHA_MINIMA):
    return {
        "call_id": call_id,
        "tipo": "postventa",
        "estado": "candidata_caso",
        "faltantes": [],
        "start_timestamp": fecha,
    }


class TestLotesPostventas422(unittest.TestCase):

    def seleccionar(self, datos, limite=3):
        return seleccionar_postventas_lote_seguro(
            datos,
            inicio_minimo_ms=FECHA_MINIMA,
            max_por_ejecucion=limite,
        )

    def test_lista_vacia(self):
        resultado = self.seleccionar([])
        self.assertEqual(resultado["seleccionadas"], [])
        self.assertEqual(resultado["total_recientes"], 0)
        self.assertEqual(resultado["pendientes_por_continuar"], 0)

    def test_una_postventa(self):
        resultado = self.seleccionar([
            postventa("call_unica_422")
        ])
        self.assertEqual(len(resultado["seleccionadas"]), 1)
        self.assertEqual(resultado["pendientes_por_continuar"], 0)

    def test_tres_postventas(self):
        datos = [
            postventa(f"call_prueba_{i}_422", FECHA_MINIMA + i)
            for i in range(3)
        ]
        resultado = self.seleccionar(datos)
        self.assertEqual(len(resultado["seleccionadas"]), 3)
        self.assertEqual(resultado["pendientes_por_continuar"], 0)

    def test_siete_postventas_limite_tres(self):
        datos = [
            postventa(f"call_prueba_{i}_422", FECHA_MINIMA + i)
            for i in range(7)
        ]
        resultado = self.seleccionar(datos)
        self.assertEqual(len(resultado["seleccionadas"]), 3)
        self.assertEqual(resultado["total_recientes"], 7)
        self.assertEqual(resultado["pendientes_por_continuar"], 4)

    def test_orden_cronologico(self):
        datos = [
            postventa("call_tercera_422", FECHA_MINIMA + 3000),
            postventa("call_primera_422", FECHA_MINIMA + 1000),
            postventa("call_segunda_422", FECHA_MINIMA + 2000),
        ]
        resultado = self.seleccionar(datos)
        self.assertEqual(
            [p["call_id"] for p in resultado["seleccionadas"]],
            [
                "call_primera_422",
                "call_segunda_422",
                "call_tercera_422",
            ],
        )

    def test_orden_igual_fecha_por_call_id(self):
        datos = [
            postventa("call_z_422"),
            postventa("call_a_422"),
        ]
        resultado = self.seleccionar(datos)
        self.assertEqual(
            [p["call_id"] for p in resultado["seleccionadas"]],
            ["call_a_422", "call_z_422"],
        )

    def test_excluir_llamadas_antiguas(self):
        datos = [
            postventa("call_antigua_422", FECHA_MINIMA - 1000),
            postventa("call_nueva_422", FECHA_MINIMA + 1000),
        ]
        resultado = self.seleccionar(datos)
        self.assertEqual(
            [p["call_id"] for p in resultado["seleccionadas"]],
            ["call_nueva_422"],
        )

    def test_fecha_ausente_bloqueada(self):
        datos = [postventa("call_sin_fecha_422", None)]
        with self.assertRaises(ValueError):
            self.seleccionar(datos)

    def test_fecha_booleana_bloqueada(self):
        datos = [postventa("call_fecha_bool_422", True)]
        with self.assertRaises(ValueError):
            self.seleccionar(datos)

    def test_call_id_duplicado_bloqueado(self):
        datos = [
            postventa("call_repetida_422"),
            postventa("call_repetida_422"),
        ]
        with self.assertRaises(ValueError):
            self.seleccionar(datos)

    def test_consulta_general_bloqueada(self):
        datos = [postventa("call_general_422")]
        datos[0]["tipo"] = "consulta_general"
        with self.assertRaises(ValueError):
            self.seleccionar(datos)

    def test_limite_fuera_de_rango(self):
        datos = [postventa("call_prueba_limite_422")]
        for limite in (0, 6, True, 2.5):
            with self.subTest(limite=limite):
                with self.assertRaises(ValueError):
                    self.seleccionar(datos, limite=limite)

    def test_limite_personalizado(self):
        datos = [
            postventa(f"call_personalizada_{i}_422")
            for i in range(4)
        ]
        resultado = self.seleccionar(datos, limite=2)
        self.assertEqual(len(resultado["seleccionadas"]), 2)
        self.assertEqual(resultado["pendientes_por_continuar"], 2)

    def test_fecha_minima_invalida(self):
        with self.assertRaises(ValueError):
            seleccionar_postventas_lote_seguro(
                [postventa("call_fecha_minima_422")],
                inicio_minimo_ms=0,
            )


if __name__ == "__main__":
    unittest.main()
