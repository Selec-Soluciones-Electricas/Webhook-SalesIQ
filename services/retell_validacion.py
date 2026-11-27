import re
from services.retell_productos import convertir_productos_retell
from services.retell_validadores import (
    validar_rut_chileno,
    validar_email_retell,
    validar_telefono_retell,
)



CAMPOS_COTIZACION = {
    "empresa": "empresa",
    "rut_cliente": "rut",
    "nombre_cliente": "contacto",
    "email_cliente": "correo",
    "telefono_cliente": "telefono",
    "direccion_entrega": "direccion_entrega",
}


def preparar_cotizacion_retell(datos, *, permitir_rut_ficticio=False):
    """Prepara una cotizacion para las validaciones de SELEC."""

    if not isinstance(datos, dict):
        raise ValueError("Los datos deben ser un diccionario")

    tipo = datos.get("tipo_solicitud")

    if not isinstance(tipo, str) or tipo.strip().lower() != "cotizacion":
        return {
            "lista": False,
            "faltantes": ["tipo_solicitud"],
            "cotizacion": None,
        }

    faltantes = []
    cotizacion = {}

    for campo_retell, campo_zoho in CAMPOS_COTIZACION.items():
        valor = datos.get(campo_retell)

        if not isinstance(valor, str) or not valor.strip():
            faltantes.append(campo_retell)
        else:
            cotizacion[campo_zoho] = valor.strip()

    texto_productos = datos.get("productos_solicitados")

    if not isinstance(texto_productos, str) or not texto_productos.strip():
        faltantes.append("productos_solicitados")

    if faltantes:
        return {
            "lista": False,
            "faltantes": faltantes,
            "cotizacion": None,
        }



    # Validar los datos del cliente antes de procesar la cotizacion
    errores_validacion = []

    rut_normalizado = (
        cotizacion["rut"]
        .replace(".", "")
        .replace(" ", "")
        .upper()
    )

    if permitir_rut_ficticio:
        rut_valido = re.fullmatch(
            r"[0-9]{7,8}-[0-9K]",
            rut_normalizado
        ) is not None
    else:
        rut_valido = validar_rut_chileno(cotizacion["rut"])

    if not rut_valido:
        errores_validacion.append("rut_cliente (RUT invalido)")

    if not validar_email_retell(cotizacion["correo"]):
        errores_validacion.append("email_cliente (correo invalido)")

    if not validar_telefono_retell(cotizacion["telefono"]):
        errores_validacion.append("telefono_cliente (telefono invalido)")

    if errores_validacion:
        return {
            "lista": False,
            "faltantes": errores_validacion,
            "cotizacion": None,
        }



    try:
        productos = convertir_productos_retell(texto_productos)
    except ValueError:
        return {
            "lista": False,
            "faltantes": ["productos_solicitados (formato invalido)"],
            "cotizacion": None,
        }

    cotizacion["productos"] = productos
    cotizacion["cantidad_productos_solicitados"] = len(productos)
    cotizacion["origen"] = "retell"

    return {
        "lista": True,
        "faltantes": [],
        "cotizacion": cotizacion,
    }



def preparar_cotizacion_desde_llamada_retell(
    llamada, *, permitir_rut_ficticio=False
):
    """
    Prepara una cotizacion usando los datos de una llamada
    analizada por Retell.
    """

    if not isinstance(llamada, dict):
        return {
            "lista": False,
            "faltantes": ["llamada"],
            "cotizacion": None,
        }

    # Obtener el identificador real de la llamada
    call_id = llamada.get("call_id")

    if (
        not isinstance(call_id, str)
        or not call_id.strip()
        or len(call_id.strip()) > 255
    ):
        return {
            "lista": False,
            "faltantes": ["call_id"],
            "cotizacion": None,
        }

    # Obtener el analisis generado por Retell
    analisis = llamada.get("call_analysis")

    if not isinstance(analisis, dict):
        return {
            "lista": False,
            "faltantes": ["call_analysis"],
            "cotizacion": None,
        }

    datos = analisis.get("custom_analysis_data")

    if not isinstance(datos, dict):
        return {
            "lista": False,
            "faltantes": ["custom_analysis_data"],
            "cotizacion": None,
        }

    # Utilizar nuestras validaciones existentes
    resultado = preparar_cotizacion_retell(
        datos,
        permitir_rut_ficticio=permitir_rut_ficticio
    )

    if not resultado["lista"]:
        return resultado

    # Asociar la cotizacion a su llamada original
    resultado["cotizacion"]["retell_call_id"] = call_id.strip()

    return resultado
