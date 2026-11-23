"""Pruebas locales, sin Retell, Zoho ni credenciales reales."""
import copy
import os
import unittest
from unittest.mock import patch

from services.sofia.cron_cotizaciones_sandbox import procesar_cotizaciones_cron_sandbox
from services.sofia.registro_cotizaciones_sandbox import registrar_cotizacion_sandbox
from services.sofia.crm_sandbox import obtener_token_sandbox, _TOKEN_CACHE


BASE = "https://sandbox.zohoapis.com/crm/v8/"
OWNER = "6098701000090407001"
AGENTE = "agent_ficticio"


class Response:
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self.body = body or {}

    def json(self):
        return self.body


def llamada(call_id="call_245_a", marca=2000000000000):
    return {
        "agent_id": AGENTE,
        "call_id": call_id,
        "start_timestamp": marca,
        "call_type": "phone_call",
        "call_status": "ended",
        "call_analysis": {
            "custom_analysis_data": {
                "tipo_solicitud": "cotizacion",
                "empresa": "Empresa Ficticia",
                "rut_cliente": "12.345.678-5",
                "nombre_cliente": "Cliente Ficticio",
                "email_cliente": "cliente@example.com",
                "telefono_cliente": "+56912345678",
                "direccion_entrega": "Santiago",
                "productos_solicitados": (
                    "Producto 1 | descripcion: Contactor | marca: Schneider | "
                    "numero de parte: LC1D09 | cantidad: 2"
                ),
            }
        },
    }


class ZohoFicticio:
    def __init__(self):
        self.data = {"Accounts": [], "Contacts": [], "Deals": []}
        self.creados = []
        self.siguiente = 1000000000
        self.fallar_deal = False
        self.busqueda_retrasada = False

    def get(self, url, **kwargs):
        assert url.startswith(BASE)
        assert kwargs["allow_redirects"] is False
        ruta = url[len(BASE):]
        if ruta == "users/" + OWNER:
            return Response(200, {"users": [{"id": OWNER, "status": "active"}]})
        if ruta.endswith("/search"):
            modulo = ruta.split("/")[0]
            campo, valor = kwargs["params"]["criteria"][1:-1].split(":equals:", 1)
            encontrados = [
                x for x in self.data[modulo]
                if str(x.get(campo) or "").casefold() == valor.casefold()
            ]
            if self.busqueda_retrasada and modulo in ("Accounts", "Contacts"):
                encontrados = []
            return Response(200, {"data": encontrados, "info": {"more_records": False}}) if encontrados else Response(204)
        if ruta.startswith("Contacts/"):
            id_contacto = ruta.split("/")[1]
            encontrados = [x for x in self.data["Contacts"] if x["id"] == id_contacto]
            return Response(200, {"data": encontrados}) if encontrados else Response(404)
        if ruta in self.data:
            modulo = ruta
            return Response(200, {"data": self.data[modulo], "info": {"more_records": False}}) if self.data[modulo] else Response(204)
        raise AssertionError("URL GET no autorizada")

    def post(self, url, **kwargs):
        assert url.startswith(BASE)
        assert kwargs["allow_redirects"] is False
        modulo = url[len(BASE):]
        assert modulo in self.data
        assert kwargs["json"].get("trigger") == []
        if self.fallar_deal and modulo == "Deals":
            return Response(400, {"data": [{"code": "MANDATORY_NOT_FOUND", "status": "error"}]})
        obj = copy.deepcopy(kwargs["json"]["data"][0])
        obj["id"] = str(self.siguiente)
        self.siguiente += 1
        self.data[modulo].append(obj)
        self.creados.append(modulo)
        return Response(201, {"data": [{"code": "SUCCESS", "status": "success", "details": {"id": obj["id"]}}]})

    @property
    def conexion(self):
        return {"base": "https://sandbox.zohoapis.com", "obtener_token": lambda: "token_de_prueba", "http_get": self.get}


ENV_WRITE = {
    "SOFIA_SANDBOX_DEALS_WRITES_ENABLED": "true",
    "SOFIA_SANDBOX_DEALS_OWNER_ID": OWNER,
    "SOFIA_SANDBOX_DEALS_CUTOFF_MS": "1999999999999",
    "SOFIA_SANDBOX_DEALS_CLOSE_DAYS": "30",
    "SOFIA_SANDBOX_DEALS_MAX_PER_RUN": "1",
    "SOFIA_SANDBOX_DEALS_ALLOWED_CALL_IDS": "call_245_a,call_245_b",
}


