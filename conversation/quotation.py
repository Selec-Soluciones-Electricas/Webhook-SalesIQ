import re

from conversation.state_machine import (
    build_reply,
    normalizar_texto,
)

from validators.email import extraer_email
from validators.phone import (
    limpiar_digitos,
    es_telefono_plausible,
)
from validators.rut import es_rut_plausible

from utils.security import (
    mask_email,
    mask_phone,
    mask_rut,
)

from services.zoho_service import (
    normalizar_owner,
    obtener_o_crear_account,
    obtener_o_crear_contact,
    crear_deal_en_zoho,
)

from services.email_service import enviar_correo_owner


# =========================================================
# UTILIDADES
# =========================================================

def es_mayormente_numerico(s: str) -> bool:
    """
    Determina si un texto está compuesto principalmente
    por caracteres numéricos.
    """
    d = limpiar_digitos(s)

    return bool(d) and (
        len(d) / max(len(s.replace(" ", "")), 1)
    ) > 0.6


# =========================================================
# EXTRACCIÓN DE DATOS DEL PRODUCTO
# =========================================================

def extraer_campos_cotizacion_producto(
    texto: str,
    campos: dict,
) -> dict:
    """
    Extrae los datos del producto desde un mensaje
    estructurado por etiquetas.
    """

    lineas = [
        linea.strip()
        for linea in texto.splitlines()
        if linea.strip()
    ]

    lineas_sin_label = []

    for linea in lineas:

        if ":" not in linea:
            lineas_sin_label.append(linea)
            continue

        etiqueta, valor = linea.split(":", 1)

        etiqueta_norm = normalizar_texto(etiqueta)
        valor_clean = valor.strip()

        if not valor_clean:
            continue

        if (
            "empresa" in etiqueta_norm
            or "razon social" in etiqueta_norm
            or "razon_social" in etiqueta_norm
        ):
            campos["empresa"] = valor_clean

        elif etiqueta_norm in (
            "rut",
            "r.u.t",
            "r u t",
        ):
            campos["rut"] = valor_clean

        elif "contacto" in etiqueta_norm:
            campos["contacto"] = valor_clean

        elif (
            "correo" in etiqueta_norm
            or "email" in etiqueta_norm
        ):
            campos["correo"] = valor_clean

        elif "telefono" in etiqueta_norm:
            campos["telefono"] = valor_clean

        elif (
            "numero de parte" in etiqueta_norm
            or "numero parte" in etiqueta_norm
            or "descripcion" in etiqueta_norm
        ):
            campos["num_parte"] = valor_clean

        elif "marca" in etiqueta_norm:
            campos["marca"] = valor_clean

        elif (
            "direccion de entrega" in etiqueta_norm
            or "direccion" in etiqueta_norm
            or "domicilio" in etiqueta_norm
        ):
            campos["direccion_entrega"] = valor_clean

        elif "cantidad" in etiqueta_norm:
            campos["cantidad"] = valor_clean

        else:
            lineas_sin_label.append(linea)

    # Si no se encontró número de parte/descripción
    # mediante una etiqueta, se utilizan las líneas libres.
    if (
        not campos["num_parte"]
        and lineas_sin_label
    ):
        campos["num_parte"] = " ".join(lineas_sin_label)

    # Si no se encontró cantidad mediante una etiqueta,
    # se intenta detectar un número dentro del mensaje.
    if not str(campos["cantidad"]).strip():

        numeros = re.findall(
            r"\b\d+(?:[.,]\d+)?\b",
            texto,
        )

        if numeros:
            campos["cantidad"] = (
                numeros[-1].replace(",", ".")
            )

    return campos


# =========================================================
# VALIDACIÓN DE COTIZACIÓN
# =========================================================

def validar_cotizacion_producto(data: dict) -> list:
    """
    Valida los campos obligatorios del producto
    y la cantidad solicitada.
    """

    obligatorios = [
        "empresa",
        "rut",
        "contacto",
        "correo",
        "telefono",
        "num_parte",
        "cantidad",
    ]

    nombres_legibles = {
        "empresa": "Nombre de la empresa",
        "rut": "RUT",
        "contacto": "Nombre de contacto",
        "correo": "Correo",
        "telefono": "Teléfono",
        "num_parte": (
            "Número de parte o descripción detallada"
        ),
        "cantidad": "Cantidad",
    }

    faltantes = [
        nombres_legibles[campo]
        for campo in obligatorios
        if not str(data.get(campo, "")).strip()
    ]

    try:
        cantidad_val = float(
            str(data.get("cantidad", "")).replace(",", ".")
        )

        if cantidad_val <= 0:
            faltantes.append(
                "Cantidad (debe ser mayor a 0)"
            )

    except Exception:

        if "Cantidad (valor numérico)" not in faltantes:
            faltantes.append(
                "Cantidad (valor numérico)"
            )

    return faltantes


# =========================================================
# RESUMEN DE COTIZACIÓN
# =========================================================

