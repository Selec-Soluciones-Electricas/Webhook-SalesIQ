"""Pruebas aisladas del modo automatico de postventas de Sofia."""

import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


def modulo(nombre, **atributos):
    m = types.ModuleType(nombre)
    for clave, valor in atributos.items():
        setattr(m, clave, valor)
    return m


class Logger:
    def info(self, *args): pass
    def warning(self, *args): pass
    def exception(self, *args): pass


class Aplicacion:
    def __init__(self):
        self.rutas = {}

    def post(self, ruta):
        def registrar(funcion):
            self.rutas[ruta] = funcion
            return funcion
        return registrar


def postventa(call_id):
    return {
        "call_id": call_id,
        "tipo": "postventa",
        "estado": "candidata_caso",
        "faltantes": [],
        "start_timestamp": 1795468501000,
    }


def consulta(call_id):
    return {
        "call_id": call_id,
        "tipo": "consulta_general",
        "estado": "candidata_caso",
    }


class CronPostventasAutomaticas(unittest.TestCase):

    def ejecutar(
        self, postventas, generales=None, *,
        auto=True, escrituras=True, existentes=(),
        fecha_minima="1795468500000",
        estados_casos=None,
    ):
        generales = generales or []
        existentes = set(existentes)
        intentos = []

        resultado = {
            "estado": "simulacion",
            "cotizaciones_sandbox_candidatas": [],
            "consultas_detectadas": generales,
            "postventas_detectadas": postventas,
            "consultas_en_revision": [],
            "total_consultas_en_revision": 0,
            "revisiones_detectadas": [],
            "total_revisiones_detectadas": 0,
        }

        cotizaciones = {
            "estado": "sandbox_habilitado",
            "creadas": 0,
            "ya_registradas": 0,
            "bloqueadas": 0,
            "motivo_bloqueo": None,
        }

        def consultar_lotes(lista, **kwargs):
            return {
                "estado": "ok",
                "lotes_consultados": 1 if lista else 0,
                "resultados": {
                    item["call_id"]: {
                        "estado": (
                            "encontrado"
                            if item["call_id"] in existentes
                            else "no_encontrado"
                        ),
                        "registro_id": (
                            "123456789"
                            if item["call_id"] in existentes
                            else None
                        ),
                    }
                    for item in lista
                },
            }

        def planificar(lista, resultados, max_pendientes=30):
            pendientes = [
                item for item in lista
                if resultados[item["call_id"]]["estado"]
                == "no_encontrado"
            ]
            seleccionadas = pendientes[:max_pendientes]
            return {
                "seleccionadas": seleccionadas,
                "ya_registradas": len(lista) - len(pendientes),
                "total_pendientes": len(pendientes),
                "pendientes_fuera_de_limite": (
                    len(pendientes) - len(seleccionadas)
                ),
            }

        def procesar_caso(item, **kwargs):
            intentos.append({
                "call_id": item["call_id"],
                "simulacion": kwargs["simulacion"],
            })
            return {
                "estado": (
                    "creacion_simulada"
                    if kwargs["simulacion"]
                    else (estados_casos or {}).get(
                        item["call_id"], "creado"
                    )
                ),
            }

        modulos = {
            "flask": modulo(
                "flask",
                current_app=types.SimpleNamespace(logger=Logger()),
                jsonify=lambda dato: dato,
            ),
            "utils.security": modulo(
                "utils.security",
                cron_autorizado=lambda: True,
            ),
            "services.retell_procesador": modulo(
                "services.retell_procesador",
                procesar_pendientes_sofia=lambda *a, **k: resultado,
            ),
            "services.retell_ventanas_recuperacion": modulo(
                "services.retell_ventanas_recuperacion",
                seleccionar_ventana_historica_rotativa=lambda *a: {
                    "indice_ventana": 1,
                    "total_ventanas": 1,
                },
            ),
            "services.sofia.cron_cotizaciones_sandbox": modulo(
                "services.sofia.cron_cotizaciones_sandbox",
                procesar_cotizaciones_cron_sandbox=lambda *a, **k: cotizaciones,
            ),
            "services.sofia.crm_sandbox": modulo(
                "services.sofia.crm_sandbox",
                obtener_conexion_sandbox=lambda: {
                    "obtener_token": lambda: "token_ficticio",
                },
            ),
            "services.retell_casos_lote": modulo(
                "services.retell_casos_lote",
                preparar_borradores_consultas=lambda lista: [
                    {"call_id": x["call_id"]} for x in lista
                ],
                consultar_consultas_en_lotes=consultar_lotes,
                planificar_recuperacion_consultas=planificar,
            ),
            "services.retell_casos": modulo(
                "services.retell_casos",
                buscar_casos_consulta_por_call_ids=lambda *a, **k: {},
                buscar_caso_consulta_por_call_id=lambda *a, **k: {},
                procesar_creacion_caso_consulta=procesar_caso,
            ),
            "services.retell_seguimiento_zoho": modulo(
                "services.retell_seguimiento_zoho",
                buscar_asunto_control_zoho=lambda *a, **k: {},
            ),
        }

        variables = {
            "RETELL_SOFIA_AGENT_ID": "agent_ficticio",
            "SOFIA_SANDBOX_POSTVENTAS_AUTO_ENABLED": (
                "true" if auto else "false"
            ),
            "SOFIA_SANDBOX_CASES_WRITES_ENABLED": (
                "true" if escrituras else "false"
            ),
            "SOFIA_SANDBOX_CASES_ALLOWED_CALL_ID": (
                "call_autorizada_382"
            ),
            "SOFIA_SANDBOX_CASES_OWNER_ID": "123456789",
            "SOFIA_SANDBOX_POSTVENTAS_AUTO_DESDE_MS": fecha_minima,
        }

        ruta = (
            Path(__file__).resolve().parents[1]
            / "routes" / "cron_sofia.py"
        )

        with patch.dict(sys.modules, modulos):
            with patch.dict(os.environ, variables):
                with patch(
                    "requests.post",
                    side_effect=AssertionError(
                        "Solicitud HTTP real no autorizada"
                    ),
                ):
                    spec = importlib.util.spec_from_file_location(
                        "cron_sofia_auto_382", ruta
                    )
                    cargado = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(cargado)

                    app = Aplicacion()
                    cargado.register_sofia_cron_routes(app)
                    respuesta, codigo = app.rutas["/cron/sofia"]()

        return respuesta, codigo, intentos

    def test_auto_solo_postventas(self):
        respuesta, codigo, intentos = self.ejecutar(
            [postventa("call_postventa_382")],
            [consulta("call_general_382")],
        )
        self.assertEqual(codigo, 200)
        self.assertEqual(
            [x["call_id"] for x in intentos],
            ["call_postventa_382"],
        )
        self.assertFalse(intentos[0]["simulacion"])
        self.assertEqual(respuesta["resumen_casos"]["creado"], 1)

    def test_auto_sin_postventas(self):
        respuesta, codigo, intentos = self.ejecutar(
            [],
            [consulta("call_solo_general_382")],
        )
        self.assertEqual(codigo, 200)
        self.assertEqual(intentos, [])
        self.assertEqual(respuesta["resumen_casos"]["creado"], 0)

    def test_auto_rechaza_postventa_invalida(self):
        invalida = postventa("call_invalida_382")
        invalida["faltantes"] = ["rut_cliente"]
        respuesta, codigo, intentos = self.ejecutar([invalida])
        self.assertEqual(codigo, 503)
        self.assertEqual(intentos, [])

    def test_auto_rechaza_identificadores_duplicados(self):
        repetida = postventa("call_repetida_382")
        respuesta, codigo, intentos = self.ejecutar(
            [repetida, repetida.copy()]
        )
        self.assertEqual(codigo, 503)
        self.assertEqual(intentos, [])

    def test_auto_no_duplica_caso_existente(self):
        respuesta, codigo, intentos = self.ejecutar(
            [postventa("call_existente_382")],
            existentes={"call_existente_382"},
        )
        self.assertEqual(codigo, 200)
        self.assertEqual(intentos, [])
        self.assertEqual(respuesta["casos_ya_registrados"], 1)
        self.assertEqual(respuesta["resumen_casos"]["creado"], 0)

    def test_modo_anterior_conserva_call_id(self):
        respuesta, codigo, intentos = self.ejecutar(
            [
                postventa("call_autorizada_382"),
                postventa("call_otra_382"),
            ],
            auto=False,
        )
        self.assertEqual(codigo, 200)
        self.assertEqual(
            [x["call_id"] for x in intentos],
            ["call_autorizada_382"],
        )

    def test_escrituras_desactivadas_no_crean_casos(self):
        respuesta, codigo, intentos = self.ejecutar(
            [postventa("call_sin_escritura_382")],
            auto=True,
            escrituras=False,
        )
        self.assertEqual(codigo, 200)
        self.assertTrue(all(x["simulacion"] for x in intentos))
        self.assertEqual(respuesta["resumen_casos"]["creado"], 0)


    def test_auto_excluye_postventa_antigua(self):
        antigua = postventa("call_antigua_402")
        antigua["start_timestamp"] = 1795468499000

        respuesta, codigo, intentos = self.ejecutar(
            [antigua]
        )

        self.assertEqual(codigo, 200)
        self.assertEqual(intentos, [])
        self.assertEqual(
            respuesta["resumen_casos"]["creado"], 0
        )

    def test_auto_procesa_dos_postventas_nuevas(self):
        respuesta, codigo, intentos = self.ejecutar([
            postventa("call_nueva_a_402"),
            postventa("call_nueva_b_402"),
        ])

        self.assertEqual(codigo, 200)
        self.assertEqual(len(intentos), 2)
        self.assertEqual(respuesta["resumen_casos"]["creado"], 2)
        self.assertEqual(
            respuesta["postventas_auto_pendientes_por_continuar"], 0
        )

    def test_auto_limita_siete_postventas_a_tres(self):
        datos = [
            postventa(f"call_lote_{i}_423")
            for i in range(7)
        ]

        respuesta, codigo, intentos = self.ejecutar(datos)

        self.assertEqual(codigo, 200)
        self.assertEqual(
            [x["call_id"] for x in intentos],
            [
                "call_lote_0_423",
                "call_lote_1_423",
                "call_lote_2_423",
            ],
        )
        self.assertEqual(respuesta["resumen_casos"]["creado"], 3)
        self.assertEqual(
            respuesta["postventas_auto_pendientes_por_continuar"], 4
        )

    def test_auto_excluye_existente_y_crea_nueva(self):
        respuesta, codigo, intentos = self.ejecutar(
            [
                postventa("call_existente_402"),
                postventa("call_nueva_402"),
            ],
            existentes={"call_existente_402"},
        )

        self.assertEqual(codigo, 200)
        self.assertEqual(
            [x["call_id"] for x in intentos],
            ["call_nueva_402"],
        )
        self.assertEqual(
            respuesta["casos_ya_registrados"], 1
        )

    def test_auto_rechaza_fecha_no_verificable(self):
        sin_fecha = postventa("call_sin_fecha_402")
        sin_fecha.pop("start_timestamp")

        respuesta, codigo, intentos = self.ejecutar(
            [sin_fecha]
        )

        self.assertEqual(codigo, 503)
        self.assertEqual(intentos, [])

    def test_auto_rechaza_fecha_minima_ausente(self):
        respuesta, codigo, intentos = self.ejecutar(
            [postventa("call_nueva_402")],
            fecha_minima="",
        )

        self.assertEqual(codigo, 503)
        self.assertEqual(intentos, [])

    def test_auto_ignora_antigua_y_crea_reciente(self):
        antigua = postventa("call_antigua_402")
        antigua["start_timestamp"] = 1795468499000

        respuesta, codigo, intentos = self.ejecutar([
            antigua,
            postventa("call_reciente_402"),
        ])

        self.assertEqual(codigo, 200)
        self.assertEqual(
            [x["call_id"] for x in intentos],
            ["call_reciente_402"],
        )

    def test_auto_detiene_lote_si_zoho_bloquea(self):
        datos = [
            postventa("call_primera_424"),
            postventa("call_segunda_424"),
            postventa("call_tercera_424"),
        ]
        respuesta, codigo, intentos = self.ejecutar(
            datos,
            estados_casos={"call_primera_424": "bloqueado"},
        )
        self.assertEqual(codigo, 503)
        self.assertEqual(
            [i["call_id"] for i in intentos],
            ["call_primera_424"],
        )
        self.assertEqual(respuesta["resumen_casos"]["bloqueado"], 1)
        self.assertEqual(respuesta["resumen_casos"]["creado"], 0)

    def test_auto_rechaza_simulacion_inesperada(self):
        respuesta, codigo, intentos = self.ejecutar(
            [postventa("call_simulada_424")],
            estados_casos={
                "call_simulada_424": "creacion_simulada"
            },
        )
        self.assertEqual(codigo, 503)
        self.assertEqual(len(intentos), 1)
        self.assertEqual(respuesta["resumen_casos"]["bloqueado"], 1)
        self.assertEqual(respuesta["resumen_casos"]["creado"], 0)


if __name__ == "__main__":
    unittest.main()
