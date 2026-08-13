import re
import unicodedata

from services.zoho_service import normalizar_owner


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


def build_reply(
    texts,
    input_card=None,
    action="reply"
) -> dict:
    """
    Construye una respuesta estándar para SalesIQ.
    """

    if isinstance(texts, str):
        replies = [texts]
    else:
        replies = list(texts)

    response = {
        "action": action,
        "replies": replies,
    }

    if input_card is not None:
        response["input"] = input_card

    return response


def reply_menu_principal() -> dict:
    """
    Respuesta inicial del menú principal.
    """

    return build_reply(
        [
            "¿Qué necesitas?",
            "1. Cotizar productos",
            "2. Soporte postventa",
        ]
    )


def elegir_owner_session(session: dict) -> dict:
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

        data["owner_asignado"] = owner

        return owner

    owner = normalizar_owner()

    data["owner_asignado"] = owner

    return owner


def manejar_menu_principal(
    session: dict,
    message_text: str
) -> dict:
    """
    Procesa la opción seleccionada desde
    el menú principal.
    """

    texto_norm = normalizar_texto(
        message_text
    )

    if es_opcion_cotizacion(texto_norm):
        return iniciar_cotizacion(
            session
        )

    if es_opcion_postventa(texto_norm):
        return iniciar_postventa(
            session
        )

    return derivar_a_operador(
        session
    )


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
        [
            "Perfecto, trabajaremos en su solicitud de cotización.",
            (
                "Por favor, complete los siguientes datos de la "
                "empresa y del contacto en un solo mensaje "
                "(puede copiar y pegar este formato):\n\n"
                "Nombre de la empresa:\n"
                "RUT:\n"
                "Nombre de contacto:\n"
                "Correo:\n"
                "Teléfono:"
            ),
        ]
    )


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

    formulario = (
        "Perfecto, trabajaremos en su solicitud de postventa.\n"
        "Por favor, responda copiando y completando este formulario "
        "en un solo mensaje:\n\n"
        "Nombre:\n"
        "RUT:\n"
        "Número de factura:\n"
        "Descripción del problema:"
    )

    return build_reply(
        formulario
    )


def derivar_a_operador(
    session: dict
) -> dict:
    """
    Deriva al visitante a un ejecutivo
    cuando la opción no es reconocida.
    """

    session["state"] = (
        "derivado_operador"
    )

    return {
        "action": "forward",
        "replies": [
            "En este momento no puedo gestionar esta solicitud automáticamente.",
            "Le derivaré con un ejecutivo para que pueda asistirle.",
        ],
    }

