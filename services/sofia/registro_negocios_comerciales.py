"""Escritor comercial de Negocios para Sofía (NO conectado al cron).

Bloqueado por defecto. Requiere aprobación explícita, llamada telefónica
finalizada del agente autorizado, fecha mínima, datos estrictamente válidos,
comprobación de duplicados antes y después de resolver Cuenta/Contacto.
Nunca reintenta un POST cuyo resultado es incierto.
"""

import os
import re
from datetime import date, datetime, timedelta, timezone

import requests

from services.sofia.cotizaciones_sandbox import (
    preparar_borrador_cotizacion_sandbox,
    preparar_registros_cotizacion_sandbox,
)
from services.sofia.crm_produccion import obtener_conexion_produccion
from services.sofia.escritura_clientes_produccion import (
    resolver_clientes_cotizacion_comercial,
)

BASE = "https://www.zohoapis.com/crm/v8"
CALL_RE = re.compile(r"call_[A-Za-z0-9_-]{1,123}\Z")


def _encendido(variable):
    return os.getenv(variable, "false").strip().lower() == "true"


def _bloqueado(motivo, estado="bloqueado"):
    return {"estado": estado, "motivo": motivo}


def _id_valido(valor):
    return isinstance(valor, str) and valor.isascii() and valor.isdecimal()


def _configuracion():
    if not all(_encendido(v) for v in (
        "SOFIA_PROD_COMMERCIAL_ENABLED",
        "SOFIA_PROD_COMMERCIAL_CLIENTS_WRITES_ENABLED",
        "SOFIA_PROD_COMMERCIAL_DEALS_WRITES_ENABLED",
    )):
        return _bloqueado("modo_comercial_apagado", "desactivado")
    if any(_encendido(v) for v in (
        "SOFIA_PROD_CRON_AUTO_ENABLED",
        "SOFIA_PROD_AUTO_TEST_ONLY",
        "SOFIA_PROD_CRON_PILOT_ENABLED",
        "SOFIA_PROD_DEALS_WRITES_ENABLED",
        # Los escritores actuales de Casos/correos aun son de PRUEBA.
        "SOFIA_PROD_CASES_WRITES_ENABLED",
        "SOFIA_PROD_CASES_MAILS_ENABLED",
        "SOFIA_PROD_CASES_MAIL_REAL_RECIPIENTS_ENABLED",
        "SOFIA_SANDBOX_CASES_WRITES_ENABLED",
        "SOFIA_SANDBOX_DEALS_WRITES_ENABLED",
    )):
        return _bloqueado("modo_prueba_incompatible")
    fecha = os.getenv("SOFIA_PROD_COMMERCIAL_START_MS", "").strip()
    if not re.fullmatch(r"[0-9]{13}", fecha):
        return _bloqueado("fecha_inicio_faltante")
    ahora = int(datetime.now(timezone.utc).timestamp() * 1000)
    inicio = int(fecha)
    if inicio < 1795737600000 or inicio > ahora + 300000:
        return _bloqueado("fecha_inicio_fuera_de_rango")
    cierre = os.getenv("SOFIA_PROD_DEALS_CLOSE_DAYS", "7").strip()
    if not cierre.isdecimal() or not 1 <= int(cierre) <= 90:
        return _bloqueado("dias_cierre_invalidos")
    return {"estado": "autorizado", "inicio": inicio, "ahora": ahora, "dias": int(cierre)}


def _buscar_negocio_unico(conexion, token, call_id):
    """Busca el Call ID exacto sin recorrer todo CRM.

    El preflight del cron exige un campo Retell_Call_ID unico. En caso de
    indexacion demorada, Zoho impide crear el mismo valor por segunda vez.
    Si el resultado no es concluyente, se bloquea en lugar de escribir.
    """
    if not isinstance(call_id, str) or CALL_RE.fullmatch(call_id) is None:
        return _bloqueado("identificador_invalido")
    try:
        r = conexion["http_get"](
            BASE + "/Deals/search",
            headers={"Authorization": "Zoho-oauthtoken " + token},
            params={
                "criteria": "(Retell_Call_ID:equals:" + call_id + ")",
                "fields": "id,Retell_Call_ID",
                "per_page": 200,
            },
            timeout=20,
            allow_redirects=False,
        )
        if r.status_code == 204:
            return {"estado": "no_encontrado"}
        if r.status_code != 200:
            return _bloqueado("busqueda_zoho_inconclusa")
        body = r.json()
        filas = body.get("data") if isinstance(body, dict) else None
        info = body.get("info") if isinstance(body, dict) else None
        if (not isinstance(filas, list) or not filas
                or not isinstance(info, dict)
                or info.get("more_records") is not False):
            return _bloqueado("busqueda_zoho_incompleta")
        coincidencias = set()
        for fila in filas:
            if not isinstance(fila, dict):
                return _bloqueado("fila_invalida")
            if fila.get("Retell_Call_ID") != call_id:
                continue  # La busqueda de Zoho puede devolver coincidencias parciales.
            ident = str(fila.get("id") or "")
            if not _id_valido(ident):
                return _bloqueado("id_invalido")
            coincidencias.add(ident)
        if len(coincidencias) > 1:
            return _bloqueado("deals_duplicados")
        if len(coincidencias) == 1:
            return {"estado": "ya_registrado", "deal_id": next(iter(coincidencias))}
        # Evitar interpretar una respuesta 200 inexacta como ausencia segura.
        return _bloqueado("busqueda_sin_coincidencia_exacta")
    except Exception:
        return _bloqueado("consulta_inconclusa")


