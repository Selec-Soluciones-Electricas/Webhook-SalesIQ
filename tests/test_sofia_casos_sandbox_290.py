"""Pruebas de permisos aislados de Casos Sandbox, sin API externa."""
import os
import unittest
from unittest.mock import patch
from pathlib import Path
from services.retell_casos import (
    preparar_borrador_caso_consulta,
    planificar_creacion_caso_consulta,
    preparar_solicitud_creacion_caso_consulta,
    ejecutar_creacion_caso_consulta_controlada,
    procesar_creacion_caso_consulta,
)

OWNER = "6098701000090407001"
BASE = "https://sandbox.zohoapis.com/crm/v8"
CALL_ID = "call_prueba_segura_290"


def clasificacion():
    return {
        "estado": "candidata_caso",
        "call_id": CALL_ID,
        "tipo_solicitud": "postventa",
        "contacto": {"nombre_cliente": "Cliente de prueba"},
        "resumen": "Solicitud postventa ficticia",
    }


def solicitud():
    borrador = preparar_borrador_caso_consulta(clasificacion())
    decision = planificar_creacion_caso_consulta(borrador, {
        "estado": "no_encontrado", "registro_id": None
    })
    return preparar_solicitud_creacion_caso_consulta(decision)


class Respuesta:
    status_code = 201
    def json(self):
        return {"data": [{"code": "SUCCESS", "status": "success", "details": {"id": "123456789"}}]}


class CasosSandboxSeguros(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "SOFIA_SANDBOX_CASES_WRITES_ENABLED": "false",
            "RETELL_CRM_WRITES_ENABLED": "false",
            "RETELL_CASES_WRITES_ENABLED": "false",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.enviados = []

    def enviar(self, url, **kwargs):
        self.enviados.append((url, kwargs))
        return Respuesta()

    def ejecutar(self, **otros):
        parametros = {
            "simulacion": False, "propietario_id": OWNER,
            "http_post": self.enviar,
            "obtener_token": lambda: "token_ficticio",
            "crm_base": BASE,
        }
        parametros.update(otros)
        return ejecutar_creacion_caso_consulta_controlada(solicitud(), **parametros)

    def test_todos_los_permisos_antiguos_no_autorizan(self):
        os.environ["RETELL_CRM_WRITES_ENABLED"] = "true"
        os.environ["RETELL_CASES_WRITES_ENABLED"] = "true"
        res = self.ejecutar()
        self.assertEqual(res["estado"], "bloqueado")
        self.assertEqual(self.enviados, [])

    def test_flag_sandbox_sin_optin_del_invocador_no_autoriza(self):
        os.environ["SOFIA_SANDBOX_CASES_WRITES_ENABLED"] = "true"
        res = self.ejecutar()
        self.assertEqual(res["estado"], "bloqueado")
        self.assertEqual(self.enviados, [])

    def test_optin_sin_flag_sandbox_no_autoriza(self):
        res = self.ejecutar(sandbox_cases_writes_enabled=True)
        self.assertEqual(res["estado"], "bloqueado")
        self.assertEqual(self.enviados, [])

    def test_sandbox_optin_explicito_permite_insercion(self):
        os.environ["SOFIA_SANDBOX_CASES_WRITES_ENABLED"] = "true"
        res = self.ejecutar(sandbox_cases_writes_enabled=True)
        self.assertEqual(res["estado"], "creado")
        self.assertEqual(len(self.enviados), 1)
        self.assertEqual(self.enviados[0][0], BASE + "/Cases")

    def test_sandbox_optin_nunca_permite_produccion(self):
        os.environ["SOFIA_SANDBOX_CASES_WRITES_ENABLED"] = "true"
        res = self.ejecutar(
            sandbox_cases_writes_enabled=True,
            crm_base="https://www.zohoapis.com/crm/v8",
        )
        self.assertEqual(res["estado"], "bloqueado")
        self.assertEqual(self.enviados, [])

    def test_propietario_invalido_bloquea(self):
        os.environ["SOFIA_SANDBOX_CASES_WRITES_ENABLED"] = "true"
        res = self.ejecutar(
            sandbox_cases_writes_enabled=True, propietario_id="invalid"
        )
        self.assertEqual(res["estado"], "bloqueado")
        self.assertEqual(self.enviados, [])

    def test_simulacion_no_realiza_escrituras(self):
        os.environ["SOFIA_SANDBOX_CASES_WRITES_ENABLED"] = "true"
        res = self.ejecutar(
            sandbox_cases_writes_enabled=True, simulacion=True
        )
        self.assertEqual(res["estado"], "bloqueado")
        self.assertEqual(self.enviados, [])

    def test_cron_casos_no_exige_escritor_antiguo(self):
        codigo = (Path(__file__).resolve().parent.parent / "routes" / "cron_sofia.py").read_text(encoding="utf-8")
        segmento = codigo.split("# Exigir autorizacion explicita antes de escribir.")[-1]
        self.assertIn("sandbox_cases_writes_enabled=escritura_sandbox", codigo)
        self.assertIn('SOFIA_SANDBOX_CASES_ALLOWED_CALL_ID', codigo)
        self.assertNotIn('os.getenv(\n                    "RETELL_CRM_WRITES_ENABLED"', codigo)

    def test_procesador_solo_escribe_con_permisos_sandbox(self):
        os.environ["SOFIA_SANDBOX_CASES_WRITES_ENABLED"] = "true"
        res = procesar_creacion_caso_consulta(
            clasificacion(),
            consultar_asunto=lambda modulo, asunto: {"estado": "no_encontrado", "registro_id": None},
            consultar_call_id=lambda call_id: {"estado": "no_encontrado", "registro_id": None},
            simulacion=False,
            propietario_id=OWNER,
            http_post=self.enviar,
            obtener_token=lambda: "token_ficticio",
            crm_base=BASE,
            sandbox_cases_writes_enabled=True,
        )
        self.assertEqual(res["estado"], "creado")
        self.assertEqual(len(self.enviados), 1)

if __name__ == "__main__":
    unittest.main()
