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

from services.email_service import (
    enviar_correo_owner,
    enviar_correo_solicitud_incompleta,
)


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


def es_valor_numerico_simple(s: str) -> bool:
    """
    Determina si el texto contiene solamente un número
    simple, permitiendo decimales con punto o coma.

    Ejemplos:

        5
        10
        2,5
        2.5
    """

    return bool(
        re.fullmatch(
            r"\d+(?:[.,]\d+)?",
            str(s or "").strip(),
        )
    )


# =========================================================
# CONVERSIÓN DE NÚMEROS ESCRITOS EN PALABRAS
# =========================================================

UNIDADES_NUMERO = {
    "cero": 0,
    "uno": 1,
    "una": 1,
    "un": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
}

DECENAS_NUMERO = {
    "diez": 10,
    "once": 11,
    "doce": 12,
    "trece": 13,
    "catorce": 14,
    "quince": 15,
    "dieciseis": 16,
    "dieciséis": 16,
    "diecisiete": 17,
    "dieciocho": 18,
    "diecinueve": 19,
    "veinte": 20,
    "treinta": 30,
    "cuarenta": 40,
    "cincuenta": 50,
    "sesenta": 60,
    "setenta": 70,
    "ochenta": 80,
    "noventa": 90,
}

CENTENAS_NUMERO = {
    "cien": 100,
    "ciento": 100,
    "doscientos": 200,
    "doscientas": 200,
    "trescientos": 300,
    "trescientas": 300,
    "cuatrocientos": 400,
    "cuatrocientas": 400,
    "quinientos": 500,
    "quinientas": 500,
    "seiscientos": 600,
    "seiscientas": 600,
    "setecientos": 700,
    "setecientas": 700,
    "ochocientos": 800,
    "ochocientas": 800,
    "novecientos": 900,
    "novecientas": 900,
}


def convertir_palabras_a_numero(texto: str):
    """
    Convierte cantidades escritas en español a números.

    Ejemplos:

        cinco -> 5
        diez -> 10
        quince -> 15
        veinte -> 20
        veinticinco -> 25
        treinta y dos -> 32
        cien -> 100
        ciento veinte -> 120
        doscientos -> 200
        quinientos veinte -> 520

    Retorna None si no puede interpretar el texto.
    """

    texto = normalizar_texto(
        str(texto or "")
    ).strip().lower()

    if not texto:
        return None

    # -----------------------------------------------------
    # LIMPIAR PALABRAS DE APOYO
    # -----------------------------------------------------

    texto = re.sub(
        r"\b(unidades?|uds?|u)\b",
        "",
        texto,
    )

    texto = texto.strip()

    if not texto:
        return None

    # -----------------------------------------------------
    # NÚMERO DIRECTO
    # -----------------------------------------------------

    if es_valor_numerico_simple(texto):

        try:

            return float(
                texto.replace(",", ".")
            )

        except (
            ValueError,
            TypeError,
        ):

            return None

    # -----------------------------------------------------
    # CASOS ESPECIALES VEINTIUNO...
    # -----------------------------------------------------

    veinti = {
        "veintiuno": 21,
        "veintiuna": 21,
        "veintidos": 22,
        "veintidós": 22,
        "veintitres": 23,
        "veintitrés": 23,
        "veinticuatro": 24,
        "veinticinco": 25,
        "veintiseis": 26,
        "veintiséis": 26,
        "veintisiete": 27,
        "veintiocho": 28,
        "veintinueve": 29,
    }

    if texto in veinti:

        return veinti[texto]

    # -----------------------------------------------------
    # SEPARAR PALABRAS
    # -----------------------------------------------------

    palabras = texto.split()

    palabras = [
        palabra
        for palabra in palabras
        if palabra != "y"
    ]

    if not palabras:
        return None

    total = 0
    valor_actual = 0

    for palabra in palabras:

        if palabra in UNIDADES_NUMERO:

            valor_actual += (
                UNIDADES_NUMERO[palabra]
            )

            continue

        if palabra in DECENAS_NUMERO:

            valor_actual += (
                DECENAS_NUMERO[palabra]
            )

            continue

        if palabra in CENTENAS_NUMERO:

            valor_actual += (
                CENTENAS_NUMERO[palabra]
            )

            continue

        return None

    total += valor_actual

    if total <= 0:
        return None

    return total


