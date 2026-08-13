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

    sin_label = []

    for linea in lineas:

        if ":" not in linea:

            sin_label.append(
                linea
            )

            continue

        etiqueta, valor = linea.split(
            ":",
            1
        )

        etiqueta_norm = normalizar_texto(
            etiqueta
        ).strip().lower()

        valor_clean = valor.strip()

        if not valor_clean:
            continue

        if (
            "nombre" in etiqueta_norm
        ):

            campos["nombre"] = (
                valor_clean
            )

        elif (
            etiqueta_norm in (
                "rut",
                "r.u.t",
                "r u t",
            )
        ):

            campos["rut"] = (
                valor_clean
            )

        elif (
            "factura" in etiqueta_norm
        ):

            campos["numero_factura"] = (
                valor_clean
            )

        elif (
            "descripcion" in etiqueta_norm
            or "detalle" in etiqueta_norm
            or "problema" in etiqueta_norm
        ):

            campos["detalle"] = (
                valor_clean
            )

        else:

            sin_label.append(
                linea
            )

    if not campos["nombre"] and sin_label:

        campos["nombre"] = (
            sin_label.pop(0)
        )

    if not campos["rut"] and sin_label:

        campos["rut"] = (
            sin_label.pop(0)
        )

    if (
        not campos["numero_factura"]
        and sin_label
    ):

        campos["numero_factura"] = (
            sin_label.pop(0)
        )

    if (
        not campos["detalle"]
        and sin_label
    ):

        campos["detalle"] = (
            " ".join(sin_label)
        )

    data.update(
        campos
    )

    faltantes = []

    if not str(
        data.get("nombre", "")
    ).strip():

        faltantes.append(
            "Nombre"
        )

    if not str(
        data.get("rut", "")
    ).strip():

        faltantes.append(
            "RUT"
        )

    if not str(
        data.get("numero_factura", "")
    ).strip():

        faltantes.append(
            "Número de factura"
        )

    if faltantes:

        session["state"] = (
            "postventa_bloque"
        )

        return build_reply(
            "No fue posible registrar correctamente su solicitud de postventa, "
            "ya que faltan datos obligatorios.\n\n"
            "Campos a corregir:\n- "
            + "\n- ".join(faltantes)
            + "\n\n"
            "Por favor, envíe únicamente los datos faltantes o corregidos.\n"
            "Ejemplo:\n"
            "Nombre: Juan Pérez\n"
            "RUT: 12345678-9\n"
            "Número de factura: 12345"
        )

    resumen = (
        "Resumen de su solicitud de postventa:\n"
        f"Nombre: {data['nombre']}\n"
        f"RUT: {mask_rut(data['rut'])}\n"
        f"Número de factura: "
        f"{data['numero_factura']}\n"
        f"Descripción del problema: "
        f"{data['detalle'] or '(sin detalle adicional)'}"
    )

    session["state"] = (
        "menu_principal"
    )

    return build_reply(
        "Gracias. Hemos registrado su solicitud de postventa con el siguiente detalle:\n\n"
        + resumen
        + "\n\nEn unos momentos un operador de Selec revisará su caso."
    )