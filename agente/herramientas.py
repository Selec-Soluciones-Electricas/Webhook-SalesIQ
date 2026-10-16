import re

from . import zoho


_DATOS_EMPRESA = {
    "empresa": {
        "type": "string",
        "description": "Nombre de la empresa",
    },
    "rut": {
        "type": "string",
        "description": "RUT de la empresa, ej. 76123456-7",
    },
    "contacto": {
        "type": "string",
        "description": "Nombre y apellido de la persona",
    },
    "correo": {
        "type": "string",
    },
    "telefono": {
        "type": "string",
    },
}


# =========================================================
# HERRAMIENTAS DISPONIBLES PARA SOFÍA
# =========================================================

HERRAMIENTAS = [
    {
        "name": "derivar_cotizacion",
        "description": (
            "Envía al cliente la plantilla oficial de WhatsApp "
            "para completar el formulario de cotización. "
            "Úsala inmediatamente cuando el cliente quiera cotizar "
            "o solicitar precios. No pidas datos antes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "derivar_postventa",
        "description": (
            "Envía al cliente la plantilla oficial de WhatsApp "
            "para completar el formulario de postventa. "
            "Úsala inmediatamente ante reclamos, garantías, fallas, "
            "devoluciones o problemas con compras/pedidos. "
            "No pidas datos antes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "registrar_contacto",
        "description": (
            "Registra al cliente en Zoho CRM y crea una tarea para "
            "que un ejecutivo lo contacte. Úsala para consultas "
            "generales, cuando el cliente pida hablar con una persona "
            "o cuando la consulta esté fuera de tu alcance. "
            "No la uses para cotización ni postventa."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                **_DATOS_EMPRESA,
                "motivo": {
                    "type": "string",
                    "description": "Motivo en pocas palabras",
                },
                "resumen": {
                    "type": "string",
                    "description": (
                        "Resumen de lo conversado para el ejecutivo"
                    ),
                },
            },
            "required": [
                "contacto",
                "correo",
                "telefono",
                "motivo",
                "resumen",
            ],
        },
    },
]


_CORREO = re.compile(
    r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$"
)


def _validar(args: dict) -> str | None:
    """
    Devuelve un mensaje de error para el modelo,
    o None si todo está bien.
    """

    correo = str(
        args.get("correo")
        or ""
    ).strip()

    if (
        "correo" in args
        and not _CORREO.match(correo)
    ):
        return (
            "El correo no tiene un formato válido. "
            "Pídelo nuevamente."
        )

    telefono = re.sub(
        r"\D",
        "",
        str(
            args.get("telefono")
            or ""
        ),
    )

    if (
        "telefono" in args
        and not 8 <= len(telefono) <= 12
    ):
        return (
            "El teléfono no parece válido. "
            "Pídelo con código de país, ej. 56912345678."
        )

    rut = re.sub(
        r"[^\dkK]",
        "",
        str(
            args.get("rut")
            or ""
        ),
    )

    if (
        args.get("rut")
        and not 7 <= len(rut) <= 10
    ):
        return (
            "El RUT no parece válido. "
            "Pídelo nuevamente, ej. 76123456-7."
        )

    return None


def ejecutar(
    nombre: str,
    args: dict,
    canal: str,
    contexto: dict | None = None,
) -> dict:

    contexto = (
        contexto
        if contexto is not None
        else {}
    )

    registros = contexto.setdefault(
        "registros",
        {},
    )

    # =====================================================
    # EVITAR EJECUCIONES DUPLICADAS
    # =====================================================

    if nombre in registros:
        return {
            "ok": True,
            "mensaje": (
                "Esta acción ya fue realizada "
                "en esta conversación."
            ),
        }

    # =====================================================
    # DERIVAR A COTIZACIÓN
    # =====================================================

    if nombre == "derivar_cotizacion":

        payload = contexto.get("payload")

        if not payload:
            return {
                "ok": False,
                "mensaje": (
                    "No se encontró la información "
                    "de WhatsApp necesaria para enviar "
                    "el formulario."
                ),
            }

        from services.salesiq_service import (
            enviar_plantilla_cotizacion_whatsapp,
        )

        enviada = (
            enviar_plantilla_cotizacion_whatsapp(
                payload
            )
        )

        if not enviada:
            return {
                "ok": False,
                "mensaje": (
                    "No fue posible enviar la plantilla "
                    "de cotización."
                ),
            }

        registros[nombre] = True

        return {
            "ok": True,
            "mensaje": (
                "Se envió correctamente al cliente "
                "el formulario oficial de cotización."
            ),
        }

    # =====================================================
    # DERIVAR A POSTVENTA
    # =====================================================

    if nombre == "derivar_postventa":

        payload = contexto.get("payload")

        if not payload:
            return {
                "ok": False,
                "mensaje": (
                    "No se encontró la información "
                    "de WhatsApp necesaria para enviar "
                    "el formulario."
                ),
            }

        from services.salesiq_service import (
            enviar_plantilla_postventa_whatsapp,
        )

        enviada = (
            enviar_plantilla_postventa_whatsapp(
                payload
            )
        )

        if not enviada:
            return {
                "ok": False,
                "mensaje": (
                    "No fue posible enviar la plantilla "
                    "de postventa."
                ),
            }

        registros[nombre] = True

        return {
            "ok": True,
            "mensaje": (
                "Se envió correctamente al cliente "
                "el formulario oficial de postventa."
            ),
        }

    # =====================================================
    # REGISTRAR CONTACTO
    # =====================================================

    if nombre == "registrar_contacto":

        error = _validar(args)

        if error:
            return {
                "ok": False,
                "mensaje": error,
            }

        try:

            registro_id = (
                zoho.registrar_contacto(
                    args,
                    contexto,
                )
            )

            registros[nombre] = (
                registro_id
            )

            return {
                "ok": True,
                "id": registro_id,
            }

        except Exception as error:

            print(
                "[agente.ejecutar] "
                f"{nombre} falló: {error}"
            )

            return {
                "ok": False,
                "mensaje": (
                    "No se pudo registrar en el sistema. "
                    "Informa al cliente que sus datos "
                    "quedaron recibidos y que un ejecutivo "
                    "lo contactará."
                ),
            }

    # =====================================================
    # HERRAMIENTA DESCONOCIDA
    # =====================================================

    return {
        "ok": False,
        "mensaje": (
            f"Herramienta desconocida: {nombre}"
        ),
    }