def extraer_cantidad_desde_texto(
    texto: str,
):
    """
    Busca una cantidad válida dentro del texto.

    IMPORTANTE:

    Esta función NO busca simplemente cualquier número
    dentro del mensaje.

    Primero busca:

        Cantidad: 5
        Cantidad: cinco

    Luego busca líneas que sean exclusivamente:

        5
        cinco
        diez
        veinte

    De esta forma:

        cinco
        Av. Ejemplo 222

    devuelve 5 y NO 222.
    """

    texto = str(
        texto or ""
    ).strip()

    if not texto:
        return None

    # =====================================================
    # 1. BUSCAR "CANTIDAD: ..."
    # =====================================================

    for linea in texto.splitlines():

        linea_clean = linea.strip()

        if not linea_clean:
            continue

        if ":" not in linea_clean:
            continue

        etiqueta, valor = (
            linea_clean.split(
                ":",
                1,
            )
        )

        etiqueta_norm = normalizar_etiqueta(
            etiqueta
        )

        if (
            "cantidad" in etiqueta_norm
            or "qty" in etiqueta_norm
            or "quantity" in etiqueta_norm
        ):

            valor_clean = valor.strip()

            if not valor_clean:
                continue

            # ---------------------------------------------
            # Número
            # ---------------------------------------------

            if es_valor_numerico_simple(
                valor_clean
            ):

                try:

                    return float(
                        valor_clean.replace(
                            ",",
                            ".",
                        )
                    )

                except (
                    ValueError,
                    TypeError,
                ):

                    return None

            # ---------------------------------------------
            # Número escrito
            # ---------------------------------------------

            numero_palabra = (
                convertir_palabras_a_numero(
                    valor_clean
                )
            )

            if numero_palabra is not None:

                return numero_palabra

            # Si existe "Cantidad:" pero el valor
            # no es válido, devolvemos None.
            return None

    # =====================================================
    # 2. BUSCAR UNA LÍNEA QUE SEA SOLO UNA CANTIDAD
    # =====================================================

    for linea in texto.splitlines():

        linea_clean = linea.strip()

        if not linea_clean:
            continue

        # ---------------------------------------------
        # Número
        # ---------------------------------------------

        if es_valor_numerico_simple(
            linea_clean
        ):

            try:

                return float(
                    linea_clean.replace(
                        ",",
                        ".",
                    )
                )

            except (
                ValueError,
                TypeError,
            ):

                continue

        # ---------------------------------------------
        # Número escrito
        # ---------------------------------------------

        numero_palabra = (
            convertir_palabras_a_numero(
                linea_clean
            )
        )

        if numero_palabra is not None:

            return numero_palabra

    # =====================================================
    # 3. NO BUSCAR NÚMEROS DENTRO DE DIRECCIONES
    # =====================================================
    #
    # IMPORTANTE:
    #
    # NO hacemos:
    #
    # re.findall(...)
    #
    # porque eso provocaba:
    #
    # "cinco"
    # "av ejemplo 222"
    #
    # -> 222
    #
    # Si llegamos aquí significa que no encontramos
    # una cantidad claramente identificable.
    # =====================================================

    return None


def normalizar_cantidad(
    cantidad,
):
    """
    Normaliza una cantidad para almacenarla.

    5       -> "5"
    5.0     -> "5"
    2.5     -> "2.5"
    2,5     -> "2.5"
    """

    if cantidad is None:
        return ""

    try:

        valor = float(
            str(cantidad).replace(
                ",",
                ".",
            )
        )

    except (
        ValueError,
        TypeError,
    ):

        return ""

    if valor <= 0:
        return ""

    if valor.is_integer():

        return str(
            int(valor)
        )

    return str(valor)


def normalizar_etiqueta(
    etiqueta: str,
) -> str:
    """
    Normaliza una etiqueta para facilitar
    su comparación.
    """

    return (
        normalizar_texto(
            str(etiqueta or "")
        )
        .strip()
        .lower()
    )


def parece_direccion(
    s: str,
) -> bool:
    """
    Determina si una línea tiene características razonables
    de una dirección de entrega.
    """

    texto = str(
        s or ""
    ).strip()

    if not texto:
        return False

    texto_norm = normalizar_texto(
        texto
    ).strip().lower()

    indicadores = (
        "avenida",
        "av.",
        "av ",
        "calle",
        "camino",
        "pasaje",
        "ruta",
        "carretera",
        "autopista",
        "parcela",
        "sitio",
        "sector",
        "oficina",
        "bodega",
        "local",
        "piso",
        "depto",
        "departamento",
        "block",
        "edificio",
        "condominio",
    )

    if any(
        indicador in texto_norm
        for indicador in indicadores
    ):
        return True

    if re.search(
        r"\b[a-záéíóúñü]{3,}(?:\s+[a-záéíóúñü]{2,})*\s+\d{1,6}\b",
        texto_norm,
    ):
        return True

    return False


