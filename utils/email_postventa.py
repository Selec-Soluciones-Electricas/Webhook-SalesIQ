import os
import html
import requests

from werkzeug.utils import secure_filename

from services.zoho_service import get_access_token


# =========================================================
# CONFIGURACIÓN
# =========================================================

CRM_BASE = "https://www.zohoapis.com/crm/v8"
CRM_ORG_UI = "org706345205"


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

    correo = str(
        datos.get(
            "correo",
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


    origen = str(
        datos.get(
            "origen",
            ""
        )
    ).strip().lower()


    if origen == "web":

        origen_texto = "Web"

    elif origen == "whatsapp":

        origen_texto = "WhatsApp"

    else:

        origen_texto = "SELEC"


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
        "Solicitud recibida desde SELEC.\n\n"

        f"Nombre: {nombre}\n"
        f"Correo: {correo}\n"
        f"Rut de Empresa: {rut}\n"

        "Número de factura y/o Orden de compra: "
        f"{factura_oc}\n"

        "Descripción de la situación: "
        f"{detalle}"
    )

    payload = {
        "data": [
            {
                "Subject": (
                    f"Postventa {origen_texto} - "
                    f"{factura_oc or nombre}"
                ),

                "Case_Origin": origen_texto,

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
# SUBIR ARCHIVOS AL CASE DE POSTVENTA
# =========================================================

def subir_archivos_postventa(
    case_id: str,
    archivos: list,
    access_token: str,
) -> list:
    """
    Sube fotografías y archivos PDF al Case
    de postventa creado en Zoho CRM.
    """

    case_id = str(
        case_id or ""
    ).strip()

    if not case_id:

        print(
            "[POSTVENTA ARCHIVOS] "
            "No se recibió Case ID."
        )

        return []


    if not archivos:

        print(
            "[POSTVENTA ARCHIVOS] "
            "No hay archivos para subir."
        )

        return []


    url = (
        "https://www.zohoapis.com/"
        f"crm/v8/Cases/{case_id}/Attachments"
    )


    headers = {
        "Authorization":
            f"Zoho-oauthtoken {access_token}"
    }


    resultados = []


    for indice, archivo in enumerate(
        archivos,
        start=1,
    ):

        nombre_original = str(
            getattr(
                archivo,
                "filename",
                "",
            )
            or ""
        ).strip()


        if not nombre_original:

            continue


        nombre_seguro = secure_filename(
            nombre_original
        )


        if not nombre_seguro:

            nombre_seguro = (
                f"archivo_postventa_{indice}"
            )


        nombre_zoho = (
            f"Postventa_{indice}_"
            f"{nombre_seguro}"
        )


        tipo_contenido = str(
            getattr(
                archivo,
                "mimetype",
                "",
            )
            or
            "application/octet-stream"
        )


        try:

            archivo.stream.seek(0)


            files = {
                "file": (
                    nombre_zoho,
                    archivo.stream,
                    tipo_contenido,
                )
            }


            print(
                "[POSTVENTA ARCHIVOS] "
                f"Subiendo {nombre_zoho} "
                f"al Case {case_id}..."
            )


            response = requests.post(
                url,
                headers=headers,
                files=files,
                timeout=60,
            )


            print(
                "[POSTVENTA ARCHIVOS] "
                f"Status: {response.status_code}"
            )


            try:

                print(
                    "[POSTVENTA ARCHIVOS] "
                    f"Respuesta: {response.text}"
                )

            except Exception:

                pass


            resultados.append({
                "archivo":
                    nombre_zoho,

                "status":
                    response.status_code,

                "ok":
                    response.status_code
                    in (
                        200,
                        201,
                    ),
            })


            archivo.stream.seek(0)


        except Exception as error:

            print(
                "[POSTVENTA ARCHIVOS] "
                f"ERROR con {nombre_zoho}:",
                error,
            )


            resultados.append({
                "archivo":
                    nombre_zoho,

                "status":
                    0,

                "ok":
                    False,

                "error":
                    str(error),
            })


    return resultados


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


    correo = str(
        datos.get(
            "correo",
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


    origen = str(
        datos.get(
            "origen",
            ""
        )
    ).strip().lower()


    if origen == "web":

        origen_texto = "sitio web de SELEC"

    elif origen == "whatsapp":

        origen_texto = "chatbot de WhatsApp de SELEC"

    else:

        origen_texto = "canal de atención de SELEC"


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

    case_link = (
        f"https://crm.zoho.com/crm/"
        f"{CRM_ORG_UI}/tab/Cases/"
        f"{case_id}"
    )


    # =====================================================
    # SUBIR ARCHIVOS AL CASE
    # =====================================================

    archivos = (
        datos.get("archivos")
        or []
    )

    try:

        resultado_archivos = (
            subir_archivos_postventa(
                case_id,
                archivos,
                access_token,
            )
        )

        print(
            "[POSTVENTA] "
            "Resultado archivos:",
            resultado_archivos,
        )

    except Exception as error:

        print(
            "[POSTVENTA] "
            "ERROR subiendo archivos:",
            error,
        )


    # =====================================================
    # PREPARAR CORREO
    # =====================================================

    nombre_html = html.escape(
    nombre
    )

    correo_html = html.escape(
        correo
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
            de postventa mediante el
            {origen_texto}.
        </p>

        <hr>

                <p>
            <strong>Nombre:</strong><br>
            {nombre_html}
        </p>

        <p>
            <strong>Correo:</strong><br>
            {correo_html}
        </p>

        <p>
            <strong>RUT de Empresa:</strong><br>
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

        <p>
            <strong>
                Caso en Zoho CRM:
            </strong>
            <br>
            <a href="{case_link}">
                Abrir caso en Zoho CRM
            </a>
        </p>

        <hr>

        <p>
            Solicitud registrada automáticamente
            desde el {origen_texto}.
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