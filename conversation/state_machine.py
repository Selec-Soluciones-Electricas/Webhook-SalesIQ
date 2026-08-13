import re
import unicodedata

from services.zoho_service import normalizar_owner


# =========================================================
# NORMALIZAR TEXTO
# =========================================================

def normalizar_texto(s: str) -> str:
    """
    Normaliza un texto para facilitar las comparaciones.
    """

    s = (s or "").strip().lower()

    s = unicodedata.normalize(
        "NFD",
        s
    )

    s = "".join(
        ch
        for ch in s
        if unicodedata.category(ch) != "Mn"
    )

    s = re.sub(
        r"\s+",
        " ",
        s
    )

    return s


# =========================================================
# CONSTRUIR RESPUESTAS
# =========================================================

def build_reply(
    texts,
    input_card=None,
    action="reply"
) -> dict:
    """
    Construye una respuesta estándar para SalesIQ.

    IMPORTANTE:
    Cuando el código entrega varios textos en una lista,
    estos representan partes de una misma respuesta lógica.

    En lugar de enviarlos como múltiples mensajes separados
    a SalesIQ, se unen en un único mensaje utilizando
    saltos de línea.

    Esto evita conversaciones fragmentadas como:

        Mensaje 1
        Mensaje 2
        Mensaje 3
        Mensaje 4

    y las transforma en:

        Mensaje 1

        Mensaje 2

        Mensaje 3

        Mensaje 4

    De esta manera el usuario recibe una sola respuesta
    más limpia y natural.

    Si se recibe directamente un string, se mantiene
    como una única respuesta.
    """

    if isinstance(texts, str):

        mensaje = texts.strip()

    else:

        partes = []

        for texto in texts or []:

            if texto is None:
                continue

            texto_clean = str(
                texto
            ).strip()

            if not texto_clean:
                continue

            partes.append(
                texto_clean
            )

        mensaje = "\n\n".join(
            partes
        )

    response = {
        "action": action,
        "replies": [
            mensaje
        ],
    }

    if input_card is not None:

        response["input"] = (
            input_card
        )

    return response


# =========================================================
# MENÚ PRINCIPAL
# =========================================================

def reply_menu_principal() -> dict:
    """
    Respuesta inicial del menú principal.
    """

    return build_reply(
        (
            "¿Qué necesitas?\n\n"
            "1. Cotizar productos\n"
            "2. Soporte postventa"
        )
    )


# =========================================================
# OWNER DE LA SESIÓN
# =========================================================

def elegir_owner_session(
    session: dict
) -> dict:
    """
    Obtiene el owner asignado a la sesión.

    Si ya existe, lo normaliza.
    Si no existe, obtiene uno nuevo.
    """

    data = session.setdefault(
        "data",
        {}
    )

    owner = data.get(
        "owner_asignado"
    )

    if owner:

        owner = normalizar_owner(
            owner
        )

        data[
            "owner_asignado"
        ] = owner

        return owner

    owner = normalizar_owner()

    data[
        "owner_asignado"
    ] = owner

    return owner


# =========================================================
# DETECTAR SALUDO
# =========================================================

def es_saludo_inicio(
    message_text: str
) -> bool:
    """
    Determina si el mensaje corresponde
    a un saludo simple utilizado para
    iniciar o reiniciar la conversación.
    """

    texto_norm = normalizar_texto(
        message_text
    )

    saludos = {
        "hola",
        "holaa",
        "holaaa",
        "buenas",
        "buenos dias",
        "buenas tardes",
        "buenas noches",
        "hello",
        "hi",
    }

    return (
        texto_norm in saludos
    )


# =========================================================
# MENÚ PRINCIPAL
# =========================================================

def manejar_menu_principal(
    session: dict,
    message_text: str
) -> dict:
    """
    Procesa la opción seleccionada
    desde el menú principal.
    """

    texto_norm = normalizar_texto(
        message_text
    )

    if es_opcion_cotizacion(
        texto_norm
    ):

        return iniciar_cotizacion(
            session
        )

    if es_opcion_postventa(
        texto_norm
    ):

        return iniciar_postventa(
            session
        )

    return derivar_a_operador(
        session
    )


# =========================================================
# OPCIÓN COTIZACIÓN
# =========================================================

def es_opcion_cotizacion(
    texto_norm: str
) -> bool:
    """
    Determina si el mensaje corresponde
    a una solicitud de cotización.
    """

    return (
        texto_norm == "1"
        or "cotiz" in texto_norm
        or texto_norm == "solicitud cotizacion"
        or texto_norm == "cotizacion"
    )


# =========================================================
# OPCIÓN POSTVENTA
# =========================================================

def es_opcion_postventa(
    texto_norm: str
) -> bool:
    """
    Determina si el mensaje corresponde
    a una solicitud de postventa.
    """

    return (
        texto_norm == "2"
        or "postventa" in texto_norm
        or "post venta" in texto_norm
        or "servicio postventa" in texto_norm
    )


# =========================================================
# INICIAR COTIZACIÓN
# =========================================================

def iniciar_cotizacion(
    session: dict
) -> dict:
    """
    Inicia el flujo de cotización.
    """

    session["state"] = (
        "cotizacion_empresa_bloque"
    )

    session["data"] = {}

    return build_reply(
        (
            "Perfecto, trabajaremos en su "
            "solicitud de cotización.\n\n"
            "Por favor, complete los siguientes "
            "datos de la empresa y del contacto "
            "en un solo mensaje. Puede copiar "
            "y completar este formato:\n\n"
            "Nombre de la empresa:\n"
            "RUT:\n"
            "Nombre de contacto:\n"
            "Correo:\n"
            "Teléfono:"
        )
    )


# =========================================================
# INICIAR POSTVENTA
# =========================================================

def iniciar_postventa(
    session: dict
) -> dict:
    """
    Inicia el flujo de postventa.
    """

    session["state"] = (
        "postventa_bloque"
    )

    session["data"] = {}

    return build_reply(
        (
            "Perfecto, trabajaremos en su "
            "solicitud de postventa.\n\n"
            "Por favor, complete este formulario "
            "en un solo mensaje:\n\n"
            "Nombre:\n"
            "RUT:\n"
            "Número de factura:\n"
            "Descripción del problema:"
        )
    )


# =========================================================
# OPCIÓN INVÁLIDA
# =========================================================

def derivar_a_operador(
    session: dict
) -> dict:
    """
    Maneja una opción inválida del menú principal.

    No deriva al operador ni cambia a otro flujo:
    mantiene al visitante en el menú para que
    pueda ingresar 1 o 2.
    """

    session["state"] = (
        "menu_principal"
    )

    return build_reply(
        (
            "La opción ingresada no es válida.\n\n"
            "Por favor, seleccione una opción:\n"
            "1. Cotizar productos\n"
            "2. Soporte postventa"
        )
    )