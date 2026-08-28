import re

from conversation.state_machine import (
    build_reply,
    normalizar_texto,
)

from utils.security import mask_rut

from utils.email_postventa import enviar_correo_postventa


# =========================================================
# DETECTORES PARA TEXTOS SIN ETIQUETA
# =========================================================

def calcular_dv_rut(cuerpo: str) -> str:
    """
    Calcula el dígito verificador de un RUT chileno.
    """

    suma = 0
    multiplicador = 2

    for digito in reversed(cuerpo):

        suma += int(digito) * multiplicador

        multiplicador += 1

        if multiplicador > 7:
            multiplicador = 2

    resultado = 11 - (suma % 11)

    if resultado == 11:
        return "0"

    if resultado == 10:
        return "K"

    return str(resultado)


def normalizar_rut_ingresado(
    texto: str,
    validar_dv: bool = False
) -> str:
    """
    Acepta:

    22333445
    2233344-5
    2.233.344-5

    También acepta RUT terminados en K.

    Si validar_dv=True, comprueba matemáticamente
    el dígito verificador.
    """

    valor = (
        texto or ""
    ).strip()

    limpio = re.sub(
        r"[\.\-\s]",
        "",
        valor
    ).upper()

    # Cuerpo de 7 u 8 dígitos + DV
    if not re.fullmatch(
        r"\d{7,8}[0-9K]",
        limpio
    ):
        return ""

    cuerpo = limpio[:-1]
    dv_ingresado = limpio[-1]

    if validar_dv:

        dv_correcto = calcular_dv_rut(
            cuerpo
        )

        if dv_ingresado != dv_correcto:
            return ""

    return f"{cuerpo}-{dv_ingresado}"

def parece_rut(texto: str) -> bool:
    """
    Determina si corresponde a un RUT chileno
    válido, incluyendo RUT sin puntos ni guion.
    """

    return bool(
        normalizar_rut_ingresado(
            texto,
            validar_dv=True
        )
    )


def parece_descripcion(texto: str) -> bool:
    """
    Intenta detectar si una frase corresponde
    a la descripción de una situación de postventa.
    """

    texto_norm = normalizar_texto(
        texto or ""
    ).lower().strip()

    palabras_clave = (
        "falla",
        "fallo",
        "problema",
        "situacion",
        "producto",
        "equipo",
        "recibido",
        "recibi",
        "funciona",
        "funcionar",
        "danado",
        "dano",
        "roto",
        "defectuoso",
        "error",
        "inconveniente",
        "averia",
        "reclamo",
        "garantia",
        "no prende",
        "no enciende",
        "no funciona",
    )

    if any(
        palabra in texto_norm
        for palabra in palabras_clave
    ):
        return True

    # Una frase larga también es mucho más probable
    # que sea una descripción que un nombre.
    return len(
        texto_norm.split()
    ) >= 6


def parece_nombre(texto: str) -> bool:
    """
    Detecta de manera simple si un texto puede
    corresponder al nombre de una persona.
    """

    texto_norm = normalizar_texto(
        texto or ""
    ).strip()

    if not texto_norm:
        return False

    if any(
        caracter.isdigit()
        for caracter in texto_norm
    ):
        return False

    if parece_descripcion(
        texto_norm
    ):
        return False

    palabras = texto_norm.split()

    return (
        1 <= len(palabras) <= 5
    )


def parece_factura_oc(texto: str) -> bool:
    """
    Detecta un número de factura u orden de compra
    enviado sin etiqueta.

    Ejemplos:
    12345
    OC-12345
    OC 12345
    FAC-4589
    """

    valor = (
        texto or ""
    ).strip()

    texto_norm = normalizar_texto(
        valor
    ).lower()

    if (
        texto_norm.startswith("oc ")
        or texto_norm.startswith("oc-")
        or texto_norm.startswith("oc#")
        or "orden de compra" in texto_norm
    ):
        return True

    if (
        texto_norm.startswith("fac ")
        or texto_norm.startswith("fac-")
        or texto_norm.startswith("factura ")
    ):
        return True

    # Código/número relativamente corto que
    # contenga al menos un dígito.
    if (
        len(valor) <= 30
        and any(
            caracter.isdigit()
            for caracter in valor
        )
    ):
        return True

    return False


