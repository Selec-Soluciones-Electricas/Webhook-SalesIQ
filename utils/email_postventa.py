import os
import html
import requests

from services.zoho_service import get_access_token


# =========================================================
# CONFIGURACIÓN
# =========================================================

CRM_BASE = "https://www.zohoapis.com/crm/v8"


# =========================================================
# UTILIDADES
# =========================================================

def convertir_lista_correos(
    valor: str
) -> list[str]:

    return [
        correo.strip()
        for correo in (valor or "").split(",")
        if correo.strip()
    ]


def valor_booleano(
    valor: str
) -> bool:

    return str(
        valor or ""
    ).strip().lower() in (
        "1",
        "true",
        "yes",
        "si",
        "sí",
        "on",
    )


def construir_destinatario(
    email: str,
    nombre: str = ""
) -> dict:

    destinatario = {
        "email": email.strip()
    }

    if nombre.strip():

        destinatario["user_name"] = (
            nombre.strip()
        )

    return destinatario


# =========================================================
# CREAR CASO DE POSTVENTA EN ZOHO CRM
# =========================================================

def crear_caso_postventa(
    datos: dict,
    access_token: str
) -> str:
    """
    Crea un Case en Zoho CRM con los datos recopilados
    por el chatbot.

    Devuelve el ID del Case creado.
    """

    nombre = str(
        datos.get(
            "nombre",
            ""
        )
    ).strip()

    rut = str(
        datos.get(
            "rut",
            ""
        )
    ).strip()

    factura_oc = str(
        datos.get(
            "numero_factura",
            ""
        )
    ).strip()

    detalle = str(
        datos.get(
            "detalle",
            ""
        )
    ).strip()

    url = (
        f"{CRM_BASE}/Cases"
    )

    headers = {
        "Authorization":
            f"Zoho-oauthtoken {access_token}",

        "Content-Type":
            "application/json",
    }

    descripcion = (
        "Solicitud recibida desde el chatbot "
        "de WhatsApp de SELEC.\n\n"

        f"Nombre: {nombre}\n"
        f"RUT: {rut}\n"

        "Número de factura y/o Orden de compra: "
        f"{factura_oc}\n"

        "Descripción de la situación: "
        f"{detalle}"
    )

    payload = {
        "data": [
            {
                "Subject": (
                    "Postventa WhatsApp - "
                    f"{factura_oc or nombre}"
                ),

                "Case_Origin": "Web",

                "Status": "New",

                "Description": descripcion,
            }
        ]
    }

    print(
        "[POSTVENTA] Creando Case en Zoho CRM..."
    )

    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=15,
    )

    print(
        "[POSTVENTA] Crear Case status:",
        response.status_code,
    )

    print(
        "[POSTVENTA] Crear Case respuesta:",
        response.text,
    )

    if response.status_code not in (
        200,
        201,
    ):

        raise RuntimeError(
            "Zoho CRM no permitió crear "
            f"el Case: {response.text}"
        )

    respuesta = response.json()

    registros = respuesta.get(
        "data",
        []
    )

    if not registros:

        raise RuntimeError(
            "Zoho CRM no devolvió información "
            "del Case creado."
        )

    resultado = registros[0]

    if (
        resultado.get("status")
        != "success"
    ):

        raise RuntimeError(
            "No fue posible crear el Case "
            f"de postventa: {resultado}"
        )

    case_id = str(
        (
            resultado.get("details")
            or {}
        ).get("id")
        or ""
    ).strip()

    if not case_id:

        raise RuntimeError(
            "Zoho CRM creó el Case pero "
            "no devolvió su ID."
        )

    print(
        "[POSTVENTA] Case creado:",
        case_id,
    )

    return case_id


# =========================================================
# ENVIAR CORREO DE POSTVENTA
# =========================================================

