"""Avisos de nuevos Casos de Sofia, desactivados por defecto.

Solo se intenta enviar después de una creación confirmada, una vez por Call ID.
Los Casos que ya existían jamás disparan el aviso automático. No reintenta.
Durante el piloto, los Casos marcados como prueba se envían a un buzón de prueba.
"""
import os
import re
from html import escape
from urllib.parse import urlparse

import requests

from services.sofia.crm_produccion import obtener_conexion_produccion
from services.sofia.autorizacion_produccion import llamada_autorizada

BASE = "https://www.zohoapis.com/crm/v8"
ORG_UI = "org706345205"


def _activo(nombre):
    return os.getenv(nombre, "false").strip().lower() == "true"


def _email(valor):
    return isinstance(valor, str) and re.fullmatch(
        r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        valor.strip(),
    ) is not None


def _url_retell(call_id):
    plantilla = os.getenv("SOFIA_RETELL_CALL_URL_TEMPLATE", "").strip()
    if plantilla.count("{call_id}") != 1:
        return None
    url = plantilla.replace("{call_id}", call_id)
    destino = urlparse(url)
    dominio = (destino.hostname or "").lower()
    if destino.scheme != "https" or not (
        dominio == "retellai.com" or dominio.endswith(".retellai.com")
    ) or destino.username or destino.password:
        return None
    return url


def _destinatarios(tipo, *, prueba):
    if prueba and not _activo("SOFIA_PROD_CASES_MAIL_REAL_RECIPIENTS_ENABLED"):
        email = os.getenv("SOFIA_PROD_CASES_MAIL_TEST_TO", "").strip()
        if not _email(email):
            return None
        return [{"email": email, "user_name": "Prueba Sofia"}]

    nombres = (
        ("Deivys", "Carolina", "Luis")
        if tipo == "postventa"
        else ("Patricio", "Carolina", "Luis")
    )
    resultado = []
    vistos = set()
    for nombre in nombres:
        email = os.getenv("SOFIA_MAIL_" + nombre.upper(), "").strip()
        if not _email(email):
            return None
        if email.lower() in vistos:
            return None
        vistos.add(email.lower())
        resultado.append({"email": email, "user_name": nombre})
    return resultado


