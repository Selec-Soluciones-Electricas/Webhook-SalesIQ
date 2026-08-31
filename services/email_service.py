import os
import requests

from services.zoho_service import get_access_token


# =========================================================
# CONFIGURACION
# =========================================================

SENDER_USER_ID = os.environ.get(
    "SENDER_USER_ID",
    ""
)

SENDER_USER_EMAIL = os.environ.get(
    "SENDER_USER_EMAIL",
    ""
)

SENDER_USER_NAME = os.environ.get(
    "SENDER_USER_NAME",
    "Bot Selec"
)

# Destinatario fijo para correos generales
# como primer contacto y solicitudes incompletas.
MAIL_TO_FIXED = "Joaquin@selec.cl"
MAIL_TO_NAME = "Joaquin Gonzalez"

CC_GERENCIA_EMAIL = ""
CC_ELIAN_EMAIL = "elian@selec.cl"

CRM_ORG_UI = "org706345205"

CRM_BASE = (
    "https://www.zohoapis.com/crm/v2.1"
)


# =========================================================
# UTILIDADES
# =========================================================

def build_mail_recipient(
    email: str,
    name: str = ""
) -> dict:
    """
    Construye un destinatario con el formato
    esperado por Zoho CRM.
    """

    recipient = {
        "email": str(email).strip()
    }

    if str(name or "").strip():
        recipient["user_name"] = str(name).strip()

    return recipient


def construir_link_chat(payload: dict) -> str:
    """
    Construye el enlace directo al chat de SalesIQ
    utilizando la plantilla configurada en variables
    de entorno.
    """

    visitor = payload.get("visitor") or {}

    conversation_id = str(
        visitor.get("active_conversation_id") or ""
    ).strip()

    if not conversation_id:
        return ""

    template = os.environ.get(
        "SALESIQ_CHAT_URL_TEMPLATE",
        ""
    ).strip()

    if not template:
        return ""

    return template.replace(
        "{conversation_id}",
        conversation_id
    )


def construir_cc() -> list:
    """
    Construye la lista de destinatarios en copia.

    Solo agrega correos que realmente estén configurados,
    evitando enviar destinatarios con email vacío a Zoho.
    """

    destinatarios = []

    if str(
        CC_ELIAN_EMAIL or ""
    ).strip():

        destinatarios.append(
            build_mail_recipient(
                CC_ELIAN_EMAIL,
                "Elian Barra"
            )
        )

    if str(
        CC_GERENCIA_EMAIL or ""
    ).strip():

        destinatarios.append(
            build_mail_recipient(
                CC_GERENCIA_EMAIL,
                ""
            )
        )

    return destinatarios


def construir_remitente() -> dict:
    """
    Construye el remitente utilizando las variables
    configuradas en Railway o en el entorno local.
    """

    return {
        "id": SENDER_USER_ID,
        "user_name": SENDER_USER_NAME,
        "email": SENDER_USER_EMAIL,
    }


# =========================================================
# CORREO DE NOTIFICACION DE DEAL
# =========================================================