def construir_resumen_cotizacion(data: dict) -> str:
    """
    Construye el resumen seguro que se muestra
    al cliente después de procesar la cotización.
    """

    return (
        "Resumen de su solicitud de cotización:\n"
        f"Nombre de la empresa: {data.get('empresa', '')}\n"
        f"RUT: {mask_rut(data.get('rut', ''))}\n"
        f"Nombre de contacto: {data.get('contacto', '')}\n"
        f"Correo: {mask_email(data.get('correo', ''))}\n"
        f"Teléfono: {mask_phone(data.get('telefono', ''))}\n"
        f"Número de parte / descripción: "
        f"{data.get('num_parte', '')}\n"
        f"Cantidad: {data.get('cantidad', '')}\n"
        f"Marca: {data.get('marca', '')}\n"
        f"Dirección de entrega: "
        f"{data.get('direccion_entrega', '')}"
    )


# =========================================================
# REGISTRO EN ZOHO
# =========================================================

def registrar_cotizacion_en_zoho(data: dict):
    """
    Obtiene o crea Account y Contact y posteriormente
    crea el Deal en Zoho CRM.
    """

    owner = normalizar_owner(
        data.get("owner_asignado")
    )

    account_id = obtener_o_crear_account(
        data,
        owner=owner,
    )

    contact_id = obtener_o_crear_contact(
        data,
        account_id=account_id,
        owner=owner,
    )

    deal_resp, deal_id = crear_deal_en_zoho(
        data,
        account_id=account_id,
        contact_id=contact_id,
        owner=owner,
    )

    return owner, deal_resp, deal_id


# =========================================================
# FINALIZAR COTIZACIÓN
# =========================================================

def finalizar_cotizacion(
    session: dict,
    data: dict,
    deal_id,
    resumen: str,
    owner: dict,
) -> dict:
    """
    Finaliza la sesión de cotización y genera
    la respuesta correspondiente al cliente.
    """

    if deal_id:
        enviar_correo_owner(
            owner,
            deal_id,
            f"Cotización - "
            f"{data.get('empresa') or 'Sin empresa'}",
            data,
        )

    session["state"] = "menu_principal"
    session["data"] = {}
    session["primer_correo_enviado"] = False

    if deal_id:
        return build_reply(
            [
                "Gracias. Hemos registrado su solicitud con el siguiente detalle:",
                resumen,
                "Un ejecutivo de Selec se pondrá en contacto con usted.",
            ]
        )

    return build_reply(
        [
            "Gracias. Hemos recibido su solicitud, pero ocurrió un inconveniente al registrarla automáticamente en nuestro sistema.",
            resumen,
            "Un ejecutivo revisará su caso manualmente y se pondrá en contacto con usted.",
        ]
    )


# =========================================================
# FLUJO DE COTIZACIÓN - PRODUCTO
# =========================================================

def manejar_flujo_cotizacion_bloque(
    session: dict,
    message_text: str,
) -> dict:

    data = session["data"]
    texto = message_text or ""

    campos = {
        "empresa": data.get("empresa", ""),
        "rut": data.get("rut", ""),
        "contacto": data.get("contacto", ""),
        "correo": data.get("correo", ""),
        "telefono": data.get("telefono", ""),
        "num_parte": data.get("num_parte", ""),
        "cantidad": data.get("cantidad", ""),
        "marca": data.get("marca", ""),
        "direccion_entrega": data.get(
            "direccion_entrega",
            "",
        ),
    }

    campos = extraer_campos_cotizacion_producto(
        texto,
        campos,
    )

    data.update(campos)

    faltantes = validar_cotizacion_producto(data)

    if faltantes:

        session["state"] = "cotizacion_bloque"

        return build_reply(
            [
                "No fue posible registrar su solicitud, ya que existen campos obligatorios faltantes o inválidos.",
                "Campos a corregir:\n- "
                + "\n- ".join(faltantes),
                "Por favor, envíe únicamente los datos faltantes o corregidos.",
            ]
        )

    resumen = construir_resumen_cotizacion(data)

    owner, deal_resp, deal_id = (
        registrar_cotizacion_en_zoho(data)
    )

    return finalizar_cotizacion(
        session,
        data,
        deal_id,
        resumen,
        owner,
    )


# =========================================================
# EXTRACCIÓN DE DATOS DE EMPRESA
# =========================================================

def extraer_campos_empresa(
    lineas: list,
    campos: dict,
):
    """
    Extrae los campos de empresa y contacto
    desde un mensaje estructurado.
    """

    sin_label = []

    for linea in lineas:

        if ":" not in linea:
            sin_label.append(linea)
            continue

        etiqueta, valor = linea.split(":", 1)

        etiqueta_norm = normalizar_texto(etiqueta)
        valor_clean = valor.strip()

        if not valor_clean:
            continue

        if (
            "empresa" in etiqueta_norm
            or "razon social" in etiqueta_norm
            or "razon_social" in etiqueta_norm
        ):
            campos["empresa"] = valor_clean

        elif etiqueta_norm in (
            "rut",
            "r.u.t",
            "r u t",
        ):
            campos["rut"] = valor_clean

        elif "contacto" in etiqueta_norm:
            campos["contacto"] = valor_clean

        elif (
            "correo" in etiqueta_norm
            or "email" in etiqueta_norm
        ):
            campos["correo"] = valor_clean

        elif "telefono" in etiqueta_norm:
            campos["telefono"] = valor_clean

        else:
            sin_label.append(linea)

    return sin_label