# =========================================================
# EXTRACCIÓN DE DATOS DEL PRODUCTO
# =========================================================

def extraer_campos_cotizacion_producto(
    texto: str,
    campos: dict,
) -> dict:

    lineas = [
        linea.strip()
        for linea in texto.splitlines()
        if linea.strip()
    ]

    lineas_sin_label = []

    # =====================================================
    # PROCESAR LÍNEAS CON ETIQUETAS
    # =====================================================

    for linea in lineas:

        if ":" not in linea:

            lineas_sin_label.append(
                linea
            )

            continue

        etiqueta, valor = (
            linea.split(
                ":",
                1,
            )
        )

        etiqueta_norm = (
            normalizar_etiqueta(
                etiqueta
            )
        )

        valor_clean = valor.strip()

        if not valor_clean:
            continue

        # -------------------------------------------------
        # EMPRESA
        # -------------------------------------------------

        if (
            "empresa" in etiqueta_norm
            or "razon social" in etiqueta_norm
            or "razon_social" in etiqueta_norm
        ):

            campos["empresa"] = (
                valor_clean
            )

        # -------------------------------------------------
        # RUT
        # -------------------------------------------------

        elif etiqueta_norm in (
            "rut",
            "r.u.t",
            "r u t",
        ):

            campos["rut"] = (
                valor_clean
            )

        # -------------------------------------------------
        # CONTACTO
        # -------------------------------------------------

        elif (
            "contacto" in etiqueta_norm
            or "nombre contacto" in etiqueta_norm
            or "nombre del contacto" in etiqueta_norm
        ):

            campos["contacto"] = (
                valor_clean
            )

        # -------------------------------------------------
        # CORREO
        # -------------------------------------------------

        elif (
            "correo" in etiqueta_norm
            or "email" in etiqueta_norm
            or "e-mail" in etiqueta_norm
        ):

            campos["correo"] = (
                valor_clean
            )

        # -------------------------------------------------
        # TELÉFONO
        # -------------------------------------------------

        elif (
            "telefono" in etiqueta_norm
            or "celular" in etiqueta_norm
            or "movil" in etiqueta_norm
        ):

            campos["telefono"] = (
                valor_clean
            )

        # -------------------------------------------------
        # NÚMERO DE PARTE
        # -------------------------------------------------

        elif (
            "numero de parte" in etiqueta_norm
            or "numero parte" in etiqueta_norm
            or "n de parte" in etiqueta_norm
            or "n parte" in etiqueta_norm
            or "n° de parte" in etiqueta_norm
            or "nº de parte" in etiqueta_norm
            or "parte number" in etiqueta_norm
            or "part number" in etiqueta_norm
            or etiqueta_norm in (
                "parte",
                "pn",
            )
        ):

            campos["num_parte"] = (
                valor_clean
            )

        # -------------------------------------------------
        # DESCRIPCIÓN
        # -------------------------------------------------

        elif (
            "descripcion" in etiqueta_norm
            or "detalle" in etiqueta_norm
            or "detalle del producto" in etiqueta_norm
            or "descripcion del producto" in etiqueta_norm
        ):

            campos["descripcion"] = (
                valor_clean
            )

        # -------------------------------------------------
        # MARCA
        # -------------------------------------------------

        elif (
            "marca" in etiqueta_norm
            or "brand" in etiqueta_norm
        ):

            campos["marca"] = (
                valor_clean
            )

        # -------------------------------------------------
        # DIRECCIÓN
        # -------------------------------------------------

        elif (
            "direccion de entrega" in etiqueta_norm
            or "direccion entrega" in etiqueta_norm
            or "direccion" in etiqueta_norm
            or "domicilio" in etiqueta_norm
        ):

            campos["direccion_entrega"] = (
                valor_clean
            )

        # -------------------------------------------------
        # CANTIDAD
        # -------------------------------------------------

        elif (
            "cantidad" in etiqueta_norm
            or "qty" in etiqueta_norm
            or "quantity" in etiqueta_norm
        ):

            cantidad = (
                convertir_palabras_a_numero(
                    valor_clean
                )
            )

            if cantidad is not None:

                campos["cantidad"] = (
                    normalizar_cantidad(
                        cantidad
                    )
                )

            else:

                # Guardamos el valor original para
                # que la validación posterior pueda
                # indicar que debe ser numérico.
                campos["cantidad"] = (
                    valor_clean
                )

        # -------------------------------------------------
        # ETIQUETA DESCONOCIDA
        # -------------------------------------------------

        else:

            lineas_sin_label.append(
                linea
            )

    # =====================================================
    # PROCESAR LÍNEAS SIN ETIQUETA
    # =====================================================

    pendientes = []

    for linea in lineas_sin_label:

        linea_clean = linea.strip()

        if not linea_clean:
            continue

        # -------------------------------------------------
        # CANTIDAD
        # -------------------------------------------------

        if not str(
            campos.get(
                "cantidad",
                "",
            )
        ).strip():

            # Número
            if es_valor_numerico_simple(
                linea_clean
            ):

                campos["cantidad"] = (
                    normalizar_cantidad(
                        linea_clean
                    )
                )

                continue

            # Número escrito
            cantidad_palabra = (
                convertir_palabras_a_numero(
                    linea_clean
                )
            )

            if cantidad_palabra is not None:

                campos["cantidad"] = (
                    normalizar_cantidad(
                        cantidad_palabra
                    )
                )

                continue

        pendientes.append(
            linea_clean
        )

    # =====================================================
    # INFERENCIA SIN ETIQUETAS
    # =====================================================

    # -----------------------------------------------------
    # NÚMERO DE PARTE
    # -----------------------------------------------------

    if (
        not str(
            campos.get(
                "num_parte",
                "",
            )
        ).strip()
        and pendientes
    ):

        campos["num_parte"] = (
            pendientes.pop(0)
        )

    # -----------------------------------------------------
    # MARCA
    # -----------------------------------------------------

    if (
        not str(
            campos.get(
                "marca",
                "",
            )
        ).strip()
        and pendientes
    ):

        campos["marca"] = (
            pendientes.pop(0)
        )

    # -----------------------------------------------------
    # DESCRIPCIÓN
    # -----------------------------------------------------

    if (
        not str(
            campos.get(
                "descripcion",
                "",
            )
        ).strip()
        and pendientes
    ):

        candidatos = []

        for linea in pendientes:

            if (
                not str(
                    campos.get(
                        "direccion_entrega",
                        "",
                    )
                ).strip()
                and parece_direccion(
                    linea
                )
            ):

                campos["direccion_entrega"] = (
                    linea
                )

                continue

            candidatos.append(
                linea
            )

        if candidatos:

            campos["descripcion"] = (
                " ".join(
                    candidatos
                ).strip()
            )

        pendientes = []

    # -----------------------------------------------------
    # DIRECCIÓN DE ENTREGA
    # -----------------------------------------------------

    if (
        not str(
            campos.get(
                "direccion_entrega",
                "",
            )
        ).strip()
        and pendientes
    ):

        for linea in pendientes:

            if parece_direccion(
                linea
            ):

                campos["direccion_entrega"] = (
                    linea
                )

                pendientes.remove(
                    linea
                )

                break

    # =====================================================
    # IMPORTANTE
    # =====================================================
    #
    # YA NO HACEMOS ESTO:
    #
    # numeros = re.findall(...)
    # campos["cantidad"] = numeros[-1]
    #
    # Ese código era el causante del problema:
    #
    # "cinco"
    # "av ejemplo 222"
    #
    # terminaba en:
    #
    # cantidad = 222
    #
    # Ahora, si no encontramos una cantidad claramente
    # identificable, dejamos el campo vacío.
    # =====================================================

    if not str(
        campos.get(
            "cantidad",
            "",
        )
    ).strip():

        cantidad_detectada = (
            extraer_cantidad_desde_texto(
                texto
            )
        )

        if cantidad_detectada is not None:

            campos["cantidad"] = (
                normalizar_cantidad(
                    cantidad_detectada
                )
            )

    return campos