def notificar_caso_creado(decision, clasificacion, *, solo_diagnostico=False, envio_manual_prueba=False):
    """Intenta un envío una sola vez, exclusivamente tras una creación confirmada.

    No registra datos del cliente en logs y no realiza un segundo POST si el
    resultado del envío es desconocido. Devuelve estados seguros para logging.
    """
    def bloquear(motivo, estado="bloqueado"):
        return {"estado": estado, "motivo": motivo}

    if envio_manual_prueba:
        # Unicamente la ruta manual protegida puede solicitar este modo.
        if not _activo("SOFIA_PROD_CASES_MAIL_MANUAL_TEST_ENABLED"):
            return bloquear("prueba_manual_desactivada")
        if (_activo("SOFIA_PROD_CASES_MAILS_ENABLED")
                or _activo("SOFIA_PROD_CASES_WRITES_ENABLED")
                or _activo("SOFIA_PROD_CASES_MAIL_REAL_RECIPIENTS_ENABLED")):
            return bloquear("interruptores_no_seguros")
        if os.getenv("SOFIA_PROD_CASES_MAIL_TEST_TO", "").strip().lower() != "ederth@selec.cl":
            return bloquear("destinatario_prueba_incorrecto")
    elif not solo_diagnostico and not _activo("SOFIA_PROD_CASES_MAILS_ENABLED"):
        return {"estado": "desactivado"}
    if not isinstance(decision, dict) or decision.get("estado") != "creado":
        return bloquear("caso_no_recien_creado")
    if not isinstance(clasificacion, dict):
        return bloquear("clasificacion_invalida")
    tipo = clasificacion.get("tipo_solicitud")
    if tipo not in ("postventa", "consulta"):
        return bloquear("tipo_invalido")
    call_id = clasificacion.get("call_id")
    case_id = str(decision.get("case_id") or "")
    if (
        not isinstance(call_id, str)
        or re.fullmatch(r"call_[A-Za-z0-9_-]{1,123}", call_id) is None
        or not case_id.isascii()
        or not case_id.isdecimal()
        or not llamada_autorizada("Cases", call_id, clasificacion.get("start_timestamp"))
    ):
        return bloquear("identificador_no_autorizado")
    remitente = os.getenv("SOFIA_PROD_CASES_MAIL_FROM", "").strip()
    if not _email(remitente):
        return bloquear("remitente_no_configurado")
    retell_url = _url_retell(call_id)
    if not retell_url:
        return bloquear("enlace_retell_no_configurado")

    try:
        conexion = obtener_conexion_produccion()
        token = conexion["obtener_token"]()
        headers = {"Authorization": "Zoho-oauthtoken " + token}
        lectura = conexion["http_get"](
            BASE + "/Cases/" + case_id,
            headers=headers,
            params={
                "fields": "id,Subject,Description,Case_Number,ID_de_llamada_Retell,Registro_de_prueba_Sof_a"
            },
            timeout=20,
            allow_redirects=False,
        )
        if lectura.status_code != 200:
            return bloquear("caso_no_verificable")
        datos = lectura.json().get("data")
        if not isinstance(datos, list) or len(datos) != 1 or not isinstance(datos[0], dict):
            return bloquear("caso_no_verificable")
        caso = datos[0]
        if str(caso.get("id") or "") != case_id or caso.get("ID_de_llamada_Retell") != call_id:
            return bloquear("caso_inconsistente")
        # Mientras los escritores crean exclusivamente registros de prueba,
        # no enviar mensajes desde Casos reales de otro origen.
        if caso.get("Registro_de_prueba_Sof_a") is not True:
            return bloquear("no_es_registro_prueba")
        descripcion = caso.get("Description")
        if not isinstance(descripcion, str) or not descripcion.startswith("[PRUEBA SOFIA]"):
            return bloquear("marca_descripcion_ausente")
        asunto = str(caso.get("Subject") or "").strip()
        if not asunto.startswith("SOFIA_" + tipo.upper() + "_"):
            return bloquear("asunto_inconsistente")
        destinatarios = _destinatarios(tipo, prueba=True)
        if not destinatarios:
            return bloquear("destinatarios_no_configurados")

        url_caso = f"https://crm.zoho.com/crm/{ORG_UI}/tab/Cases/{case_id}"
        descripcion_html = escape(descripcion[:15000])
        numero_crm = str(caso.get("Case_Number") or "").strip()
        # Referencia CORTA visible; no cambia el ID real usado por CRM ni por los enlaces.
        numero_visible = (numero_crm if numero_crm and not (numero_crm.isdecimal() and len(numero_crm) > 12)
                          else "S-" + case_id[-8:])
        numero = escape(numero_visible)
        contenido = (
            "<p>Se registró un nuevo Caso de Sofía para gestión.</p>"
            f"<p><b>Tipo:</b> {escape(tipo.title())}<br>"
            f"<b>Referencia de Caso:</b> {numero}<br>"
            f'<b>Zoho CRM:</b> <a href="{escape(url_caso, quote=True)}">Abrir Caso</a><br>'
            f'<b>Llamada Retell:</b> <a href="{escape(retell_url, quote=True)}">Abrir llamada</a></p>'
            "<p><b>Descripción del Caso:</b></p>"
            f'<pre style="font-family:Arial,sans-serif;white-space:pre-wrap">{descripcion_html}</pre>'
            "<p>Mensaje automático del sistema Sofía — SELEC.</p>"
        )
        payload = {"data": [{
            "from": {
                "email": remitente,
                "user_name": os.getenv("SOFIA_PROD_CASES_MAIL_FROM_NAME", "Sofia - SELEC"),
            },
            "to": destinatarios,
            "subject": "[PRUEBA SOFIA] Nuevo Caso de " + tipo + " #" + numero_visible,
            "content": contenido,
            "mail_format": "html",
        }]}
        if solo_diagnostico:
            return {
                "estado": "listo_para_enviar",
                "motivo": "validaciones_superadas",
            }
        # SOLO un POST, sin reintentos; si expira, el resultado es incierto.
        respuesta = requests.post(
            BASE + "/Cases/" + case_id + "/actions/send_mail",
            headers={**headers, "Content-Type": "application/json"},
            json=payload,
            timeout=20,
            allow_redirects=False,
        )
        if respuesta.status_code not in (200, 201, 202):
            codigo = "DESCONOCIDO"

            try:
                cuerpo_error = respuesta.json()

                if isinstance(cuerpo_error, dict):
                    filas_error = cuerpo_error.get("data", [])

                    if isinstance(filas_error, list) and filas_error:
                        primer_error = filas_error[0]

                        if isinstance(primer_error, dict):
                            codigo = str(
                                primer_error.get("code") or "DESCONOCIDO"
                            )

                    elif isinstance(cuerpo_error.get("code"), str):
                        codigo = cuerpo_error["code"]

            except (ValueError, TypeError):
                pass

            if codigo not in (
                "INVALID_OAUTHSCOPE",
                "OAUTH_SCOPE_MISMATCH",
                "NO_PERMISSION",
                "NOT_ALLOWED",
                "INVALID_DATA",
                "MANDATORY_NOT_FOUND",
                "LIMIT_EXCEEDED",
            ):
                codigo = "OTRO_ERROR"

            return bloquear("zoho_rechazo_" + codigo)
        cuerpo = respuesta.json()
        filas = cuerpo.get("data") if isinstance(cuerpo, dict) else None
        if (
            isinstance(filas, list) and len(filas) == 1
            and isinstance(filas[0], dict)
            and filas[0].get("code") == "SUCCESS"
            and filas[0].get("status") == "success"
        ):
            return {"estado": "enviado"}
        return bloquear("envio_no_confirmado", "resultado_incierto")
    except Exception:
        return bloquear("excepcion_envio_no_confirmado", "resultado_incierto")
