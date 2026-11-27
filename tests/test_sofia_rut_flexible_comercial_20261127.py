"""RUT con DV incorrecto solo mediante permiso explícito; ninguna petición real."""

from datetime import datetime, timezone
from unittest.mock import Mock, patch

from services.retell_recuperacion import clasificar_llamada_recuperacion
from services.sofia.registro_negocios_comerciales import registrar_negocio_comercial
from services.sofia.escritura_clientes_produccion import resolver_clientes_cotizacion_comercial


AHORA = int(datetime.now(timezone.utc).timestamp() * 1000)
CALL = {
    "call_id": "call_rut_flexible_prueba",
    "agent_id": "agent_sofia_prueba",
    "call_type": "phone_call",
    "call_status": "ended",
    "start_timestamp": AHORA - 10_000,
    "call_analysis": {"custom_analysis_data": {
        "tipo_solicitud": "cotizacion",
        "empresa": "Empresa Prueba",
        "rut_cliente": "76.111.111-1",  # Forma válida, DV deliberadamente incorrecto
        "nombre_cliente": "Ana Ejemplo",
        "email_cliente": "ana@example.com",
        "telefono_cliente": "+56912345678",
        "direccion_entrega": "Santiago",
        "productos_solicitados": "Producto 1 | Descripcion: Computador | Marca: HP | Cantidad: 2",
    }},
}

ENV = {
    "SOFIA_PROD_COMMERCIAL_ENABLED": "true",
    "SOFIA_PROD_COMMERCIAL_CLIENTS_WRITES_ENABLED": "true",
    "SOFIA_PROD_COMMERCIAL_DEALS_WRITES_ENABLED": "true",
    "SOFIA_PROD_COMMERCIAL_START_MS": str(AHORA - 60_000),
    "RETELL_SOFIA_AGENT_ID": "agent_sofia_prueba",
}


def test_clasificador_no_acepta_rut_incorrecto_por_defecto():
    r = clasificar_llamada_recuperacion(CALL, "agent_sofia_prueba")
    assert r["estado"] == "revision"
    assert "rut_cliente (RUT invalido)" in r["faltantes"]


def test_clasificador_acepta_rut_con_formato_sin_dv():
    r = clasificar_llamada_recuperacion(CALL, "agent_sofia_prueba", permitir_rut_ficticio=True)
    assert r["estado"] == "candidata"


def test_escritor_deal_acepta_rut_sin_dv_solo_en_modo_explicito(monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("SOFIA_PROD_COMMERCIAL_RUT_SIN_DV_ENABLED", "true")
    conn = {
        "base": "https://www.zohoapis.com",
        "obtener_token": lambda: "test_token",
        "http_get": Mock(return_value=Mock(status_code=204)),
    }
    with patch(
        "services.sofia.registro_negocios_comerciales.resolver_clientes_cotizacion_comercial",
        return_value={"estado": "bloqueado", "motivo": "prueba_aislada"},
    ) as resolver:
        r = registrar_negocio_comercial(
            CALL, autorizar=True, conexion=conn, http_post=Mock()
        )
    assert r["motivo"] == "prueba_aislada"
    resolver.assert_called_once()


def test_resolver_cliente_pasa_validacion_rut_sin_dv_pero_sin_escribir(monkeypatch):
    monkeypatch.setenv("SOFIA_PROD_COMMERCIAL_ENABLED", "true")
    monkeypatch.setenv("SOFIA_PROD_COMMERCIAL_CLIENTS_WRITES_ENABLED", "true")
    monkeypatch.setenv("SOFIA_PROD_COMMERCIAL_RUT_SIN_DV_ENABLED", "true")
    borrador = {
        "estado": "borrador_preparado",
        "call_id": "call_rut_flexible_prueba",
        "cuenta": {"empresa": "Empresa Prueba", "rut": "76.111.111-1"},
        "contacto": {"nombre": "Ana Ejemplo", "correo": "ana@example.com", "telefono": "+56912345678"},
        "negocio": {"etapa": "Pendiente por cotizar", "direccion_entrega": "Santiago"},
        "productos": [{"descripcion": "Computador", "marca": "HP", "cantidad": "2"}],
    }
    with patch(
        "services.sofia.escritura_clientes_produccion.buscar_cuenta_por_rut",
        return_value={"estado": "bloqueado", "motivo": "prueba_aislada"},
    ) as buscar:
        r = resolver_clientes_cotizacion_comercial(
            borrador, autorizar=True,
            conexion={"base":"https://www.zohoapis.com", "obtener_token":lambda: "test_token", "http_get":Mock()},
            http_post=Mock(),
        )
    assert r["motivo"] == "cuenta_no_verificable"
    buscar.assert_called_once()
