"""Verifica HTTP del cron sin conectar a Zoho, Retell ni Flask real."""
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


def modulo(nombre, **atributos):
    resultado = types.ModuleType(nombre)
    for clave, valor in atributos.items():
        setattr(resultado, clave, valor)
    return resultado


class Logger:
    def info(self, *args): pass
    def warning(self, *args): pass
    def exception(self, *args): pass


class Aplicacion:
    def __init__(self): self.rutas = {}
    def post(self, ruta):
        def registrar(funcion):
            self.rutas[ruta] = funcion
            return funcion
        return registrar


class RespuestasCron(unittest.TestCase):
    def ejecutar(self, estado_cotizacion="sandbox_habilitado", revisiones=1):
        procesado = {
            "estado": "simulacion",
            "cotizaciones_sandbox_candidatas": [dict(call_id="prueba")],
            "consultas_en_revision": [{"motivo": "incompleta"}],
            "total_consultas_en_revision": 1,
            "revisiones_detectadas": [{"motivo": "datos_incompletos"}] * revisiones,
            "total_revisiones_detectadas": revisiones,
            "consultas_detectadas": [],
            "postventas_detectadas": [],
        }
        resumen = {
            "estado": estado_cotizacion,
            "creadas": 1,
            "ya_registradas": 0,
            "bloqueadas": int(estado_cotizacion == "parcial"),
            "motivo_bloqueo": "resultado_incierto" if estado_cotizacion == "parcial" else None,
        }
        fake_flask = modulo("flask", current_app=types.SimpleNamespace(logger=Logger()), jsonify=lambda x: x)
        modules = {
            "flask": fake_flask,
            "utils.security": modulo("utils.security", cron_autorizado=lambda: True),
            "services.retell_procesador": modulo(
                "services.retell_procesador", procesar_pendientes_sofia=lambda *a, **k: procesado
            ),
            "services.retell_ventanas_recuperacion": modulo(
                "services.retell_ventanas_recuperacion",
                seleccionar_ventana_historica_rotativa=lambda *a: {
                    "indice_ventana": 1, "total_ventanas": 1,
                },
            ),
            "services.sofia.cron_cotizaciones_sandbox": modulo(
                "services.sofia.cron_cotizaciones_sandbox",
                procesar_cotizaciones_cron_sandbox=lambda *a, **k: resumen,
            ),
            "services.sofia.crm_sandbox": modulo(
                "services.sofia.crm_sandbox", obtener_conexion_sandbox=lambda: {},
            ),
            "services.retell_casos_lote": modulo(
                "services.retell_casos_lote",
                preparar_borradores_consultas=lambda lista: [],
                consultar_consultas_en_lotes=lambda *a, **k: {
                    "estado": "ok", "resultados": {}, "lotes_consultados": 0,
                },
                planificar_recuperacion_consultas=lambda *a, **k: {
                    "seleccionadas": [], "ya_registradas": 0,
                    "total_pendientes": 0, "pendientes_fuera_de_limite": 0,
                },
            ),
            "services.retell_casos": modulo(
                "services.retell_casos",
                buscar_casos_consulta_por_call_ids=lambda *a, **k: {},
                buscar_caso_consulta_por_call_id=lambda *a, **k: {},
                procesar_creacion_caso_consulta=lambda *a, **k: {},
            ),
            "services.retell_seguimiento_zoho": modulo(
                "services.retell_seguimiento_zoho",
                buscar_asunto_control_zoho=lambda *a, **k: {},
            ),
        }
        ruta = Path(__file__).resolve().parents[1] / "routes" / "cron_sofia.py"
        aplicacion = Aplicacion()
        with patch.dict(sys.modules, modules):
            with patch.dict("os.environ", {"RETELL_SOFIA_AGENT_ID": "agent_prueba"}):
                spec = importlib.util.spec_from_file_location("cron_sofia_isolado", ruta)
                importado = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(importado)
                importado.register_sofia_cron_routes(aplicacion)
                respuesta, status = aplicacion.rutas["/cron/sofia"]()
        return respuesta, status

    def test_cotizacion_creada_no_falla_por_revisiones_independientes(self):
        respuesta, status = self.ejecutar("sandbox_habilitado", 1)
        self.assertEqual(status, 200)
        self.assertEqual(respuesta["resumen_cotizaciones"]["creadas"], 1)
        self.assertTrue(respuesta["escrituras_crm"])
        self.assertEqual(respuesta["consultas_en_revision"], 1)
        self.assertTrue(respuesta["recuperacion_requerida"])

    def test_error_crm_verdadero_se_reporta_con_resumen(self):
        respuesta, status = self.ejecutar("parcial", 0)
        self.assertEqual(status, 503)
        self.assertTrue(respuesta["escrituras_crm"])
        self.assertEqual(respuesta["resumen_cotizaciones"]["creadas"], 1)
        self.assertEqual(respuesta["resumen_cotizaciones"]["motivo_bloqueo"], "resultado_incierto")


if __name__ == "__main__":
    unittest.main()