# =========================================================
# VALIDACIÓN DE COTIZACIÓN
# =========================================================

def validar_cotizacion_producto(
    data: dict,
) -> list:

    obligatorios = [
        "empresa",
        "rut",
        "contacto",
        "correo",
        "telefono",
        "num_parte",
        "cantidad",
        "direccion_entrega",
    ]

    nombres_legibles = {
        "empresa": "Nombre de la empresa",
        "rut": "RUT",
        "contacto": "Nombre de contacto",
        "correo": "Correo",
        "telefono": "Teléfono",
        "num_parte": "Número de parte",
        "cantidad": "Cantidad",
        "direccion_entrega": "Dirección de entrega",
    }

    faltantes = [
        nombres_legibles[campo]
        for campo in obligatorios
        if not str(
            data.get(
                campo,
                "",
            )
        ).strip()
    ]

    # =====================================================
    # VALIDAR CANTIDAD
    # =====================================================

    cantidad_raw = str(
        data.get(
            "cantidad",
            "",
        )
    ).strip()

    if not cantidad_raw:

        if "Cantidad" not in faltantes:

            faltantes.append(
                "Cantidad"
            )

    else:

        # -------------------------------------------------
        # Primero intentar número escrito
        # -------------------------------------------------

        cantidad_palabra = (
            convertir_palabras_a_numero(
                cantidad_raw
            )
        )

        if cantidad_palabra is not None:

            cantidad_raw = (
                normalizar_cantidad(
                    cantidad_palabra
                )
            )

            data["cantidad"] = (
                cantidad_raw
            )

        else:

            try:

                cantidad_val = float(
                    cantidad_raw.replace(
                        ",",
                        ".",
                    )
                )

                if cantidad_val <= 0:

                    faltantes.append(
                        "Cantidad (debe ser mayor a 0)"
                    )

                else:

                    data["cantidad"] = (
                        normalizar_cantidad(
                            cantidad_val
                        )
                    )

            except (
                ValueError,
                TypeError,
            ):

                faltantes.append(
                    "Cantidad (valor numérico)"
                )

    return faltantes


