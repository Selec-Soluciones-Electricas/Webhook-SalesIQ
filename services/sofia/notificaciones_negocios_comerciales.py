"""Notificación de Negocios comerciales creados por Sofía.

No usa reintentos: se invoca únicamente después de una creación confirmada,
nunca cuando el Negocio ya existe. Protege destinatarios y contenido.
"""

import os
import re
from html import escape
from urllib.parse import urlparse

import requests

from services.sofia.crm_produccion import obtener_conexion_produccion

BASE = "https://www.zohoapis.com/crm/v8"
ORG_UI = "org706345205"
CALL_RE = re.compile(r"call_[A-Za-z0-9_-]{1,123}\Z")
EMAIL_RE = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\Z")


def _activo(nombre):
    return os.getenv(nombre, "false").strip().lower() == "true"


def _correo(valor):
    return isinstance(valor, str) and EMAIL_RE.fullmatch(valor.strip()) is not None


def _bloquear(motivo, estado="bloqueado"):
    return {"estado": estado, "motivo": motivo}


def _destinatarios():
    """Fail-closed: el modo real requiere dos flags y una lista explícita."""
    if not _activo("SOFIA_PROD_COMMERCIAL_DEALS_MAIL_REAL_RECIPIENTS_ENABLED"):
        email = os.getenv("SOFIA_PROD_COMMERCIAL_DEALS_MAIL_TEST_TO", "").strip()
        if email.lower() != "ederth@selec.cl":
            return None, True
        return [{"email": email, "user_name": "Prueba Sofía"}], True

    if not _activo("SOFIA_PROD_COMMERCIAL_DEALS_MAIL_REAL_RECIPIENTS_APPROVED"):
        return None, False
    raw = os.getenv("SOFIA_PROD_COMMERCIAL_DEALS_MAIL_TO", "")
    direcciones = [e.strip() for e in raw.split(",")]
    if not direcciones or len(direcciones) > 6 or any(not _correo(e) for e in direcciones):
        return None, False
    if len(set(e.lower() for e in direcciones)) != len(direcciones):
        return None, False
    return [{"email": e} for e in direcciones], False


def _enlace_retell(call_id):
    plantilla = os.getenv("SOFIA_RETELL_CALL_URL_TEMPLATE", "").strip()
    if plantilla.count("{call_id}") != 1:
        return None
    enlace = plantilla.replace("{call_id}", call_id)
    destino = urlparse(enlace)
    dominio = (destino.hostname or "").lower()
    if destino.scheme != "https" or destino.username or destino.password:
        return None
    if dominio != "retellai.com" and not dominio.endswith(".retellai.com"):
        return None
    return enlace


