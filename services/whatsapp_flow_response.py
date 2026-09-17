import json


# =========================================================
# CONVERTIR RESPUESTA DEL FLOW
# =========================================================

def normalizar_respuesta_flow(
    respuesta,
) -> dict:
    """
    Convierte la respuesta recibida desde WhatsApp Flow
    al formato que ya utiliza el backend de SELEC.

    Puede recibir:
    - dict
    - JSON en texto
    """

    if isinstance(
        respuesta,
        str,
    ):

        respuesta = json.loads(
            respuesta
        )

    if not isinstance(
        respuesta,
        dict,
    ):

        raise ValueError(
            "La respuesta del Flow no tiene un formato válido."
        )

    tipo = str(
        respuesta.get(
            "tipo_solicitud",
            "",
        )
    ).strip().lower()

    # =====================================================
    # COTIZACIÓN
    # =====================================================

    if tipo == "cotizacion":

        return {
            "tipo_solicitud": "cotizacion",

            "empresa": str(
                respuesta.get(
                    "empresa",
                    "",
                )
            ).strip(),

            "rut": str(
                respuesta.get(
                    "rut",
                    "",
                )
            ).strip(),

            "contacto": str(
                respuesta.get(
                    "contacto",
                    "",
                )
            ).strip(),

            "correo": str(
                respuesta.get(
                    "correo",
                    "",
                )
            ).strip(),

            "telefono": str(
                respuesta.get(
                    "telefono",
                    "",
                )
            ).strip(),

            "num_parte": str(
                respuesta.get(
                    "numero_parte",
                    "",
                )
            ).strip(),

            "marca": str(
                respuesta.get(
                    "marca",
                    "",
                )
            ).strip(),

            "descripcion": str(
                respuesta.get(
                    "descripcion",
                    "",
                )
            ).strip(),

            "cantidad": str(
                respuesta.get(
                    "cantidad",
                    "",
                )
            ).strip(),

            "direccion_entrega": str(
                respuesta.get(
                    "direccion_entrega",
                    "",
                )
            ).strip(),
        }

    # =====================================================
    # POSTVENTA
    # =====================================================

    if tipo == "postventa":

        return {
            "tipo_solicitud": "postventa",

            "nombre": str(
                respuesta.get(
                    "nombre",
                    "",
                )
            ).strip(),

            "rut": str(
                respuesta.get(
                    "rut",
                    "",
                )
            ).strip(),

            "numero_factura": str(
                respuesta.get(
                    "factura_oc",
                    "",
                )
            ).strip(),

            "detalle": str(
                respuesta.get(
                    "descripcion",
                    "",
                )
            ).strip(),
        }

    raise ValueError(
        "Tipo de solicitud desconocido."
    )


# =========================================================
# TEST LOCAL
# =========================================================

if __name__ == "__main__":

    prueba_cotizacion = {
        "tipo_solicitud": "cotizacion",
        "empresa": "SELEC SPA",
        "rut": "76123456-7",
        "contacto": "Juan Pérez",
        "correo": "juan@empresa.cl",
        "telefono": "+56912345678",
        "numero_parte": "ABC123",
        "marca": "Siemens",
        "descripcion": "Producto de prueba",
        "cantidad": "5",
        "direccion_entrega": (
            "Av. Pedro de Valdivia 273, Santiago"
        ),
    }

    resultado = normalizar_respuesta_flow(
        prueba_cotizacion
    )

    print(
        "=== RESPUESTA NORMALIZADA ==="
    )

    for clave, valor in resultado.items():

        print(
            f"{clave}: {valor}"
        )