# =========================================================
# ALERTA DE SOLICITUD INCOMPLETA
# =========================================================

def notificar_solicitud_incompleta(
    session: dict,
    data: dict,
    faltantes: list,
    ultimo_mensaje: str,
):

    if session.get(
        "alerta_cotizacion_incompleta_enviada",
        False,
    ):

        return

    response = (
        enviar_correo_solicitud_incompleta(
            data,
            faltantes,
            ultimo_mensaje=ultimo_mensaje,
        )
    )

    if (
        response is not None
        and response.status_code in (
            200,
            201,
        )
    ):

        session[
            "alerta_cotizacion_incompleta_enviada"
        ] = True


# =========================================================
# RESUMEN DE COTIZACIÓN
# =========================================================

def construir_resumen_cotizacion(
    data: dict,
) -> str:

    return (
        "Resumen de su solicitud de cotización:\n"
        f"Nombre de la empresa: "
        f"{data.get('empresa', '')}\n"
        f"RUT: "
        f"{mask_rut(data.get('rut', ''))}\n"
        f"Nombre de contacto: "
        f"{data.get('contacto', '')}\n"
        f"Correo: "
        f"{mask_email(data.get('correo', ''))}\n"
        f"Teléfono: "
        f"{mask_phone(data.get('telefono', ''))}\n"
        f"Número de parte: "
        f"{data.get('num_parte', '')}\n"
        f"Marca: "
        f"{data.get('marca', '')}\n"
        f"Descripción: "
        f"{data.get('descripcion', '')}\n"
        f"Cantidad: "
        f"{data.get('cantidad', '')}\n"
        f"Dirección de entrega: "
        f"{data.get('direccion_entrega', '')}"
    )


# =========================================================
# REGISTRO EN ZOHO
# =========================================================

def registrar_cotizacion_en_zoho(
    data: dict,
):

    owner = normalizar_owner(
        data.get(
            "owner_asignado"
        )
    )

    account_id = (
        obtener_o_crear_account(
            data,
            owner=owner,
        )
    )

    contact_id = (
        obtener_o_crear_contact(
            data,
            account_id=account_id,
            owner=owner,
        )
    )

    deal_resp, deal_id = (
        crear_deal_en_zoho(
            data,
            account_id=account_id,
            contact_id=contact_id,
            owner=owner,
        )
    )

    return (
        owner,
        deal_resp,
        deal_id,
    )


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

    if deal_id:

        enviar_correo_owner(
            owner,
            deal_id,
            f"Cotización - "
            f"{data.get('empresa') or 'Sin empresa'}",
            data,
        )

    session["state"] = (
        "menu_principal"
    )

    session["data"] = {}

    session["primer_correo_enviado"] = (
        False
    )

    if deal_id:

        return build_reply(
            "Gracias. Hemos registrado su solicitud "
            "con el siguiente detalle:\n\n"
            + resumen
            + "\n\nUn ejecutivo de Selec se pondrá "
            "en contacto con usted."
        )

    return build_reply(
        "Gracias. Hemos recibido su solicitud, "
        "pero ocurrió un inconveniente al registrarla "
        "automáticamente en nuestro sistema.\n\n"
        + resumen
        + "\n\nUn ejecutivo revisará su caso manualmente "
        "y se pondrá en contacto con usted."
    )


