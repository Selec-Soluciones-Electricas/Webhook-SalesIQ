
from services.retell_validacion import (
    preparar_cotizacion_desde_llamada_retell,
)
from services.retell_duplicados import (
    buscar_negocio_por_call_id,
)


def evaluar_cotizacion_retell(llamada):
    """
    Valida una cotizacion telefonica y comprueba
    si su Call ID ya existe en Zoho CRM.

    Esta funcion no crea ni modifica registros.
    """

    # PASO 1: Validar la informacion de la llamada
    try:
        validacion = preparar_cotizacion_desde_llamada_retell(
            llamada
        )
    except Exception as error:
        print(
            "[RETELL] Error validando cotizacion:",
            type(error).__name__,
        )
        return {
            "estado": "revision",
            "faltantes": ["error_validacion"],
            "cotizacion": None,
        }

    if not validacion.get("lista"):
        return {
            "estado": "revision",
            "faltantes": validacion.get("faltantes", []),
            "cotizacion": None,
        }

    cotizacion = validacion["cotizacion"]
    call_id = cotizacion["retell_call_id"]

    # PASO 2: Consultar si la llamada ya fue registrada
    try:
        consulta = buscar_negocio_por_call_id(call_id)
    except Exception as error:
        print(
            "[RETELL] Error consultando duplicados:",
            type(error).__name__,
        )
        return {
            "estado": "error_consulta",
            "faltantes": [],
            "cotizacion": None,
        }

    # PASO 3: Interpretar el resultado
    if consulta.get("estado") == "encontrado":
        return {
            "estado": "duplicado",
            "negocio_id": consulta.get("negocio_id"),
            "cotizacion": None,
        }

    if consulta.get("estado") == "no_encontrado":
        return {
            "estado": "apta_para_creacion",
            "faltantes": [],
            "cotizacion": cotizacion,
        }

    # Ante errores de Zoho, detener el proceso
    return {
        "estado": "error_consulta",
        "faltantes": [],
        "cotizacion": None,
    }



def preparar_cliente_retell(llamada, owner=None):
    """
    Evalua la cotizacion y resuelve su empresa y contacto.

    No crea el negocio en Zoho CRM.
    """


    # Proteccion adicional contra escrituras accidentales.
    # La preparacion del cliente puede crear empresas
    # y contactos en Zoho CRM.

    import os

    escritura_habilitada = (
        os.getenv(
            "RETELL_CRM_WRITES_ENABLED",
            "false",
        ).strip().lower()
        == "true"
    )

    if not escritura_habilitada:
        print(
            "[RETELL] Preparacion de cliente bloqueada: "
            "escrituras CRM desactivadas."
        )

        return {
            "estado": "registro_desactivado",
            "negocio_id": None,
        }


    from services import zoho_service

    # 1. Validar y comprobar duplicados
    evaluacion = evaluar_cotizacion_retell(llamada)

    if evaluacion["estado"] != "apta_para_creacion":
        return evaluacion

    cotizacion = evaluacion["cotizacion"]

    # 2. Buscar o crear la empresa por RUT
    try:
        account_id = zoho_service.obtener_o_crear_account(
            cotizacion,
            owner=owner,
            proteger_busqueda=True,
        )
    except Exception as error:
        print(
            "[RETELL] Error preparando empresa:",
            type(error).__name__,
        )
        account_id = None

    if not account_id:
        return {
            "estado": "pendiente_empresa",
            "cotizacion": cotizacion,
            "account_id": None,
            "contact_id": None,
        }

    # 3. Buscar o crear el contacto por correo
    try:
        contact_id = zoho_service.obtener_o_crear_contact(
            cotizacion,
            account_id=account_id,
            owner=owner,
            proteger_empresa=True,
        )
    except Exception as error:
        print(
            "[RETELL] Error preparando contacto:",
            type(error).__name__,
        )
        contact_id = None

    if not contact_id:
        return {
            "estado": "pendiente_contacto",
            "cotizacion": cotizacion,
            "account_id": account_id,
            "contact_id": None,
        }

    # 4. Todo listo para la futura creacion del negocio
    return {
        "estado": "cliente_preparado",
        "cotizacion": cotizacion,
        "account_id": account_id,
        "contact_id": contact_id,
    }




def registrar_cotizacion_retell(llamada, owner=None):
    """
    Registra una cotizacion telefonica en Zoho CRM.

    Si Zoho rechaza un Call ID duplicado, intenta
    recuperar el negocio existente sin crearlo otra vez.
    """


    # Interruptor de seguridad para Zoho CRM
    import os

    escritura_habilitada = (
        os.getenv("RETELL_CRM_WRITES_ENABLED", "false")
        .strip()
        .lower()
        == "true"
    )

    if not escritura_habilitada:
        print(
            "[RETELL] Registro automatico de cotizaciones "
            "desactivado por seguridad."
        )

        return {
            "estado": "registro_desactivado",
            "negocio_id": None,
        }

    from services import zoho_service

    # 1. Validar llamada y preparar cliente
    preparacion = preparar_cliente_retell(
        llamada,
        owner=owner,
    )

    if preparacion.get("estado") != "cliente_preparado":
        return preparacion

    cotizacion = preparacion["cotizacion"]
    account_id = preparacion["account_id"]
    contact_id = preparacion["contact_id"]
    call_id = cotizacion["retell_call_id"]

    # 2. Intentar crear el negocio
    respuesta = None
    negocio_id = None

    try:
        respuesta, negocio_id = zoho_service.crear_deal_en_zoho(
            cotizacion,
            account_id=account_id,
            contact_id=contact_id,
            owner=owner,
        )

    except Exception as error:
        print(
            "[RETELL] Error registrando negocio:",
            type(error).__name__,
        )

    # 3. Zoho confirmo la creacion
    if negocio_id:
        return {
            "estado": "creado",
            "negocio_id": str(negocio_id),
            "retell_call_id": call_id,
        }

    # 4. Revisar si Zoho rechazo datos duplicados
    es_duplicado = False

    if respuesta is not None:
        try:
            cuerpo = respuesta.json()

            if isinstance(cuerpo, dict):
                registros = cuerpo.get("data", [])

                if isinstance(registros, list):
                    es_duplicado = any(
                        isinstance(registro, dict)
                        and registro.get("code") == "DUPLICATE_DATA"
                        for registro in registros
                    )

                if cuerpo.get("code") == "DUPLICATE_DATA":
                    es_duplicado = True

        except (ValueError, TypeError, AttributeError):
            pass

    # 5. Si hubo duplicado, buscar el negocio original
    if es_duplicado:
        print(
            "[RETELL] Zoho reporto un duplicado. "
            "Verificando Call ID."
        )

        try:
            consulta = buscar_negocio_por_call_id(call_id)

            if (
                consulta.get("estado") == "encontrado"
                and consulta.get("negocio_id")
            ):
                return {
                    "estado": "duplicado",
                    "negocio_id": consulta["negocio_id"],
                    "retell_call_id": call_id,
                }

        except Exception as error:
            print(
                "[RETELL] Error verificando duplicado:",
                type(error).__name__,
            )

    # 6. Si no hay confirmacion, dejar pendiente
    return {
        "estado": "pendiente_verificacion",
        "negocio_id": None,
        "retell_call_id": call_id,
    }