class Flujo(unittest.TestCase):
    def test_automatica_no_se_atasca_en_llamadas_ya_registradas(self):
        crm = ZohoFicticio()
        env = {**ENV_WRITE, "SOFIA_SANDBOX_DEALS_MODE": "automatico",
               "SOFIA_SANDBOX_DEALS_ALLOWED_CALL_IDS": "",
               "SOFIA_SANDBOX_DEALS_MAX_PER_RUN": "1"}
        # La llamada que ya existe no debe consumir el cupo de creacion.
        con_anterior = llamada("call_anterior")
        con_nueva = llamada("call_nueva")
        with patch.dict(os.environ, env):
            original = procesar_cotizaciones_cron_sandbox(
                [con_anterior], AGENTE, conexion=crm.conexion, http_post=crm.post,
            )
            siguiente = procesar_cotizaciones_cron_sandbox(
                [con_anterior, con_nueva], AGENTE,
                conexion=crm.conexion, http_post=crm.post,
            )
            repetido = procesar_cotizaciones_cron_sandbox(
                [con_anterior, con_nueva], AGENTE,
                conexion=crm.conexion, http_post=crm.post,
            )
        self.assertEqual(original["creadas"], 1)
        self.assertEqual(siguiente["creadas"], 1)
        self.assertEqual(len(crm.data["Deals"]), 2)
        self.assertEqual(repetido["creadas"], 0)
        self.assertEqual(repetido["ya_registradas"], 2)

    def test_deal_creado_pero_respuesta_perdida_se_reconcilia(self):
        """Zoho guardo Deals; falló la respuesta HTTP: no duplicar."""
        crm = ZohoFicticio()
        def post_con_timeout_tras_guardar(url, **kwargs):
            respuesta = crm.post(url, **kwargs)
            if url == BASE + "Deals":
                raise TimeoutError("la respuesta no llego al servidor")
            return respuesta
        env = {**ENV_WRITE, "SOFIA_SANDBOX_DEALS_MODE": "automatico",
               "SOFIA_SANDBOX_DEALS_ALLOWED_CALL_IDS": ""}
        with patch.dict(os.environ, env):
            primero = procesar_cotizaciones_cron_sandbox(
                [llamada("call_reconciliar")], AGENTE,
                conexion=crm.conexion, http_post=post_con_timeout_tras_guardar,
            )
            segundo = procesar_cotizaciones_cron_sandbox(
                [llamada("call_reconciliar")], AGENTE,
                conexion=crm.conexion, http_post=post_con_timeout_tras_guardar,
            )
        self.assertEqual(primero["estado"], "sandbox_habilitado")
        self.assertEqual(primero["ya_registradas"], 1)
        self.assertEqual(segundo["ya_registradas"], 1)
        self.assertEqual(crm.creados, ["Accounts", "Contacts", "Deals"])

    def test_deal_existente_con_busqueda_desactualizada_no_duplicar(self):
        crm = ZohoFicticio()
        env = {**ENV_WRITE, "SOFIA_SANDBOX_DEALS_MODE": "automatico",
               "SOFIA_SANDBOX_DEALS_ALLOWED_CALL_IDS": ""}
        with patch.dict(os.environ, env):
            primero = procesar_cotizaciones_cron_sandbox(
                [llamada("call_indexacion")], AGENTE,
                conexion=crm.conexion, http_post=crm.post,
            )
            self.assertEqual(primero["creadas"], 1)
            def get_busqueda_desactualizada(url, **kwargs):
                if url == BASE + "Deals/search":
                    return Response(204)
                return crm.get(url, **kwargs)
            conexion = crm.conexion
            conexion["http_get"] = get_busqueda_desactualizada
            repetido = procesar_cotizaciones_cron_sandbox(
                [llamada("call_indexacion")], AGENTE,
                conexion=conexion, http_post=crm.post,
            )
        self.assertEqual(repetido["estado"], "sandbox_habilitado")
        self.assertEqual(repetido["ya_registradas"], 1)
        self.assertEqual(crm.creados, ["Accounts", "Contacts", "Deals"])

    def test_fallo_real_en_deal_no_se_marca_como_creado(self):
        crm = ZohoFicticio()
        env = {**ENV_WRITE, "SOFIA_SANDBOX_DEALS_MODE": "automatico",
               "SOFIA_SANDBOX_DEALS_ALLOWED_CALL_IDS": ""}
        def post_no_guardado(url, **kwargs):
            if url == BASE + "Deals":
                raise TimeoutError("no se confirmo el envio")
            return crm.post(url, **kwargs)
        with patch.dict(os.environ, env):
            fallido = procesar_cotizaciones_cron_sandbox(
                [llamada("call_fallo_real")], AGENTE,
                conexion=crm.conexion, http_post=post_no_guardado,
            )
        self.assertEqual(fallido["estado"], "parcial")
        self.assertEqual(fallido["creadas"], 0)
        self.assertEqual(fallido["motivo_bloqueo"], "insercion_sin_confirmacion")
        self.assertEqual(crm.creados, ["Accounts", "Contacts"])

    def test_modo_automatico_sin_whitelist_y_reintento(self):
        crm = ZohoFicticio()
        env = {
            **ENV_WRITE,
            "SOFIA_SANDBOX_DEALS_MODE": "automatico",
            "SOFIA_SANDBOX_DEALS_ALLOWED_CALL_IDS": "",
        }
        with patch.dict(os.environ, env):
            primero = procesar_cotizaciones_cron_sandbox(
                [llamada("call_auto_a")], AGENTE,
                conexion=crm.conexion, http_post=crm.post,
            )
            repetido = procesar_cotizaciones_cron_sandbox(
                [llamada("call_auto_a")], AGENTE,
                conexion=crm.conexion, http_post=crm.post,
            )
            siguiente = procesar_cotizaciones_cron_sandbox(
                [llamada("call_auto_b")], AGENTE,
                conexion=crm.conexion, http_post=crm.post,
            )
        self.assertEqual(primero["creadas"], 1)
        self.assertEqual(repetido["ya_registradas"], 1)
        self.assertEqual(siguiente["creadas"], 1)
        self.assertEqual(crm.creados, ["Accounts", "Contacts", "Deals", "Deals"])

    def test_automatico_excluye_llamadas_anteriores_y_no_escribe_sin_habilitar(self):
        crm = ZohoFicticio()
        env = {
            **ENV_WRITE,
            "SOFIA_SANDBOX_DEALS_MODE": "automatico",
            "SOFIA_SANDBOX_DEALS_ALLOWED_CALL_IDS": "",
        }
        with patch.dict(os.environ, env):
            vieja = procesar_cotizaciones_cron_sandbox(
                [llamada("call_auto_vieja", marca=1999999999998)], AGENTE,
                conexion=crm.conexion, http_post=crm.post,
            )
        with patch.dict(os.environ, {
            **env, "SOFIA_SANDBOX_DEALS_WRITES_ENABLED": "false"
        }):
            desactivada = procesar_cotizaciones_cron_sandbox(
                [llamada("call_auto_nueva")], AGENTE,
                conexion=crm.conexion, http_post=crm.post,
            )
        self.assertEqual(vieja["anteriores_al_inicio"], 1)
        self.assertEqual(desactivada["estado"], "simulacion")
        self.assertEqual(crm.creados, [])

    def test_automatico_rechaza_configuracion_ambigua(self):
        crm = ZohoFicticio()
        opciones = [
            ("automatico", "call_245_a"),
            ("desconocido", ""),
        ]
        for modo, lista in opciones:
            with self.subTest(modo=modo, lista=lista):
                with patch.dict(os.environ, {
                    **ENV_WRITE,
                    "SOFIA_SANDBOX_DEALS_MODE": modo,
                    "SOFIA_SANDBOX_DEALS_ALLOWED_CALL_IDS": lista,
                }):
                    resultado = procesar_cotizaciones_cron_sandbox(
                        [llamada()], AGENTE,
                        conexion=crm.conexion, http_post=crm.post,
                    )
                self.assertEqual(resultado["estado"], "bloqueado")
                self.assertEqual(crm.creados, [])


    def test_lista_autorizada_obligatoria(self):
        crm = ZohoFicticio()
        with patch.dict(os.environ, {
            **ENV_WRITE,
            "SOFIA_SANDBOX_DEALS_ALLOWED_CALL_IDS": "",
        }):
            resumen = procesar_cotizaciones_cron_sandbox(
                [llamada()],
                AGENTE,
                conexion=crm.conexion,
                http_post=crm.post,
            )

        self.assertEqual(resumen["estado"], "bloqueado")
        self.assertEqual(crm.creados, [])

    def test_por_defecto_no_escribe(self):
        crm = ZohoFicticio()
        with patch.dict(os.environ, {"SOFIA_SANDBOX_DEALS_WRITES_ENABLED": "false"}):
            resumen = procesar_cotizaciones_cron_sandbox([llamada()], AGENTE, conexion=crm.conexion, http_post=crm.post)
        self.assertEqual(resumen["estado"], "simulacion")
        self.assertEqual(resumen["listas"], 1)
        self.assertEqual(crm.creados, [])

    def test_flujo_completo_y_reintento_idempotente(self):
        crm = ZohoFicticio()
        with patch.dict(os.environ, ENV_WRITE):
            primero = procesar_cotizaciones_cron_sandbox([llamada()], AGENTE, conexion=crm.conexion, http_post=crm.post)
            segundo = procesar_cotizaciones_cron_sandbox([llamada()], AGENTE, conexion=crm.conexion, http_post=crm.post)
            tercero = procesar_cotizaciones_cron_sandbox([llamada("call_245_b")], AGENTE, conexion=crm.conexion, http_post=crm.post)
        self.assertEqual(primero["creadas"], 1)
        self.assertEqual(segundo["ya_registradas"], 1)
        self.assertEqual(tercero["creadas"], 1)
        self.assertEqual(crm.creados, ["Accounts", "Contacts", "Deals", "Deals"])
        self.assertEqual(crm.data["Deals"][0]["Cantidad_de_productos"], 1)

    def test_retraso_de_indexacion_reusa_cuenta_y_contacto(self):
        crm = ZohoFicticio()
        with patch.dict(os.environ, ENV_WRITE):
            procesar_cotizaciones_cron_sandbox([llamada()], AGENTE, conexion=crm.conexion, http_post=crm.post)
            crm.busqueda_retrasada = True
            respuesta = procesar_cotizaciones_cron_sandbox([llamada("call_245_b")], AGENTE, conexion=crm.conexion, http_post=crm.post)
        self.assertEqual(respuesta["creadas"], 1)
        self.assertEqual(crm.creados, ["Accounts", "Contacts", "Deals", "Deals"])

    def test_no_retroactivo_ni_sin_autorizacion(self):
        crm = ZohoFicticio()
        with patch.dict(os.environ, ENV_WRITE):
            viejo = procesar_cotizaciones_cron_sandbox([llamada(marca=1999999999998)], AGENTE, conexion=crm.conexion, http_post=crm.post)
        self.assertEqual(viejo["anteriores_al_inicio"], 1)
        self.assertEqual(crm.creados, [])
        with patch.dict(os.environ, {**ENV_WRITE, "SOFIA_SANDBOX_DEALS_ALLOWED_CALL_IDS": "call_otra"}):
            ajeno = procesar_cotizaciones_cron_sandbox([llamada()], AGENTE, conexion=crm.conexion, http_post=crm.post)
        self.assertEqual(ajeno["fuera_de_lista"], 1)
        self.assertEqual(crm.creados, [])

    def test_creacion_parcial_no_duplica_clientes_al_reanudar(self):
        crm = ZohoFicticio()
        crm.fallar_deal = True
        with patch.dict(os.environ, ENV_WRITE):
            fallido = procesar_cotizaciones_cron_sandbox([llamada()], AGENTE, conexion=crm.conexion, http_post=crm.post)
            crm.fallar_deal = False
            recuperado = procesar_cotizaciones_cron_sandbox([llamada()], AGENTE, conexion=crm.conexion, http_post=crm.post)
        self.assertEqual(fallido["estado"], "parcial")
        self.assertEqual(recuperado["creadas"], 1)
        self.assertEqual(crm.creados, ["Accounts", "Contacts", "Deals"])

    def test_independiente_del_writer_produccion(self):
        from pathlib import Path
        codigo = Path("routes/cron_sofia.py").read_text(encoding="utf-8")
        self.assertIn("simulacion=True", codigo)
        self.assertIn("incluir_cotizaciones_sandbox=True", codigo)
        self.assertNotIn("simulacion=False", codigo)

    def test_procesador_retell_entrega_candidatas_solo_con_opt_in(self):
        import sys
        import importlib
        from types import ModuleType
        stub = ModuleType("services.retell_cotizaciones")
        stub.registrar_cotizacion_retell = lambda *_: (_ for _ in ()).throw(
            AssertionError("El writer de produccion fue invocado")
        )
        with patch.dict(sys.modules, {"services.retell_cotizaciones": stub}):
            modulo = importlib.import_module("services.retell_procesador")
        procesar_pendientes_sofia = modulo.procesar_pendientes_sofia
        historial = {
            "llamadas": [llamada()],
            "paginas": 1,
            "completa": True,
        }
        with patch.dict(os.environ, {"RETELL_SOFIA_AGENT_ID": AGENTE}):
            with patch(
                "services.retell_historial.obtener_historial_sofia_por_periodos",
                return_value=historial,
            ):
                recibido = procesar_pendientes_sofia(
                    AGENTE, simulacion=True,
                    inicio_ms=1000000000000,
                    fin_ms=2000000000001,
                    incluir_cotizaciones_sandbox=True,
                )
                simple = procesar_pendientes_sofia(
                    AGENTE, simulacion=True,
                    inicio_ms=1000000000000,
                    fin_ms=2000000000001,
                )
        self.assertEqual(recibido["estado"], "simulacion")
        self.assertEqual(len(recibido["cotizaciones_sandbox_candidatas"]), 1)
        self.assertNotIn("cotizaciones_sandbox_candidatas", simple)

    def test_configuracion_faltante_bloquea_escrituras(self):
        crm = ZohoFicticio()
        with patch.dict(os.environ, {**ENV_WRITE, "SOFIA_SANDBOX_DEALS_CUTOFF_MS": ""}):
            respuesta = procesar_cotizaciones_cron_sandbox(
                [llamada()], AGENTE, conexion=crm.conexion, http_post=crm.post
            )
        self.assertEqual(respuesta["estado"], "bloqueado")
        self.assertEqual(crm.creados, [])

    def test_fallo_listado_bloquea_nuevo_cliente(self):
        crm = ZohoFicticio()
        get_original = crm.get

        def get_fallido(url, **kwargs):
            if url == BASE + "Accounts":
                return Response(500)
            return get_original(url, **kwargs)

        conexion = crm.conexion
        conexion["http_get"] = get_fallido
        with patch.dict(os.environ, ENV_WRITE):
            respuesta = procesar_cotizaciones_cron_sandbox(
                [llamada()], AGENTE, conexion=conexion, http_post=crm.post
            )
        self.assertEqual(respuesta["estado"], "parcial")
        self.assertEqual(crm.creados, [])

    def test_cache_oauth_reutiliza_token(self):
        import services.sofia.crm_sandbox as oauth
        _TOKEN_CACHE.update({"key": None, "token": None, "hasta": 0})
        org = {"org": [{"type": "sandbox", "domain_name": "sofiaretell", "zgid": "868044837"}]}
        with patch.dict(os.environ, {
            "SOFIA_SANDBOX_CLIENT_ID": "prueba_id",
            "SOFIA_SANDBOX_CLIENT_SECRET": "prueba_secret",
            "SOFIA_SANDBOX_REFRESH_TOKEN": "prueba_refresh",
        }):
            with patch.object(oauth.requests, "post", return_value=Response(200, {"access_token": "token_ficticio", "expires_in": 3600})) as post:
                with patch.object(oauth.requests, "get", return_value=Response(200, org)) as get:
                    a = obtener_token_sandbox()
                    b = obtener_token_sandbox()
        self.assertEqual((a, b), ("token_ficticio", "token_ficticio"))
        self.assertEqual(post.call_count, 1)
        self.assertEqual(get.call_count, 1)


if __name__ == "__main__":
    unittest.main()