# =========================================================
# FLUJO DE POSTVENTA
# =========================================================

def manejar_flujo_postventa_bloque(
    session: dict,
    message_text: str
) -> dict:

    data = session.setdefault(
        "data",
        {}
    )

    texto = (
        message_text or ""
    ).strip()

    lineas = [
        linea.strip()
        for linea in texto.splitlines()
        if linea.strip()
    ]

    # Conservamos la información ya entregada
    # anteriormente por el cliente.
    campos = {

        "nombre":
            data.get(
                "nombre",
                ""
            ),

        "rut":
            data.get(
                "rut",
                ""
            ),

        "numero_factura":
            data.get(
                "numero_factura",
                ""
            ),

        "detalle":
            data.get(
                "detalle",
                ""
            ),
    }

    sin_etiqueta = []

    # =====================================================
    # 1. PROCESAR CAMPOS QUE VIENEN CON ETIQUETA
    # =====================================================

    for linea in lineas:

        if ":" not in linea:

            sin_etiqueta.append(
                linea
            )

            continue

        etiqueta, valor = linea.split(
            ":",
            1
        )

        etiqueta_norm = normalizar_texto(
            etiqueta
        ).lower().strip()

        valor_clean = valor.strip()

        if not valor_clean:
            continue

        # -------------------------------------------------
        # NOMBRE
        # -------------------------------------------------

        if "nombre" in etiqueta_norm:

            campos["nombre"] = (
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

            rut_detectado = normalizar_rut_ingresado(
                valor_clean
            )

            campos["rut"] = (
                rut_detectado
                if rut_detectado
                else valor_clean
            )

        # -------------------------------------------------
        # FACTURA / ORDEN DE COMPRA
        # -------------------------------------------------

        elif (
            "factura" in etiqueta_norm
            or "orden de compra" in etiqueta_norm
            or "numero de orden" in etiqueta_norm
            or etiqueta_norm in (
                "oc",
                "o.c",
                "o.c.",
                "o c",
            )
        ):

            campos["numero_factura"] = (
                valor_clean
            )

        # -------------------------------------------------
        # DESCRIPCIÓN
        # -------------------------------------------------

        elif (
            "descripcion" in etiqueta_norm
            or "situacion" in etiqueta_norm
            or "detalle" in etiqueta_norm
            or "problema" in etiqueta_norm
        ):

            campos["detalle"] = (
                valor_clean
            )

        else:

            sin_etiqueta.append(
                linea
            )

    # =====================================================
    # 2. PROCESAR TEXTOS SIN ETIQUETA
    # =====================================================

    for linea in sin_etiqueta:

        # -------------------------------------------------
        # RUT
        # -------------------------------------------------

        if not campos["rut"]:

            # Primero intentamos reconocer un RUT
            # chileno válido mediante su dígito verificador.
            rut_valido = normalizar_rut_ingresado(
                linea,
                validar_dv=True
            )

            if rut_valido:
                campos["rut"] = rut_valido
                continue

            # Si los demás campos ya están completos,
            # entonces sabemos por contexto que el dato
            # que falta es el RUT.
            solo_falta_rut = (
                bool(str(campos["nombre"]).strip())
                and bool(str(campos["numero_factura"]).strip())
                and bool(str(campos["detalle"]).strip())
            )

            if solo_falta_rut:

                rut_flexible = normalizar_rut_ingresado(
                    linea,
                    validar_dv=False
                )

                if rut_flexible:
                    campos["rut"] = rut_flexible
                    continue

            # Si el usuario escribió puntos, guion
            # o un dígito verificador K, también
            # lo tratamos como RUT explícito.
            rut_explicito = (
                "-" in linea
                or "." in linea
                or linea.upper().endswith("K")
            )

            if rut_explicito:

                rut_flexible = normalizar_rut_ingresado(
                    linea,
                    validar_dv=False
                )

                if rut_flexible:
                    campos["rut"] = rut_flexible
                    continue

        # -------------------------------------------------
        # DESCRIPCIÓN DE LA SITUACIÓN
        # -------------------------------------------------

        if (
            not campos["detalle"]
            and parece_descripcion(linea)
        ):
            campos["detalle"] = linea
            continue

        # -------------------------------------------------
        # FACTURA / ORDEN DE COMPRA
        # -------------------------------------------------

        if (
            not campos["numero_factura"]
            and parece_factura_oc(linea)
        ):
            campos["numero_factura"] = linea
            continue

        # -------------------------------------------------
        # NOMBRE
        # -------------------------------------------------

        if (
            not campos["nombre"]
            and parece_nombre(linea)
        ):
            campos["nombre"] = linea
            continue

    # =====================================================
    # 3. GUARDAR INFORMACIÓN RECONOCIDA
    # =====================================================

    data.update(
        campos
    )

    # =====================================================
    # 4. DETECTAR EXACTAMENTE QUÉ FALTA
    # =====================================================

    faltantes = []

    if not str(
        data.get(
            "nombre",
            ""
        )
    ).strip():

        faltantes.append(
            "Nombre"
        )

    if not str(
        data.get(
            "rut",
            ""
        )
    ).strip():

        faltantes.append(
            "RUT"
        )

    if not str(
        data.get(
            "numero_factura",
            ""
        )
    ).strip():

        faltantes.append(
            "Número de factura y/o Orden de compra"
        )

    if not str(
        data.get(
            "detalle",
            ""
        )
    ).strip():

        faltantes.append(
            "Descripción de la situación"
        )

    # =====================================================
    # 5. SI FALTAN DATOS
    # =====================================================

    if faltantes:

        session["state"] = (
            "postventa_bloque"
        )

        ejemplos = {

            "Nombre":
                "Nombre: Juan Pérez",

            "RUT":
                "RUT: 12345678-9",

            "Número de factura y/o Orden de compra":
                (
                    "Número de factura y/o "
                    "Orden de compra: 12345"
                ),

            "Descripción de la situación":
                (
                    "Descripción de la situación: "
                    "El producto recibido presenta una falla "
                    "y no funciona correctamente."
                ),
        }

        ejemplo_faltantes = "\n".join(
            ejemplos[campo]
            for campo in faltantes
        )

        return build_reply(
            (
                "No fue posible registrar correctamente "
                "su solicitud de postventa, ya que faltan "
                "datos obligatorios.\n\n"

                "Campos faltantes:\n- "
                + "\n- ".join(
                    faltantes
                )
                + "\n\n"

                "Por favor, envíe únicamente los datos "
                "faltantes o corregidos.\n"

                "Ejemplo:\n"
                + ejemplo_faltantes
            )
        )

        # =====================================================
    # 6. TODO COMPLETO
    # =====================================================

    resumen = (
        "Resumen de su solicitud de postventa:\n"
        f"Nombre: {data['nombre']}\n"
        f"RUT: {mask_rut(data['rut'])}\n"
        "Número de factura y/o Orden de compra: "
        f"{data['numero_factura']}\n"
        "Descripción de la situación: "
        f"{data['detalle']}"
    )

    # =====================================================
    # 7. ENVIAR CORREO DE POSTVENTA
    # =====================================================

    try:

        enviar_correo_postventa(
            data
        )

    except Exception as error:

        print(
            "[POSTVENTA] Error enviando correo:",
            error
        )

        # Conservamos toda la información que ya
        # entregó el cliente.
        #
        # De esta manera NO tendrá que completar
        # nuevamente el formulario.

        session["state"] = (
            "postventa_bloque"
        )

        return build_reply(
            (
                "Sus datos fueron recibidos correctamente, "
                "pero ocurrió un inconveniente al registrar "
                "la solicitud de postventa.\n\n"
                "Por favor, intente nuevamente en unos momentos."
            )
        )

    # =====================================================
    # 8. CORREO ENVIADO / SOLICITUD REGISTRADA
    # =====================================================

    session["state"] = (
        "menu_principal"
    )

    return build_reply(
        (
            "Gracias. Hemos registrado su solicitud "
            "de postventa con el siguiente detalle:\n\n"
            + resumen
            + "\n\n"
            "Gracias por la información, será contactado "
            "en breve por nuestro personal de postventa."
        )
    )