import os
import time
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

# Modo de prueba para correos de cotización
COTIZACION_MODO_PRUEBA = (
    os.environ.get(
        "COTIZACION_MODO_PRUEBA",
        "false"
    ).strip().lower() == "true"
)

COTIZACION_TEST_TO = os.environ.get(
    "COTIZACION_TEST_TO",
    ""
).strip()

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

def obtener_link_zoho_one(
    deal_id: str,
    access_token: str,
) -> str:

    deal_id = str(
        deal_id or ""
    ).strip()

    if not deal_id:

        return ""


    url = (
        "https://www.zohoapis.com/"
        f"crm/v8/Deals/{deal_id}"
    )


    headers = {
        "Authorization":
            f"Zoho-oauthtoken {access_token}"
    }


    params = {
        "fields":
            "Zoho_One_Negocio"
    }


    for intento in range(
        1,
        11,
    ):

        try:

            response = requests.get(
                url,
                headers=headers,
                params=params,
                timeout=15,
            )


            if response.status_code == 200:

                data = response.json()

                registros = (
                    data.get("data")
                    or []
                )


                if registros:

                    zoho_one_link = str(
                        registros[0].get(
                            "Zoho_One_Negocio"
                        )
                        or ""
                    ).strip()


                    if zoho_one_link:

                        print(
                            "[enviar_correo_owner] "
                            "Link Zoho One encontrado:",
                            zoho_one_link,
                        )

                        return zoho_one_link


        except Exception as error:

            print(
                "[enviar_correo_owner] "
                "Error obteniendo link Zoho One:",
                error,
            )


        if intento < 10:

            time.sleep(1)


    print(
        "[enviar_correo_owner] "
        "No se encontró link de Zoho One."
    )

    return ""

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
    Negocio generado desde Web o WhatsApp.

    En modo prueba:
    - Envía únicamente a COTIZACION_TEST_TO.
    - No envía copias.

    En producción:
    - Envía al ejecutivo asignado a la cotización.
    - Envía copia a Luis Hurtado / Gerencia.
    """

    # =====================================================
    # EJECUTIVO ASIGNADO A LA COTIZACIÓN
    # =====================================================

    owner_email = str(
        owner.get("email")
        or ""
    ).strip()

    owner_name = str(
        owner.get("nombre")
        or ""
    ).strip()

    if not owner_name:
        owner_name = "Ejecutivo Selec"

    # =====================================================
    # MODO PRUEBA / PRODUCCIÓN
    # =====================================================

    if COTIZACION_MODO_PRUEBA:

        if not COTIZACION_TEST_TO:

            print(
                "[enviar_correo_owner] "
                "COTIZACION_MODO_PRUEBA está activo, "
                "pero COTIZACION_TEST_TO está vacío. "
                "No se enviará ningún correo."
            )

            return None

        to_email = COTIZACION_TEST_TO
        to_name = "Ederth"
        cc_destinatarios = []

        print(
            "[enviar_correo_owner] MODO PRUEBA ACTIVO"
        )

        print(
            "[enviar_correo_owner] Ejecutivo real:",
            owner_name,
            owner_email
        )

        print(
            "[enviar_correo_owner] Correo redirigido a:",
            to_email
        )

    else:

        if not owner_email:

            print(
                "[enviar_correo_owner] "
                "El ejecutivo asignado no tiene correo configurado. "
                "No se enviará la notificación."
            )

            return None

        # Destinatario principal:
        # Patricio / ejecutivo asignado
        to_email = owner_email
        to_name = owner_name

        # Copia a Luis Hurtado / Gerencia
        cc_destinatarios = [
            build_mail_recipient(
                "gerencia@selec.cl",
                "Luis Hurtado"
            )
        ]

    # =====================================================
    # ACCESS TOKEN
    # =====================================================

    access_token = get_access_token()

    if not access_token:

        print(
            "[enviar_correo_owner] "
            "No se pudo obtener access token; "
            "no se envía correo."
        )

        return None

    # Nombre inicial recibido por la función
    deal_name_real = str(
        deal_name or ""
    ).strip()

    # Intentamos obtener el nombre real guardado en CRM
    try:

        response_nombre = requests.get(
            (
                "https://www.zohoapis.com/"
                f"crm/v8/Deals/{deal_id}"
            ),
            headers={
                "Authorization":
                    f"Zoho-oauthtoken {access_token}"
            },
            params={
                "fields":
                    "Deal_Name"
            },
            timeout=15,
        )

        if response_nombre.status_code == 200:

            registros_nombre = (
                response_nombre.json().get(
                    "data"
                )
                or []
            )

            if registros_nombre:

                nombre_crm = str(
                    registros_nombre[0].get(
                        "Deal_Name"
                    )
                    or ""
                ).strip()

                if nombre_crm:

                    deal_name_real = nombre_crm

                    print(
                        "[enviar_correo_owner] "
                        "Nombre real del Negocio:",
                        deal_name_real,
                    )

    except Exception as error:

        print(
            "[enviar_correo_owner] "
            "No se pudo obtener el nombre "
            "real del Negocio:",
            error,
        )

    # =====================================================
    # ENDPOINT ZOHO CRM
    # =====================================================

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

    # =====================================================
    # ORIGEN
    # =====================================================

    origen = str(
        campos.get("origen")
        or ""
    ).strip().lower()

    if origen == "web":

        origen_asunto = "Web"
        origen_texto = "sitio web de SELEC"

    elif origen == "whatsapp":

        origen_asunto = "WhatsApp"
        origen_texto = "chatbot de WhatsApp de SELEC"

    else:

        origen_asunto = "SELEC"
        origen_texto = "canal de atención de SELEC"

    # =====================================================
    # ASUNTO Y LINKS
    # =====================================================

    subject = (
        f"Nuevo Negocio asignado desde {origen_asunto}: "
        f"{deal_name_real}"
    )

    deal_link = (
        f"https://crm.zoho.com/crm/"
        f"{CRM_ORG_UI}/tab/Potentials/"
        f"{deal_id}"
    )

    zoho_one_link = obtener_link_zoho_one(
        deal_id,
        access_token,
    )

    if zoho_one_link:

        bloque_zoho_one = f"""
<p>
<b>Negocio en Zoho One:</b><br>
<a href="{zoho_one_link}">
Abrir Negocio en Zoho One
</a>
</p>
"""

    else:

        bloque_zoho_one = ""

    # =====================================================
    # CONTENIDO
    # =====================================================

    content = f"""
<p>Hola {to_name},</p>

<p>
Se ha creado un nuevo Negocio asignado desde
el {origen_texto}.
</p>

<p>
<b>Número de Chat (SalesIQ):</b>
{campos.get("num_chat") or "(sin número de chat)"}
</p>

<p>
<b>Negocio:</b>
{deal_name_real}
</p>

<p>
<b>Link del Negocio en Zoho CRM:</b>
<a href="{deal_link}">
Abrir Negocio
</a>
</p>

{bloque_zoho_one}

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
<b>Ejecutivo asignado:</b>
{owner_name}
</p>

<p>
Saludos,<br>
Sistema de atención SELEC
</p>
"""

    # =====================================================
    # PAYLOAD
    # =====================================================

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

                "cc": cc_destinatarios,

                "subject": subject,

                "content": content,

                "mail_format": "html",
            }
        ]
    }

    # =====================================================
    # ENVÍO
    # =====================================================

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