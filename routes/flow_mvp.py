from flask import (
    Blueprint,
    jsonify,
    request,
)

from services.whatsapp_flow_service import (
    cargar_flow_json,
)

from services.whatsapp_flow_response import (
    normalizar_respuesta_flow,
)

from conversation.quotation import (
    registrar_cotizacion_en_zoho,
    validar_cotizacion_producto,
)

from services.email_service import (
    enviar_correo_owner,
)

from utils.email_postventa import (
    enviar_correo_postventa,
)


flow_mvp_bp = Blueprint(
    "flow_mvp",
    __name__,
)


# =========================================================
# OBTENER FLOW JSON
# =========================================================

@flow_mvp_bp.get("/api/flow-mvp")
def obtener_flow_mvp():

    try:

        flow = cargar_flow_json()

        return jsonify(
            {
                "success": True,
                "flow": flow,
            }
        )

    except Exception as error:

        print(
            "[FLOW MVP] Error cargando Flow:",
            error,
        )

        return jsonify(
            {
                "success": False,
                "error": str(error),
            }
        ), 500


# =========================================================
# VALIDACIONES
# =========================================================

def validar_cotizacion_flow(
    datos: dict,
) -> list:

    faltantes = list(
        validar_cotizacion_producto(
            datos
        )
    )

    # En el Flow Marca y Descripción
    # también son obligatorios.
    adicionales = {
        "marca": "Marca",
        "descripcion": "Descripción",
    }

    for campo, nombre in adicionales.items():

        if not str(
            datos.get(
                campo,
                ""
            )
        ).strip():

            if nombre not in faltantes:

                faltantes.append(
                    nombre
                )

    return faltantes


def validar_postventa_flow(
    datos: dict,
) -> list:

    obligatorios = {
        "nombre": "Nombre",
        "rut": "RUT",
        "numero_factura": (
            "Número de factura y/o Orden de compra"
        ),
        "detalle": (
            "Descripción de la situación"
        ),
    }

    return [
        nombre
        for campo, nombre
        in obligatorios.items()
        if not str(
            datos.get(
                campo,
                ""
            )
        ).strip()
    ]


# =========================================================
# RECIBIR RESPUESTA DEL FLOW
# =========================================================

@flow_mvp_bp.post("/api/flow-mvp/submit")
def recibir_flow_mvp():

    try:

        payload = (
            request.get_json(
                silent=True
            )
            or {}
        )

        datos = normalizar_respuesta_flow(
            payload
        )

        tipo = datos.get(
            "tipo_solicitud"
        )

        print(
            "=== FLOW MVP COMPLETADO ==="
        )

        print(
            "Tipo:",
            tipo,
        )


        # =====================================================
        # COTIZACIÓN
        # =====================================================

        if tipo == "cotizacion":

            faltantes = (
                validar_cotizacion_flow(
                    datos
                )
            )

            if faltantes:

                return jsonify(
                    {
                        "success": False,
                        "tipo_solicitud":
                            "cotizacion",

                        "error": (
                            "Faltan datos "
                            "obligatorios: "
                            + ", ".join(
                                faltantes
                            )
                        ),

                        "faltantes":
                            faltantes,
                    }
                ), 400


            owner, _deal_resp, deal_id = (
                registrar_cotizacion_en_zoho(
                    datos
                )
            )


            if not deal_id:

                return jsonify(
                    {
                        "success": False,

                        "tipo_solicitud":
                            "cotizacion",

                        "error": (
                            "No fue posible "
                            "crear el Deal "
                            "en Zoho CRM."
                        ),
                    }
                ), 502


            deal_name = (
                "Cotización - "
                f"{datos.get('empresa') or 'Sin empresa'}"
            )


            # Notificar al mismo ejecutivo
            # asignado al Deal.

            enviar_correo_owner(
                owner,
                deal_id,
                deal_name,
                datos,
            )


            print(
                "=== FLOW -> ZOHO CRM ==="
            )

            print(
                "Deal creado:",
                deal_id,
            )

            print(
                "Owner:",
                owner.get(
                    "nombre"
                ),
            )


            return jsonify(
                {
                    "success": True,

                    "tipo_solicitud":
                        "cotizacion",

                    "crm": {
                        "deal_id":
                            str(
                                deal_id
                            ),

                        "deal_name":
                            deal_name,

                        "owner":
                            owner.get(
                                "nombre"
                            ),
                    },
                }
            )


        # =====================================================
        # POSTVENTA
        # =====================================================

        if tipo == "postventa":

            faltantes = (
                validar_postventa_flow(
                    datos
                )
            )

            if faltantes:

                return jsonify(
                    {
                        "success": False,

                        "tipo_solicitud":
                            "postventa",

                        "error": (
                            "Faltan datos "
                            "obligatorios: "
                            + ", ".join(
                                faltantes
                            )
                        ),

                        "faltantes":
                            faltantes,
                    }
                ), 400


            resultado = (
                enviar_correo_postventa(
                    datos
                )
            )


            case_id = str(
                resultado.get(
                    "case_id",
                    ""
                )
            ).strip()


            if not case_id:

                return jsonify(
                    {
                        "success": False,

                        "tipo_solicitud":
                            "postventa",

                        "error": (
                            "Zoho CRM no "
                            "devolvió el ID "
                            "del Case."
                        ),
                    }
                ), 502


            print(
                "=== FLOW -> ZOHO CRM ==="
            )

            print(
                "Case creado:",
                case_id,
            )


            return jsonify(
                {
                    "success": True,

                    "tipo_solicitud":
                        "postventa",

                    "crm": {
                        "case_id":
                            case_id,
                    },
                }
            )


        return jsonify(
            {
                "success": False,

                "error": (
                    "Tipo de solicitud "
                    "no soportado."
                ),
            }
        ), 400


    except ValueError as error:

        print(
            "[FLOW MVP] Datos inválidos:",
            error,
        )

        return jsonify(
            {
                "success": False,
                "error": str(error),
            }
        ), 400


    except Exception as error:

        print(
            "[FLOW MVP] "
            "Error integrando con CRM:",
            error,
        )

        return jsonify(
            {
                "success": False,

                "error": (
                    "Ocurrió un error al "
                    "registrar la solicitud "
                    "en Zoho CRM."
                ),
            }
        ), 500