def enviar_correo_postventa(
    datos: dict
) -> dict:
    """
    1. Obtiene el token OAuth existente.
    2. Crea un Case de postventa.
    3. Envía el correo asociado a ese Case.

    Durante POSTVENTA_MODO_PRUEBA=true
    únicamente se envía a POSTVENTA_TEST_TO.
    """

    # =====================================================
    # TOKEN ZOHO
    # =====================================================

    access_token = get_access_token()

    if not access_token:

        raise RuntimeError(
            "No fue posible obtener "
            "el access token de Zoho."
        )

    # =====================================================
    # DATOS
    # =====================================================

    nombre = str(
        datos.get(
            "nombre",
            ""
        )
    ).strip()

    rut = str(
        datos.get(
            "rut",
            ""
        )
    ).strip()

    factura_oc = str(
        datos.get(
            "numero_factura",
            ""
        )
    ).strip()

    detalle = str(
        datos.get(
            "detalle",
            ""
        )
    ).strip()

    # =====================================================
    # MODO PRUEBA / PRODUCCIÓN
    # =====================================================

    modo_prueba = valor_booleano(
        os.environ.get(
            "POSTVENTA_MODO_PRUEBA",
            "true",
        )
    )

    if modo_prueba:

        destinatarios = (
            convertir_lista_correos(
                os.environ.get(
                    "POSTVENTA_TEST_TO",
                    "ederth@selec.cl",
                )
            )
        )

        copias = []

    else:

        destinatarios = (
            convertir_lista_correos(
                os.environ.get(
                    "POSTVENTA_TO",
                    "",
                )
            )
        )

        copias = (
            convertir_lista_correos(
                os.environ.get(
                    "POSTVENTA_CC",
                    "",
                )
            )
        )

    if not destinatarios:

        raise RuntimeError(
            "No existen destinatarios "
            "configurados para postventa."
        )

    # =====================================================
    # REMITENTE DE ZOHO CRM
    # =====================================================

    sender_email = os.environ.get(
        "SENDER_USER_EMAIL",
        "",
    ).strip()

    sender_name = os.environ.get(
        "SENDER_USER_NAME",
        "SELEC",
    ).strip()

    if not sender_email:

        raise RuntimeError(
            "Falta configurar "
            "SENDER_USER_EMAIL."
        )

    # =====================================================
    # CREAR CASE
    # =====================================================

    case_id = crear_caso_postventa(
        datos,
        access_token,
    )

    # =====================================================
    # PREPARAR CORREO
    # =====================================================

    nombre_html = html.escape(
        nombre
    )

    rut_html = html.escape(
        rut
    )

    factura_html = html.escape(
        factura_oc
    )

    detalle_html = html.escape(
        detalle
    )

    asunto = (
        "Nueva solicitud de postventa SELEC"
        f" | {factura_oc}"
    )

    contenido = f"""
    <html>

    <body
        style="
            font-family: Arial, Helvetica, sans-serif;
            color: #222222;
        "
    >

        <h2>
            Nueva solicitud de postventa SELEC
        </h2>

        <p>
            Se ha recibido una nueva solicitud
            de postventa mediante el chatbot
            de WhatsApp de SELEC.
        </p>

        <hr>

        <p>
            <strong>Nombre:</strong><br>
            {nombre_html}
        </p>

        <p>
            <strong>RUT:</strong><br>
            {rut_html}
        </p>

        <p>
            <strong>
                Número de factura y/o Orden de compra:
            </strong>
            <br>
            {factura_html}
        </p>

        <p>
            <strong>
                Descripción de la situación:
            </strong>
            <br>
            {detalle_html}
        </p>

        <hr>

        <p>
            Solicitud registrada automáticamente
            desde el chatbot de WhatsApp.
        </p>

    </body>

    </html>
    """

    # =====================================================
    # SEND MAIL DEL CASE
    # =====================================================

    url = (
        f"{CRM_BASE}/Cases/"
        f"{case_id}/actions/send_mail"
    )

    headers = {
        "Authorization":
            f"Zoho-oauthtoken {access_token}",

        "Content-Type":
            "application/json",
    }

    lista_to = [
        construir_destinatario(
            correo
        )
        for correo in destinatarios
    ]

    lista_cc = [
        construir_destinatario(
            correo
        )
        for correo in copias
    ]

    datos_correo = {
        "from": {
            "user_name": sender_name,
            "email": sender_email,
        },

        "to": lista_to,

        "subject": asunto,

        "content": contenido,

        "mail_format": "html",
    }

    if lista_cc:

        datos_correo["cc"] = (
            lista_cc
        )

    payload = {
        "data": [
            datos_correo
        ]
    }

    print(
        "[POSTVENTA] Enviando correo..."
    )

    print(
        "[POSTVENTA] Destinatarios:",
        ", ".join(destinatarios),
    )

    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=15,
    )

    print(
        "[POSTVENTA] Send mail status:",
        response.status_code,
    )

    print(
        "[POSTVENTA] Send mail respuesta:",
        response.text,
    )

    if response.status_code not in (
        200,
        201,
    ):

        raise RuntimeError(
            "Zoho CRM no pudo enviar "
            f"el correo: {response.text}"
        )

    respuesta = response.json()

    resultados = respuesta.get(
        "data",
        []
    )

    if not resultados:

        raise RuntimeError(
            "Zoho CRM no devolvió resultado "
            "del envío del correo."
        )

    resultado = resultados[0]

    if (
        resultado.get("status")
        != "success"
    ):

        raise RuntimeError(
            "Zoho CRM rechazó el envío "
            f"del correo: {resultado}"
        )

    print(
        "[POSTVENTA] Correo enviado "
        "correctamente."
    )

    return {
        "case_id": case_id,
        "email_response": resultado,
    }