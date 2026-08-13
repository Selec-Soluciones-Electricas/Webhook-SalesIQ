from conversation.state_machine import (
    build_reply,
    normalizar_texto,
)

from utils.security import mask_rut


def manejar_flujo_postventa_bloque(
    session: dict,
    message_text: str
) -> dict:
    """
    Procesa la información de una solicitud de postventa.
    """

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

    campos = {
        "nombre": data.get(
            "nombre",
            ""
        ),
        "rut": data.get(
            "rut",
            ""
        ),
        "numero_factura": data.get(
            "numero_factura",
            ""
        ),
        "detalle": data.get(
            "detalle",
            ""
        ),
    }

    # =========================================================
    # EXTRAER CAMPOS
    # =========================================================

    for linea in lineas:

        if ":" not in linea:

            if linea:
                campos["detalle"] = (
                    f"{campos['detalle']} {linea}"
                ).strip()

            continue

        etiqueta, valor = linea.split(
            ":",
            1
        )

        etiqueta_norm = normalizar_texto(
            etiqueta
        )

        valor_clean = valor.strip()

        if not valor_clean:
            continue

        if "nombre" in etiqueta_norm:

            campos["nombre"] = valor_clean

        elif etiqueta_norm in (
            "rut",
            "r.u.t",
            "r u t",
        ):

            campos["rut"] = valor_clean

        elif (
            "factura" in etiqueta_norm
            or "n° factura" in etiqueta_norm
        ):

            campos["numero_factura"] = (
                valor_clean
            )

        elif (
            "descripcion" in etiqueta_norm
            or "descripción" in etiqueta_norm
            or "problema" in etiqueta_norm
        ):

            campos["detalle"] = (
                valor_clean
            )

    data.update(campos)

    # =========================================================
    # VALIDAR CAMPOS OBLIGATORIOS
    # =========================================================

    obligatorios = [
        "nombre",
        "rut",
        "numero_factura",
    ]

    nombres_legibles = {
        "nombre": "Nombre",
        "rut": "RUT",
        "numero_factura": "Número de factura",
    }

    faltantes = [
        nombres_legibles[campo]
        for campo in obligatorios
        if not str(
            data.get(
                campo,
                ""
            )
        ).strip()
    ]

    if faltantes:

        session["state"] = (
            "postventa_bloque"
        )

        return build_reply(
            [
                (
                    "No fue posible registrar correctamente "
                    "su solicitud de postventa, ya que "
                    "faltan datos obligatorios."
                ),
                (
                    "Campos a corregir:\n- "
                    + "\n- ".join(faltantes)
                ),
                (
                    "Por favor, envíe únicamente los datos "
                    "faltantes o corregidos. "
                    "Por ejemplo:\n"
                    "Número de factura: 12345"
                ),
            ]
        )

    # =========================================================
    # CONSTRUIR RESUMEN
    # =========================================================

    resumen = (
        "Resumen de su solicitud de postventa:\n"
        f"Nombre: {data['nombre']}\n"
        f"RUT: {mask_rut(data['rut'])}\n"
        f"Número de factura: "
        f"{data['numero_factura']}\n"
        f"Descripción del problema: "
        f"{data['detalle'] or '(sin detalle adicional)'}"
    )

    # =========================================================
    # FINALIZAR
    # =========================================================

    session["state"] = "menu_principal"

    return build_reply(
        [
            (
                "Gracias. Hemos registrado su solicitud "
                "de postventa con el siguiente detalle:"
            ),
            resumen,
            (
                "En unos momentos un operador de Selec "
                "revisará su caso."
            ),
        ]
    )