# =========================================================
# FLUJO DE COTIZACIÓN - PRODUCTO
# =========================================================

def manejar_flujo_cotizacion_bloque(
    session: dict,
    message_text: str,
) -> dict:

    data = session.setdefault(
        "data",
        {},
    )

    texto = message_text or ""

    # -----------------------------------------------------
    # CAMPOS EXISTENTES
    # -----------------------------------------------------

    campos = {
        "empresa": data.get(
            "empresa",
            "",
        ),
        "rut": data.get(
            "rut",
            "",
        ),
        "contacto": data.get(
            "contacto",
            "",
        ),
        "correo": data.get(
            "correo",
            "",
        ),
        "telefono": data.get(
            "telefono",
            "",
        ),
        "num_parte": data.get(
            "num_parte",
            "",
        ),
        "marca": data.get(
            "marca",
            "",
        ),
        "descripcion": data.get(
            "descripcion",
            "",
        ),
        "cantidad": data.get(
            "cantidad",
            "",
        ),
        "direccion_entrega": data.get(
            "direccion_entrega",
            "",
        ),
    }

    # -----------------------------------------------------
    # EXTRAER PRODUCTO
    # -----------------------------------------------------

    campos = (
        extraer_campos_cotizacion_producto(
            texto,
            campos,
        )
    )

    data.update(
        campos
    )

    # -----------------------------------------------------
    # VALIDAR
    # -----------------------------------------------------

    faltantes = (
        validar_cotizacion_producto(
            data
        )
    )

    if faltantes:

        notificar_solicitud_incompleta(
            session,
            data,
            faltantes,
            texto,
        )

        session["state"] = (
            "cotizacion_bloque"
        )

        # =================================================
        # EJEMPLOS
        # =================================================

        ejemplos = {
            "Nombre de la empresa":
                "Nombre de la empresa: Empresa Ejemplo",

            "RUT":
                "RUT: 12345678-9",

            "Nombre de contacto":
                "Nombre de contacto: Juan Pérez",

            "Correo":
                "Correo: cliente@empresa.com",

            "Correo (formato inválido)":
                "Correo: cliente@empresa.com",

            "Teléfono":
                "Teléfono: 56912345678",

            "Número de parte":
                "Número de parte: ABC123",

            "Marca":
                "Marca: Siemens",

            "Descripción":
                "Descripción: Tornillo de acero inoxidable",

            "Cantidad":
                "Cantidad: 5",

            "Cantidad (valor numérico)":
                "Cantidad: 5",

            "Cantidad (debe ser mayor a 0)":
                "Cantidad: 5",

            "Dirección de entrega":
                "Dirección de entrega: Av. Ejemplo 1234, Santiago",
        }

        ejemplos_faltantes = []

        for campo in faltantes:

            ejemplo = ejemplos.get(
                campo
            )

            if ejemplo:

                ejemplos_faltantes.append(
                    ejemplo
                )

        mensaje = (
            "No fue posible registrar su solicitud, "
            "ya que existen campos obligatorios "
            "faltantes o inválidos.\n\n"
            "Campos a corregir:\n- "
            + "\n- ".join(
                faltantes
            )
            + "\n\n"
            "Por favor, envíe únicamente los datos "
            "faltantes o corregidos."
        )

        if ejemplos_faltantes:

            mensaje += (
                "\n\nEjemplo para completar/corregir:\n"
                + "\n".join(
                    ejemplos_faltantes
                )
            )

        return build_reply(
            mensaje
        )

    # =====================================================
    # RESUMEN
    # =====================================================

    resumen = (
        construir_resumen_cotizacion(
            data
        )
    )

    # =====================================================
    # REGISTRAR EN ZOHO
    # =====================================================

    (
        owner,
        deal_resp,
        deal_id,
    ) = registrar_cotizacion_en_zoho(
        data
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

    sin_label = []

    for linea in lineas:

        if ":" not in linea:

            sin_label.append(
                linea
            )

            continue

        etiqueta, valor = (
            linea.split(
                ":",
                1,
            )
        )

        etiqueta_norm = (
            normalizar_etiqueta(
                etiqueta
            )
        )

        valor_clean = valor.strip()

        if not valor_clean:
            continue

        # -------------------------------------------------
        # EMPRESA
        # -------------------------------------------------

        if (
            "empresa" in etiqueta_norm
            or "razon social" in etiqueta_norm
            or "razon_social" in etiqueta_norm
        ):

            campos["empresa"] = (
                valor_clean
            )

        # -------------------------------------------------
        # RUT
        # -------------------------------------------------

        elif etiqueta_norm in (
            "rut",
            "r.u.t",
            "r u t",
        ):

            campos["rut"] = (
                valor_clean
            )

        # -------------------------------------------------
        # CONTACTO
        # -------------------------------------------------

        elif (
            "contacto" in etiqueta_norm
            or "nombre contacto" in etiqueta_norm
            or "nombre del contacto" in etiqueta_norm
        ):

            campos["contacto"] = (
                valor_clean
            )

        # -------------------------------------------------
        # CORREO
        # -------------------------------------------------

        elif (
            "correo" in etiqueta_norm
            or "email" in etiqueta_norm
            or "e-mail" in etiqueta_norm
        ):

            campos["correo"] = (
                valor_clean
            )

        # -------------------------------------------------
        # TELÉFONO
        # -------------------------------------------------

        elif (
            "telefono" in etiqueta_norm
            or "celular" in etiqueta_norm
            or "movil" in etiqueta_norm
        ):

            campos["telefono"] = (
                valor_clean
            )

        else:

            sin_label.append(
                linea
            )

    return sin_label


# =========================================================
# INFERENCIA DE DATOS DE EMPRESA
# =========================================================

def inferir_datos_empresa(
    sin_label: list,
    campos: dict,
):

    # =====================================================
    # 1. CORREO
    # =====================================================

    for linea in list(
        sin_label
    ):

        if not campos.get(
            "correo"
        ):

            email = extraer_email(
                linea
            )

            if email:

                campos["correo"] = (
                    email
                )

                sin_label.remove(
                    linea
                )

    # =====================================================
    # 2. RUT
    # =====================================================

    if not str(
        campos.get(
            "rut",
            "",
        )
    ).strip():

        for linea in list(
            sin_label
        ):

            linea_clean = (
                linea.strip()
            )

            if not linea_clean:
                continue

            if es_rut_plausible(
                linea_clean
            ):

                campos["rut"] = (
                    linea_clean
                )

                sin_label.remove(
                    linea
                )

                break

    # =====================================================
    # 3. TELÉFONO
    # =====================================================

    if not str(
        campos.get(
            "telefono",
            "",
        )
    ).strip():

        for linea in list(
            sin_label
        ):

            linea_clean = (
                linea.strip()
            )

            if not linea_clean:
                continue

            if es_telefono_plausible(
                linea_clean
            ):

                campos["telefono"] = (
                    limpiar_digitos(
                        linea_clean
                    )
                )

                sin_label.remove(
                    linea
                )

                break

    # =====================================================
    # 4. SI FALTA RUT Y EL USUARIO ENVIÓ UN NÚMERO
    # =====================================================

    if not str(
        campos.get(
            "rut",
            "",
        )
    ).strip():

        for linea in list(
            sin_label
        ):

            linea_clean = (
                linea.strip()
            )

            if es_mayormente_numerico(
                linea_clean
            ):

                campos["rut"] = (
                    linea_clean
                )

                sin_label.remove(
                    linea
                )

                break

    # =====================================================
    # 5. EMPRESA
    # =====================================================

    if not str(
        campos.get(
            "empresa",
            "",
        )
    ).strip():

        for linea in list(
            sin_label
        ):

            if extraer_email(
                linea
            ):
                continue

            if es_mayormente_numerico(
                linea
            ):
                continue

            if es_telefono_plausible(
                linea
            ):
                continue

            campos["empresa"] = (
                linea
            )

            sin_label.remove(
                linea
            )

            break

    # =====================================================
    # 6. CONTACTO
    # =====================================================

    if not str(
        campos.get(
            "contacto",
            "",
        )
    ).strip():

        for linea in list(
            sin_label
        ):

            if extraer_email(
                linea
            ):
                continue

            if es_mayormente_numerico(
                linea
            ):
                continue

            if es_telefono_plausible(
                linea
            ):
                continue

            campos["contacto"] = (
                linea
            )

            sin_label.remove(
                linea
            )

            break

    return campos


# =========================================================
# VALIDACIÓN DE DATOS DE EMPRESA
# =========================================================

def validar_datos_empresa(
    data: dict,
) -> list:

    faltantes = []

    # -----------------------------------------------------
    # EMPRESA
    # -----------------------------------------------------

    if not str(
        data.get(
            "empresa",
            "",
        )
    ).strip():

        faltantes.append(
            "Nombre de la empresa"
        )

    # -----------------------------------------------------
    # RUT
    # -----------------------------------------------------

    if not str(
        data.get(
            "rut",
            "",
        )
    ).strip():

        faltantes.append(
            "RUT"
        )

    # -----------------------------------------------------
    # CONTACTO
    # -----------------------------------------------------

    if not str(
        data.get(
            "contacto",
            "",
        )
    ).strip():

        faltantes.append(
            "Nombre de contacto"
        )

    # -----------------------------------------------------
    # CORREO
    # -----------------------------------------------------

    correo_val = str(
        data.get(
            "correo",
            "",
        )
    ).strip()

    if not correo_val:

        faltantes.append(
            "Correo"
        )

    elif not re.search(
        r"[\w\.-]+@[\w\.-]+\.\w+",
        correo_val,
    ):

        faltantes.append(
            "Correo (formato inválido)"
        )

    # -----------------------------------------------------
    # TELÉFONO
    # -----------------------------------------------------

    telefono_val = str(
        data.get(
            "telefono",
            "",
        )
    ).strip()

    if not telefono_val:

        faltantes.append(
            "Teléfono"
        )

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

    # -----------------------------------------------------
    # CAMPOS EXISTENTES
    # -----------------------------------------------------

    campos = {
        "empresa": data.get(
            "empresa",
            "",
        ),
        "rut": data.get(
            "rut",
            "",
        ),
        "contacto": data.get(
            "contacto",
            "",
        ),
        "correo": data.get(
            "correo",
            "",
        ),
        "telefono": data.get(
            "telefono",
            "",
        ),
    }

    # -----------------------------------------------------
    # EXTRAER DATOS CON ETIQUETAS
    # -----------------------------------------------------

    sin_label = (
        extraer_campos_empresa(
            lineas,
            campos,
        )
    )

    # -----------------------------------------------------
    # INFERIR DATOS SIN ETIQUETAS
    # -----------------------------------------------------

    campos = (
        inferir_datos_empresa(
            sin_label,
            campos,
        )
    )

    data.update(
        campos
    )

    # -----------------------------------------------------
    # VALIDAR
    # -----------------------------------------------------

    faltantes = (
        validar_datos_empresa(
            data
        )
    )

    if faltantes:

        notificar_solicitud_incompleta(
            session,
            data,
            faltantes,
            texto,
        )

        session["state"] = (
            "cotizacion_empresa_bloque"
        )

        # =================================================
        # EJEMPLOS DINÁMICOS
        # =================================================

        ejemplos = []

        if "Nombre de la empresa" in faltantes:

            ejemplos.append(
                "Nombre de la empresa: "
                "Empresa Ejemplo"
            )

        if "RUT" in faltantes:

            ejemplos.append(
                "RUT: 12345678-9"
            )

        if "Nombre de contacto" in faltantes:

            ejemplos.append(
                "Nombre de contacto: "
                "Juan Pérez"
            )

        if "Correo" in faltantes:

            ejemplos.append(
                "Correo: cliente@empresa.com"
            )

        if (
            "Correo (formato inválido)"
            in faltantes
        ):

            ejemplos.append(
                "Correo: cliente@empresa.com"
            )

        if "Teléfono" in faltantes:

            ejemplos.append(
                "Teléfono: 56912345678"
            )

        # -------------------------------------------------
        # CONSTRUIR EJEMPLO
        # -------------------------------------------------

        ejemplo = "\n".join(
            ejemplos
        )

        mensaje = (
            "No fue posible registrar la información, "
            "ya que faltan datos obligatorios o el correo "
            "presenta un formato inválido.\n\n"
            "Campos a corregir:\n- "
            + "\n- ".join(
                faltantes
            )
            + "\n\n"
            "Por favor, envíe únicamente los campos "
            "faltantes o corregidos."
        )

        if ejemplo:

            mensaje += (
                "\n\nEjemplo para completar/corregir:\n"
                + ejemplo
            )

        return build_reply(
            mensaje
        )

    # -----------------------------------------------------
    # PASAR A PRODUCTO
    # -----------------------------------------------------

    session["state"] = (
        "cotizacion_producto_bloque"
    )

    return build_reply(
        "Gracias. A continuación, por favor envíe "
        "la información del producto.\n\n"
        "En un SOLO mensaje, indique:\n"
        "Número de parte, marca, descripción detallada, "
        "cantidad y dirección de entrega.\n\n"
        "La cantidad puede escribirse con números "
        "o con palabras.\n\n"
        "Ejemplo:\n"
        "Número de parte: ABC123\n"
        "Marca: Siemens\n"
        "Descripción: test\n"
        "Cantidad: 5\n"
        "Dirección de entrega: Av. Ejemplo 1234, Santiago"
    )