def notificar_negocio_comercial_creado(decision, llamada, *, conexion=None, http_post=None):
    """Solo un POST a send_mail tras verificar el Negocio mediante GET.

    Nunca vuelve a enviar por `ya_registrado`. Si el resultado es incierto,
    el cron NO reintenta la notificación automáticamente.
    """
    if not _activo("SOFIA_PROD_COMMERCIAL_DEALS_MAILS_ENABLED"):
        return {"estado": "desactivado"}
    if not isinstance(decision, dict) or decision.get("estado") != "creado":
        return _bloquear("negocio_no_recien_creado")
    if not isinstance(llamada, dict):
        return _bloquear("llamada_invalida")
    call_id = llamada.get("call_id")
    deal_id = str(decision.get("deal_id") or "")
    if (not isinstance(call_id, str) or CALL_RE.fullmatch(call_id) is None
            or not deal_id.isascii() or not deal_id.isdecimal()):
        return _bloquear("identificador_invalido")
    destinatarios, prueba = _destinatarios()
    if not destinatarios:
        return _bloquear("destinatarios_no_autorizados")
    remitente = os.getenv("SOFIA_PROD_COMMERCIAL_DEALS_MAIL_FROM", "").strip()
    if not _correo(remitente):
        return _bloquear("remitente_no_configurado")
    enlace_retell = _enlace_retell(call_id)
    if not enlace_retell:
        return _bloquear("enlace_retell_no_configurado")

    try:
        conn = conexion if conexion is not None else obtener_conexion_produccion()
        if (not isinstance(conn, dict) or conn.get("base") != "https://www.zohoapis.com"
                or not callable(conn.get("obtener_token"))
                or not callable(conn.get("http_get"))):
            return _bloquear("conexion_invalida")
        token = conn["obtener_token"]()
        if not isinstance(token, str) or not token:
            return _bloquear("token_no_disponible")
        headers = {"Authorization": "Zoho-oauthtoken " + token}
        r = conn["http_get"](
            BASE + "/Deals/" + deal_id,
            headers=headers,
            params={"fields": "id,Deal_Name,Description,Retell_Call_ID,Account_Name,Contact_Name"},
            timeout=20,
            allow_redirects=False,
        )
        if r.status_code != 200:
            return _bloquear("negocio_no_verificable")
        cuerpo = r.json()
        registros = cuerpo.get("data") if isinstance(cuerpo, dict) else None
        if not isinstance(registros, list) or len(registros) != 1 or not isinstance(registros[0], dict):
            return _bloquear("negocio_no_verificable")
        negocio = registros[0]
        if str(negocio.get("id") or "") != deal_id or negocio.get("Retell_Call_ID") != call_id:
            return _bloquear("negocio_inconsistente")
        for campo, esperado in (("Account_Name", "account_id"), ("Contact_Name", "contact_id")):
            valor = negocio.get(campo)
            if not isinstance(valor, dict) or str(valor.get("id") or "") != str(decision.get(esperado) or ""):
                return _bloquear("vinculos_no_verificables")
        nombre = negocio.get("Deal_Name")
        descripcion = negocio.get("Description")
        if not isinstance(nombre, str) or not nombre.strip() or not isinstance(descripcion, str):
            return _bloquear("descripcion_invalida")

        enlace_crm = "https://crm.zoho.com/crm/" + ORG_UI + "/tab/Deals/" + deal_id
        asunto = ("[PRUEBA CORREO SOFIA] " if prueba else "[SOFIA] ") + "Nuevo Negocio de cotización"
        contenido = (
            "<p>Se creó un nuevo Negocio de cotización atendido por Sofía.</p>"
            "<p><b>Negocio:</b> " + escape(nombre[:300]) + "<br>"
            '<b>Zoho CRM:</b> <a href="' + escape(enlace_crm, quote=True) + '">Abrir Negocio</a><br>'
            '<b>Llamada Retell:</b> <a href="' + escape(enlace_retell, quote=True) + '">Abrir llamada</a></p>'
            "<p><b>Datos y productos de la solicitud:</b></p>"
            '<pre style="font-family:Arial,sans-serif;white-space:pre-wrap">'
            + escape(descripcion[:15000]) + "</pre>"
            "<p>Mensaje automático del sistema Sofía — SELEC.</p>"
        )
        payload = {"data": [{
            "from": {"email": remitente, "user_name": "Sofía - SELEC"},
            "to": destinatarios, "subject": asunto,
            "content": contenido, "mail_format": "html",
        }]}
        enviar = http_post if http_post is not None else requests.post
        respuesta = enviar(
            BASE + "/Deals/" + deal_id + "/actions/send_mail",
            headers={**headers, "Content-Type": "application/json"},
            json=payload, timeout=20, allow_redirects=False,
        )
        if respuesta.status_code not in (200, 201, 202):
            return _bloquear("zoho_rechazo_envio")
        dato = respuesta.json()
        filas = dato.get("data") if isinstance(dato, dict) else None
        if (isinstance(filas, list) and len(filas) == 1
                and isinstance(filas[0], dict)
                and filas[0].get("code") == "SUCCESS"
                and filas[0].get("status") == "success"):
            return {"estado": "enviado"}
        return _bloquear("envio_no_confirmado", "resultado_incierto")
    except Exception:
        return _bloquear("excepcion_envio", "resultado_incierto")