def enviar_correo_owner(
    owner: dict,
    deal_id: str,
    deal_name: str,
    campos: dict,
):
    """
    Envía un correo notificando la creación de un nuevo
    Deal desde el chatbot de WhatsApp.
    """

    # =====================================================
    # DESTINATARIO = OWNER REAL DEL DEAL
    # =====================================================

    to_email = str(
        owner.get("email")
        or ""
    ).strip()

    to_name = str(
        owner.get("nombre")
        or ""
    ).strip()

       # =====================================================
    # VALIDAR OWNER DEL DEAL
    # =====================================================

    if not to_email:

        print(
            "[enviar_correo_owner] "
            "El owner del Deal no tiene correo configurado. "
            "No se enviará la notificación."
        )

        return None

    if not to_name:
        to_name = "Ejecutivo Selec"

    access_token = get_access_token()

    if not access_token:
        print(
            "[enviar_correo_owner] "
            "No se pudo obtener access token; "
            "no se envía correo."
        )
        return None

    url = (
        f"{CRM_BASE}/Deals/"
        f"{deal_id}/actions/send_mail"
    )

    headers = {
        "Authorization": (
            f"Zoho-oauthtoken {access_token}"
        ),
        "Content-Type": "application/json",
    }

    subject = (
        "Nuevo Deal asignado desde WhatsApp: "
        f"{deal_name}"
    )

    deal_link = (
        f"https://crm.zoho.com/crm/"
        f"{CRM_ORG_UI}/tab/Potentials/"
        f"{deal_id}"
    )

    content = f"""
<p>Hola {to_name},</p>

<p>
Se ha creado un nuevo Deal asignado desde
el chatbot de WhatsApp.
</p>

<p>
<b>Número de Chat (SalesIQ):</b>
{campos.get("num_chat") or "(sin número de chat)"}
</p>

<p>
<b>Deal:</b>
{deal_name}
</p>

<p>
<b>Link del Deal en Zoho CRM:</b>
<a href="{deal_link}">
Abrir Deal
</a>
</p>

<hr>

<p>
<b>Empresa:</b>
{campos.get("empresa") or "(sin empresa)"}
</p>

<p>
<b>RUT:</b>
{campos.get("rut") or "(sin RUT)"}
</p>

<p>
<b>Contacto:</b>
{campos.get("contacto") or "(sin contacto)"}
</p>

<p>
<b>Correo:</b>
{campos.get("correo") or "(sin correo)"}
</p>

<p>
<b>Teléfono:</b>
{campos.get("telefono") or "(sin teléfono)"}
</p>

<p>
<b>Número de parte / descripción:</b>
{campos.get("num_parte") or "(sin descripción)"}
</p>

<p>
<b>Marca:</b>
{campos.get("marca") or "(sin marca)"}
</p>

<p>
<b>Cantidad:</b>
{campos.get("cantidad") or "(sin cantidad)"}
</p>

<p>
<b>Dirección de entrega:</b>
{campos.get("direccion_entrega") or "(sin dirección)"}
</p>

<hr>

<p>
Saludos,<br>
Bot WhatsApp Selec
</p>
"""

    payload = {
        "data": [
            {
                "from": construir_remitente(),

                "to": [
    build_mail_recipient(
        to_email,
        to_name
    )
],

                "cc": construir_cc(),

                "subject": subject,

                "content": content,

                "mail_format": "html",
            }
        ]
    }

    try:
        print(
            "[enviar_correo_owner] "
            "Enviando correo..."
        )

        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=10,
        )

        print(
            "=== Respuesta Zoho CRM "
            "send_mail owner ==="
        )

        print(
            "Status:",
            response.status_code
        )

        print(
            "Respuesta:",
            response.text
        )

        return response

    except Exception as error:
        print(
            "ERROR enviando correo "
            "de notificación:",
            error
        )

        return None


# =========================================================
# CORREO DE SOLICITUD DE COTIZACION INCOMPLETA
# =========================================================

def enviar_correo_solicitud_incompleta(
    data: dict,
    faltantes: list,
    ultimo_mensaje: str = "",
):
    """
    Envía una alerta a los ejecutivos cuando una solicitud
    de cotización no puede completarse correctamente por
    campos faltantes o inválidos.
    """

    access_token = get_access_token()

    if not access_token:
        print(
            "[enviar_correo_solicitud_incompleta] "
            "No se pudo obtener access token; "
            "no se envía correo."
        )
        return None

    url = (
        f"{CRM_BASE}/Deals/actions/send_mail"
    )

    headers = {
        "Authorization": (
            f"Zoho-oauthtoken {access_token}"
        ),
        "Content-Type": "application/json",
    }

    empresa = str(
        data.get("empresa") or ""
    ).strip()

    identificador = (
        empresa
        or str(data.get("contacto") or "").strip()
        or str(data.get("correo") or "").strip()
        or "Cliente sin identificar"
    )

    subject = (
        "⚠️ Solicitud de cotización no completada: "
        f"{identificador}"
    )

    def valor(campo: str, defecto: str) -> str:
        value = str(data.get(campo) or "").strip()
        return value or defecto

    faltantes_html = ""

    if faltantes:
        faltantes_html = (
            "<ul>"
            + "".join(
                f"<li>{item}</li>"
                for item in faltantes
            )
            + "</ul>"
        )
    else:
        faltantes_html = "<p>(No especificado)</p>"

    mensaje_html = (
        str(ultimo_mensaje or "").strip()
        or "(sin mensaje disponible)"
    )

    content = f"""
<p>Estimados,</p>

<p>
Se informa que una <b>solicitud de cotización no pudo ser
completada correctamente</b> mediante el chatbot de WhatsApp.
</p>

<p>
Por favor, revisar la conversación y contactar al cliente si es necesario.
</p>

<hr>

<h3>Datos recibidos</h3>

<p><b>Empresa:</b> {valor("empresa", "(sin empresa)")}</p>
<p><b>RUT:</b> {valor("rut", "(sin RUT)")}</p>
<p><b>Contacto:</b> {valor("contacto", "(sin contacto)")}</p>
<p><b>Correo:</b> {valor("correo", "(sin correo)")}</p>
<p><b>Teléfono:</b> {valor("telefono", "(sin teléfono)")}</p>
<p><b>Número de parte / descripción:</b> {valor("num_parte", "(sin descripción)")}</p>
<p><b>Marca:</b> {valor("marca", "(sin marca)")}</p>
<p><b>Cantidad:</b> {valor("cantidad", "(sin cantidad)")}</p>
<p><b>Dirección de entrega:</b> {valor("direccion_entrega", "(sin dirección)")}</p>

<hr>

<h3>Campos faltantes o inválidos</h3>
{faltantes_html}

<h3>Último mensaje recibido</h3>
<p>
<pre style="white-space: pre-wrap; font-family: Arial, sans-serif;">{mensaje_html}</pre>
</p>

<hr>

<p>
Saludos,<br>
Sistema de atención Selec
</p>
"""

    payload_mail = {
        "data": [
            {
                "from": construir_remitente(),

                "to": [
                    build_mail_recipient(
                        MAIL_TO_FIXED,
                        MAIL_TO_NAME,
                    )
                ],

                "cc": construir_cc(),

                "subject": subject,

                "content": content,

                "mail_format": "html",
            }
        ]
    }

    try:
        print(
            "[enviar_correo_solicitud_incompleta] "
            "Enviando alerta..."
        )

        response = requests.post(
            url,
            headers=headers,
            json=payload_mail,
            timeout=10,
        )

        print(
            "=== Respuesta correo solicitud incompleta ==="
        )

        print(
            "Status:",
            response.status_code,
        )

        print(
            "Respuesta:",
            response.text,
        )

        return response

    except Exception as error:
        print(
            "[enviar_correo_solicitud_incompleta] "
            "ERROR:",
            error,
        )

        return None