# =========================================================
# INFERENCIA DE DATOS DE EMPRESA
# =========================================================

def inferir_datos_empresa(
    sin_label: list,
    campos: dict,
):
    """
    Intenta identificar correo, RUT, teléfono,
    empresa y contacto cuando el usuario no utilizó
    etiquetas.
    """

    # Correo
    for linea in list(sin_label):

        if not campos["correo"]:

            email = extraer_email(linea)

            if email:
                campos["correo"] = email
                sin_label.remove(linea)

    # RUT
    for linea in list(sin_label):

        if (
            not campos["rut"]
            and es_rut_plausible(linea)
        ):
            campos["rut"] = linea.strip()
            sin_label.remove(linea)

    # Teléfono
    for linea in list(sin_label):

        if (
            not campos["telefono"]
            and es_telefono_plausible(linea)
        ):
            campos["telefono"] = limpiar_digitos(linea)
            sin_label.remove(linea)

    # Empresa
    if not campos["empresa"]:

        for linea in list(sin_label):

            if extraer_email(linea):
                continue

            if es_mayormente_numerico(linea):
                continue

            campos["empresa"] = linea
            sin_label.remove(linea)
            break

    # Contacto
    if not campos["contacto"]:

        for linea in list(sin_label):

            if extraer_email(linea):
                continue

            if es_mayormente_numerico(linea):
                continue

            campos["contacto"] = linea
            sin_label.remove(linea)
            break

    return campos


# =========================================================
# VALIDACIÓN DE DATOS DE EMPRESA
# =========================================================

def validar_datos_empresa(data: dict) -> list:
    """
    Valida los datos obligatorios de empresa
    y contacto.
    """

    faltantes = []

    if not str(
        data.get("empresa", "")
    ).strip():
        faltantes.append("Nombre de la empresa")

    if not str(
        data.get("rut", "")
    ).strip():
        faltantes.append("RUT")

    if not str(
        data.get("contacto", "")
    ).strip():
        faltantes.append("Nombre de contacto")

    correo_val = str(
        data.get("correo", "")
    ).strip()

    if not correo_val:
        faltantes.append("Correo")

    elif not re.search(
        r"[\w\.-]+@[\w\.-]+\.\w+",
        correo_val,
    ):
        faltantes.append(
            "Correo (formato inválido)"
        )

    telefono_val = str(
        data.get("telefono", "")
    ).strip()

    if not telefono_val:
        faltantes.append("Teléfono")

    return faltantes


# =========================================================
# FLUJO DE COTIZACIÓN - EMPRESA
# =========================================================

def manejar_flujo_cotizacion_empresa_bloque(
    session: dict,
    message_text: str,
) -> dict:

    data = session.setdefault(
        "data",
        {},
    )

    texto = (
        message_text or ""
    ).strip()

    lineas = [
        linea.strip()
        for linea in texto.splitlines()
        if linea.strip()
    ]

    campos = {
        "empresa": data.get("empresa", ""),
        "rut": data.get("rut", ""),
        "contacto": data.get("contacto", ""),
        "correo": data.get("correo", ""),
        "telefono": data.get("telefono", ""),
    }

    sin_label = extraer_campos_empresa(
        lineas,
        campos,
    )

    campos = inferir_datos_empresa(
        sin_label,
        campos,
    )

    data.update(campos)

    faltantes = validar_datos_empresa(data)

    if faltantes:

        session["state"] = (
            "cotizacion_empresa_bloque"
        )

        return build_reply(
            [
                "No fue posible registrar la información, ya que faltan datos obligatorios o el correo presenta un formato inválido.",
                "Campos a corregir:\n- "
                + "\n- ".join(faltantes),
                (
                    "Por favor, envíe únicamente los campos "
                    "faltantes o corregidos.\n\n"
                    "Ejemplo:\n"
                    "Correo: cliente@empresa.com\n"
                    "Teléfono: 56912345678"
                ),
            ]
        )

    session["state"] = (
        "cotizacion_producto_bloque"
    )

    return build_reply(
        [
            "Gracias. A continuación, por favor envíe la información del producto.",
            (
                "En un SOLO mensaje, indique:\n"
                "Número de parte, marca, descripción detallada y cantidad.\n\n"
                "Ejemplo:\n"
                "Número de parte: ABC123\n"
                "Marca: Siemens\n"
                "Descripción: ...\n"
                "Cantidad: 5"
            ),
        ]
    )