def registrar_negocio_comercial(llamada, *, autorizar=False, conexion=None, http_post=None):
    """Crea un solo Negocio vinculado, luego de resolver Cuenta y Contacto.

    Este módulo no debe conectarse al cron hasta verificar permisos/metadata,
    concurrencia y campos obligatorios específicos de la organización.
    """
    if autorizar is not True:
        return _bloqueado("autorizacion_explicita_requerida", "desactivado")
    cfg = _configuracion()
    if cfg["estado"] != "autorizado":
        return cfg
    agente = os.getenv("RETELL_SOFIA_AGENT_ID", "").strip()
    if not isinstance(llamada, dict) or not agente:
        return _bloqueado("llamada_o_agente_invalido")
    call_id = llamada.get("call_id")
    timestamp = llamada.get("start_timestamp")
    if (not isinstance(call_id, str) or CALL_RE.fullmatch(call_id) is None
            or type(timestamp) is not int or not cfg["inicio"] <= timestamp <= cfg["ahora"] + 300000
            or llamada.get("agent_id") != agente or llamada.get("call_type") != "phone_call"
            or llamada.get("call_status") != "ended"):
        return _bloqueado("llamada_no_autorizada")
    analisis = llamada.get("call_analysis")
    datos = analisis.get("custom_analysis_data") if isinstance(analisis, dict) else None
    if not isinstance(datos, dict) or str(datos.get("tipo_solicitud") or "").lower().strip() != "cotizacion":
        return _bloqueado("no_es_cotizacion")
    # Solo las pruebas explícitamente autorizadas pueden omitir el dígito
    # verificador. Se siguen exigiendo formato, productos y datos de contacto.
    borrador = preparar_borrador_cotizacion_sandbox(
        llamada,
        permitir_rut_ficticio=_encendido("SOFIA_PROD_COMMERCIAL_RUT_SIN_DV_ENABLED"),
    )
    if borrador.get("estado") != "borrador_preparado" or borrador.get("call_id") != call_id:
        return _bloqueado("datos_por_revisar")
    if conexion is None:
        conexion = obtener_conexion_produccion()
    if (not isinstance(conexion, dict) or conexion.get("base") != "https://www.zohoapis.com"
            or not callable(conexion.get("http_get")) or not callable(conexion.get("obtener_token"))):
        return _bloqueado("conexion_invalida")
    if http_post is None:
        http_post = requests.post
    if not callable(http_post):
        return _bloqueado("post_no_disponible")
    try:
        token = conexion["obtener_token"]()
        if not isinstance(token, str) or not token:
            return _bloqueado("token_no_disponible")
    except Exception:
        return _bloqueado("token_no_disponible")
    conex_token = dict(conexion)
    conex_token["obtener_token"] = lambda: token
    previo = _buscar_negocio_unico(conex_token, token, call_id)
    if previo["estado"] != "no_encontrado":
        return previo

    clientes = resolver_clientes_cotizacion_comercial(
        borrador, autorizar=True, conexion=conex_token, http_post=http_post,
    )
    if clientes.get("estado") != "resueltos":
        return clientes
    cuenta_id = clientes.get("account_id")
    contacto_id = clientes.get("contact_id")
    if not _id_valido(cuenta_id) or not _id_valido(contacto_id):
        return _bloqueado("clientes_inconsistentes")
    preparado = preparar_registros_cotizacion_sandbox(
        borrador, account_id=cuenta_id, contact_id=contacto_id,
    )
    if preparado.get("estado") != "registros_preparados":
        return _bloqueado("negocio_invalido")
    negocio = dict(preparado["negocio"])
    if (str(negocio.get("Retell_Call_ID") or "") != call_id
            or str((negocio.get("Account_Name") or {}).get("id") or "") != cuenta_id
            or str((negocio.get("Contact_Name") or {}).get("id") or "") != contacto_id):
        return _bloqueado("vinculos_invalidos")
    negocio["Closing_Date"] = (date.today() + timedelta(days=cfg["dias"])).isoformat()

    # Segundo barrido antes del único POST a Deals. No garantiza protección
    # entre procesos: para operar en real se requiere serialización/unique key.
    previo = _buscar_negocio_unico(conex_token, token, call_id)
    if previo["estado"] != "no_encontrado":
        return previo
    try:
        respuesta = http_post(
            BASE + "/Deals",
            headers={"Authorization": "Zoho-oauthtoken " + token,
                     "Content-Type": "application/json"},
            json={"data": [negocio], "trigger": []}, timeout=20,
            allow_redirects=False,
        )
        body = respuesta.json()
        filas = body.get("data") if isinstance(body, dict) else None
        fila = filas[0] if isinstance(filas, list) and len(filas) == 1 and isinstance(filas[0], dict) else None
        if respuesta.status_code in (200, 201) and isinstance(fila, dict) and fila.get("code") == "SUCCESS" and fila.get("status") == "success":
            deal_id = str((fila.get("details") or {}).get("id") or "")
            if _id_valido(deal_id):
                return {"estado": "creado", "deal_id": deal_id, "account_id": cuenta_id, "contact_id": contacto_id}
        if respuesta.status_code in (400, 401, 403, 422):
            return _bloqueado("rechazo_confirmado_zoho", "rechazado")
        return _bloqueado("resultado_no_confirmado", "resultado_incierto")
    except Exception:
        return _bloqueado("resultado_no_confirmado", "resultado_incierto")