# =========================================================
# CORREO DE PRIMER CONTACTO
# =========================================================

def enviar_correo_primer_contacto(
    owner: dict,
    payload: dict,
    access_token: str,
):
    """
    Envía una notificación cuando un visitante
    realiza su primer contacto mediante SalesIQ.
    """

    to_email = MAIL_TO_FIXED
    to_name = MAIL_TO_NAME

    visitor = payload.get("visitor") or {}

    visitor_name = (
        visitor.get("name")
        or visitor.get("email")
        or visitor.get("phone")
        or "Cliente sin identificar"
    )

    visitor_email = (
        visitor.get("email")
        or ""
    )

    visitor_phone = (
        visitor.get("phone")
        or ""
    )

    conversation_id = str(
        visitor.get(
            "active_conversation_id"
        ) or ""
    ).strip()

    current_page = (
        visitor.get("current_page_url")
        or ""
    )

    question = (
        visitor.get("question")
        or ""
    )

    chat_link = construir_link_chat(
        payload
    )

    subject = (
        "Nuevo contacto recibido por "
        f"SalesIQ: {visitor_name}"
    )

    if chat_link:

        bloque_chat = (
            '<p>'
            '<b>Link directo del chat:</b> '
            f'<a href="{chat_link}">'
            'Abrir conversación'
            '</a>'
            '</p>'
        )

    else:

        bloque_chat = (
            "<p>"
            "<b>ID conversación:</b> "
            f"{conversation_id or '(no disponible)'}"
            "</p>"
        )

    content = f"""
<p>Estimado/a {to_name},</p>

<p>
Se informa que un cliente se ha contactado
con Selec mediante SalesIQ.
</p>

<p>
<b>Nombre:</b>
{visitor_name}
</p>

<p>
<b>Correo:</b>
{visitor_email or "(no informado)"}
</p>

<p>
<b>Teléfono:</b>
{visitor_phone or "(no informado)"}
</p>

<p>
<b>Consulta inicial:</b>
{question or "(sin mensaje inicial)"}
</p>

<p>
<b>Página actual:</b>
{current_page or "(no disponible)"}
</p>

{bloque_chat}

<p>
Por favor, revisar la conversación para continuar
con la atención del cliente.
</p>

<p>
Saludos cordiales,<br>
Sistema de atención Selec
</p>
"""

    url = (
        f"{CRM_BASE}/Deals/actions/send_mail"
    )

    headers = {
        "Authorization": (
            f"Zoho-oauthtoken {access_token}"
        ),
        "Content-Type": "application/json",
    }

    payload_mail = {
        "data": [
            {
                "from": construir_remitente(),

                "to": [
                    build_mail_recipient(
                        to_email,
                        to_name
                    )
                ],

                "cc": construir_cc(),

                "subject": subject,

                "content": content,

                "mail_format": "html",
            }
        ]
    }

    try:
        print(
            "[enviar_correo_primer_contacto] "
            "Enviando correo..."
        )

        response = requests.post(
            url,
            headers=headers,
            json=payload_mail,
            timeout=10,
        )

        print(
            "=== Respuesta correo "
            "primer contacto ==="
        )

        print(
            "Status:",
            response.status_code
        )

        print(
            "Respuesta:",
            response.text
        )

        return response

    except Exception as error:
        print(
            "[enviar_correo_primer_contacto] "
            "ERROR:",
            error
        )

        return None