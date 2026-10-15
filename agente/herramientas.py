import re

from . import zoho

_DATOS_EMPRESA = {
    "empresa": {"type": "string", "description": "Nombre de la empresa"},
    "rut": {"type": "string", "description": "RUT de la empresa, ej. 76123456-7"},
    "contacto": {"type": "string", "description": "Nombre y apellido de la persona"},
    "correo": {"type": "string"},
    "telefono": {"type": "string"},
}

HERRAMIENTAS = [
    {
        "name": "registrar_cotizacion",
        "description": (
            "Registra una solicitud de cotización en Zoho CRM (crea el negocio y avisa al ejecutivo). "
            "Úsala solo después de que el cliente confirmó el resumen."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                **_DATOS_EMPRESA,
                "productos": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "descripcion": {"type": "string"},
                            "numero_parte": {"type": "string", "description": "Vacío si no lo conoce"},
                            "marca": {"type": "string", "description": "Vacío si no la conoce"},
                            "cantidad": {"type": "string"},
                        },
                        "required": ["descripcion", "cantidad"],
                    },
                },
                "direccion_entrega": {"type": "string"},
            },
            "required": ["empresa", "rut", "contacto", "correo", "telefono", "productos", "direccion_entrega"],
        },
    },
    {
        "name": "registrar_postventa",
        "description": (
            "Registra una solicitud de postventa (crea un Caso en Zoho CRM y avisa al equipo de postventa). "
            "Úsala solo después de que el cliente confirmó el resumen."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nombre": {"type": "string"},
                "rut": {"type": "string"},
                "numero_factura": {"type": "string", "description": "Número de factura y/o orden de compra"},
                "detalle": {"type": "string", "description": "Descripción de la situación"},
            },
            "required": ["nombre", "rut", "numero_factura", "detalle"],
        },
    },
    {
        "name": "registrar_contacto",
        "description": (
            "Registra al cliente en Zoho CRM y crea una tarea para que un ejecutivo lo contacte. "
            "Úsala para consultas generales, cuando el cliente pida hablar con una persona "
            "o cuando la consulta esté fuera de tu alcance. No la uses si ya registraste una cotización o postventa."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                **_DATOS_EMPRESA,
                "motivo": {"type": "string", "description": "Motivo en pocas palabras"},
                "resumen": {"type": "string", "description": "Resumen de lo conversado para el ejecutivo"},
            },
            "required": ["contacto", "correo", "telefono", "motivo", "resumen"],
        },
    },
]

_CORREO = re.compile(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$")


def _validar(args: dict) -> str | None:
    """Devuelve un mensaje de error para el modelo, o None si todo está bien."""
    correo = str(args.get("correo") or "").strip()
    if "correo" in args and not _CORREO.match(correo):
        return "El correo no tiene un formato válido. Pídelo nuevamente."

    telefono = re.sub(r"\D", "", str(args.get("telefono") or ""))
    if "telefono" in args and not 8 <= len(telefono) <= 12:
        return "El teléfono no parece válido. Pídelo con código de país, ej. 56912345678."

    rut = re.sub(r"[^\dkK]", "", str(args.get("rut") or ""))
    if args.get("rut") and not 7 <= len(rut) <= 10:
        return "El RUT no parece válido. Pídelo nuevamente, ej. 76123456-7."

    return None



def ejecutar(nombre: str, args: dict, canal: str, contexto: dict | None = None) -> dict:
    contexto = contexto if contexto is not None else {}
    registros = contexto.setdefault("registros", {})

    # Evita registros duplicados en la misma conversación
    if nombre in registros:
        return {"ok": True, "id": registros[nombre], "mensaje": "Ya estaba registrado en esta conversación."}

    error = _validar(args)
    if error:
        return {"ok": False, "mensaje": error}

    try:
        if nombre == "registrar_cotizacion":
            registro_id = zoho.registrar_cotizacion(args, contexto)
        elif nombre == "registrar_postventa":
            registro_id = zoho.registrar_postventa(args)
        elif nombre == "registrar_contacto":
            registro_id = zoho.registrar_contacto(args, contexto)
        else:
            return {"ok": False, "mensaje": f"Herramienta desconocida: {nombre}"}

        registros[nombre] = registro_id
        return {"ok": True, "id": registro_id}

    except Exception as e:
        print(f"[agente.ejecutar] {nombre} falló: {e}")
        return {
            "ok": False,
            "mensaje": (
                "No se pudo registrar en el sistema. Informa al cliente que sus datos quedaron "
                "recibidos y que un ejecutivo lo contactará; no le pidas los datos de nuevo."
            ),
        }