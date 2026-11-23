"""
Preparacion de cotizaciones de Sofia para Zoho CRM Sandbox.

Este modulo no realiza solicitudes HTTP ni escrituras CRM.
"""

from services.retell_validacion import (
    preparar_cotizacion_desde_llamada_retell,
)


def preparar_borrador_cotizacion_sandbox(llamada):
    """
    Valida una llamada y prepara los datos de cotizacion.
    No busca, crea ni modifica registros en CRM.
    """

    if not isinstance(llamada, dict):
        return {
            "estado": "revision",
            "faltantes": ["llamada_invalida"],
        }

    try:
        validacion = preparar_cotizacion_desde_llamada_retell(
            llamada
        )
    except Exception:
        return {
            "estado": "revision",
            "faltantes": ["error_validacion"],
        }

    if not isinstance(validacion, dict):
        return {
            "estado": "revision",
            "faltantes": ["resultado_invalido"],
        }

    if validacion.get("lista") is not True:
        return {
            "estado": "revision",
            "faltantes": validacion.get("faltantes", []),
        }

    datos = validacion.get("cotizacion")

    if not isinstance(datos, dict):
        return {
            "estado": "revision",
            "faltantes": ["cotizacion_invalida"],
        }

    call_id = datos.get("retell_call_id")
    productos = datos.get("productos")

    if (
        not isinstance(call_id, str)
        or not call_id.strip()
        or not isinstance(productos, list)
        or not productos
    ):
        return {
            "estado": "revision",
            "faltantes": ["call_id_o_productos"],
        }

    return {
        "estado": "borrador_preparado",
        "call_id": call_id.strip(),
        "cuenta": {
            "empresa": datos.get("empresa"),
            "rut": datos.get("rut"),
        },
        "contacto": {
            "nombre": datos.get("contacto"),
            "correo": datos.get("correo"),
            "telefono": datos.get("telefono"),
        },
        "negocio": {
            "etapa": "Pendiente por cotizar",
            "tipo": "Llamada telefónica",
            "origen": "Llamada entrante",
            "direccion_entrega": datos.get(
                "direccion_entrega"
            ),
        },
        "productos": productos,
        "cantidad_productos": len(productos),
    }


def buscar_cuenta_sandbox_por_rut(rut, *, conexion=None):
    """
    Busca una Cuenta por Billing_Code exclusivamente en Sandbox.
    No crea ni modifica registros.
    """
    import re

    resultado_base = {
        "estado": "bloqueado",
        "account_id": None,
    }

    if not isinstance(rut, str):
        return {**resultado_base, "motivo": "rut_invalido"}

    rut_norm = (
        rut.replace(".", "")
        .replace(" ", "")
        .strip()
        .upper()
    )

    if not re.fullmatch(r"[0-9]{7,8}-[0-9K]", rut_norm):
        return {**resultado_base, "motivo": "rut_invalido"}

    if conexion is None:
        from services.sofia.crm_sandbox import (
            obtener_conexion_sandbox,
        )
        conexion = obtener_conexion_sandbox()

    if (
        not isinstance(conexion, dict)
        or conexion.get("base") != "https://sandbox.zohoapis.com"
        or not callable(conexion.get("http_get"))
        or not callable(conexion.get("obtener_token"))
    ):
        return {**resultado_base, "motivo": "conexion_invalida"}

    try:
        token = conexion["obtener_token"]()

        respuesta = conexion["http_get"](
            "https://sandbox.zohoapis.com/crm/v8/Accounts/search",
            headers={
                "Authorization": f"Zoho-oauthtoken {token}"
            },
            params={
                "criteria": f"(Billing_Code:equals:{rut_norm})",
                "fields": "id,Account_Name,Billing_Code",
                "per_page": 2,
            },
            timeout=20,
            allow_redirects=False,
        )

        if respuesta.status_code == 204:
            return {
                "estado": "no_encontrado",
                "account_id": None,
            }

        if respuesta.status_code != 200:
            return {**resultado_base, "motivo": "error_http"}

        datos = respuesta.json()

        if not isinstance(datos, dict):
            return {**resultado_base, "motivo": "respuesta_invalida"}

        registros = datos.get("data")

        if not isinstance(registros, list) or not registros:
            return {**resultado_base, "motivo": "respuesta_invalida"}

        if (datos.get("info") or {}).get("more_records") is True:
            return {**resultado_base, "motivo": "varios_resultados"}

        coincidencias = []

        for registro in registros:
            if not isinstance(registro, dict):
                return {**resultado_base, "motivo": "registro_invalido"}

            rut_registro = str(
                registro.get("Billing_Code") or ""
            ).replace(".", "").replace(" ", "").upper()

            if rut_registro == rut_norm:
                identificador = str(registro.get("id") or "")

                if not identificador.isascii() or not identificador.isdecimal():
                    return {
                        **resultado_base,
                        "motivo": "id_invalido",
                    }

                coincidencias.append(identificador)

        if len(coincidencias) > 1:
            return {**resultado_base, "motivo": "rut_duplicado"}

        if len(coincidencias) == 1:
            return {
                "estado": "encontrado",
                "account_id": coincidencias[0],
            }

        return {
            "estado": "no_encontrado",
            "account_id": None,
        }

    except Exception:
        return {**resultado_base, "motivo": "error_consulta"}


def buscar_registro_unico_sandbox(
    modulo, campo, valor, *, conexion=None
):
    """
    Busca un Contacto o Negocio en Sandbox.
    Rechaza resultados duplicados o inconsistentes.
    Solo lectura.
    """
    if (modulo, campo) not in (
        ("Contacts", "Email"),
        ("Deals", "Retell_Call_ID"),
    ):
        return {"estado": "bloqueado", "motivo": "campo_no_permitido"}

    if not isinstance(valor, str) or not valor.strip():
        return {"estado": "bloqueado", "motivo": "valor_invalido"}

    valor = valor.strip()

    import re

    if modulo == "Contacts":
        if not re.fullmatch(
            r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
            valor,
        ):
            return {"estado": "bloqueado", "motivo": "correo_invalido"}
    elif not re.fullmatch(r"[A-Za-z0-9_\\-]{3,255}", valor):
        return {"estado": "bloqueado", "motivo": "call_id_invalido"}

    if conexion is None:
        from services.sofia.crm_sandbox import (
            obtener_conexion_sandbox,
        )
        conexion = obtener_conexion_sandbox()

    if (
        not isinstance(conexion, dict)
        or conexion.get("base") != "https://sandbox.zohoapis.com"
        or not callable(conexion.get("http_get"))
        or not callable(conexion.get("obtener_token"))
    ):
        return {"estado": "bloqueado", "motivo": "conexion_invalida"}

    try:
        respuesta = conexion["http_get"](
            f"https://sandbox.zohoapis.com/crm/v8/{modulo}/search",
            headers={
                "Authorization": (
                    "Zoho-oauthtoken "
                    + conexion["obtener_token"]()
                )
            },
            params={
                "criteria": f"({campo}:equals:{valor})",
                "fields": f"id,{campo}",
                "per_page": 2,
            },
            timeout=20,
            allow_redirects=False,
        )

        if respuesta.status_code == 204:
            return {"estado": "no_encontrado", "registro_id": None}

        if respuesta.status_code != 200:
            return {"estado": "bloqueado", "motivo": "error_http"}

        datos = respuesta.json()

        if not isinstance(datos, dict):
            return {"estado": "bloqueado", "motivo": "respuesta_invalida"}

        registros = datos.get("data")
        info = datos.get("info") or {}

        if (
            not isinstance(registros, list)
            or not registros
            or not isinstance(info, dict)
            or info.get("more_records") is True
        ):
            return {"estado": "bloqueado", "motivo": "respuesta_ambigua"}

        coincidencias = []

        for registro in registros:
            if not isinstance(registro, dict):
                return {"estado": "bloqueado", "motivo": "registro_invalido"}

            recibido = registro.get(campo)

            if not isinstance(recibido, str):
                return {"estado": "bloqueado", "motivo": "campo_invalido"}

            igual = (
                recibido.casefold() == valor.casefold()
                if modulo == "Contacts"
                else recibido == valor
            )

            if igual:
                identificador = str(registro.get("id") or "")

                if (
                    not identificador.isascii()
                    or not identificador.isdecimal()
                ):
                    return {"estado": "bloqueado", "motivo": "id_invalido"}

                coincidencias.append(identificador)

        if len(coincidencias) > 1:
            return {"estado": "bloqueado", "motivo": "duplicados"}

        if len(coincidencias) == 1:
            return {
                "estado": "encontrado",
                "registro_id": coincidencias[0],
            }

        return {"estado": "no_encontrado", "registro_id": None}

    except Exception:
        return {"estado": "bloqueado", "motivo": "error_consulta"}


def preparar_registros_cotizacion_sandbox(
    borrador, *, account_id=None, contact_id=None
):
    """
    Construye datos para Accounts, Contacts y Deals.
    No ejecuta ninguna escritura.
    """
    from decimal import Decimal, InvalidOperation
    import re

    if (
        not isinstance(borrador, dict)
        or borrador.get("estado") != "borrador_preparado"
    ):
        return {"estado": "bloqueado", "motivo": "borrador_invalido"}

    cuenta = borrador.get("cuenta") or {}
    contacto = borrador.get("contacto") or {}
    negocio = borrador.get("negocio") or {}
    productos = borrador.get("productos") or []
    call_id = borrador.get("call_id")

    empresa = str(cuenta.get("empresa") or "").strip()
    rut = (
        str(cuenta.get("rut") or "")
        .replace(".", "")
        .replace(" ", "")
        .upper()
    )
    nombre = str(contacto.get("nombre") or "").strip()
    correo = str(contacto.get("correo") or "").strip()
    telefono = str(contacto.get("telefono") or "").strip()

    if (
        not empresa
        or not re.fullmatch(r"[0-9]{7,8}-[0-9K]", rut)
        or not nombre
        or not correo
        or not telefono
        or not isinstance(call_id, str)
        or not re.fullmatch(r"[A-Za-z0-9_\\-]{3,255}", call_id)
        or not isinstance(productos, list)
        or not productos
        or negocio.get("etapa") != "Pendiente por cotizar"
    ):
        return {"estado": "bloqueado", "motivo": "datos_incompletos"}

    partes_nombre = nombre.split()
    apellido = partes_nombre[-1]
    primer_nombre = " ".join(partes_nombre[:-1])

    descripcion = [
        "Solicitud de cotizacion telefonica",
        "Empresa: " + empresa,
        "RUT: " + rut,
        "Contacto: " + nombre,
        "Correo: " + correo,
        "Telefono: " + telefono,
        "Direccion: " + str(negocio.get("direccion_entrega") or ""),
        "Call ID: " + call_id,
        "",
        "PRODUCTOS SOLICITADOS:",
    ]

    for numero, producto in enumerate(productos, 1):
        if not isinstance(producto, dict):
            return {"estado": "bloqueado", "motivo": "producto_invalido"}

        try:
            cantidad = Decimal(str(producto.get("cantidad") or ""))
        except InvalidOperation:
            return {"estado": "bloqueado", "motivo": "cantidad_invalida"}

        if not cantidad.is_finite() or cantidad <= 0:
            return {"estado": "bloqueado", "motivo": "cantidad_invalida"}

        campos = {
            clave: str(producto.get(clave) or "").strip()
            for clave in ("descripcion", "marca", "numero_parte")
        }

        if not all(campos.values()):
            return {"estado": "bloqueado", "motivo": "producto_incompleto"}

        descripcion.append(
            f"{numero}. {campos['descripcion']} | "
            f"Marca: {campos['marca']} | "
            f"Parte: {campos['numero_parte']} | "
            f"Cantidad: {cantidad}"
        )

    def id_valido(valor):
        return (
            isinstance(valor, str)
            and valor.isascii()
            and valor.isdecimal()
        )

    if account_id is not None and not id_valido(account_id):
        return {"estado": "bloqueado", "motivo": "account_id_invalido"}

    if contact_id is not None and not id_valido(contact_id):
        return {"estado": "bloqueado", "motivo": "contact_id_invalido"}

    cuenta_data = {
        "Account_Name": empresa,
        "Billing_Code": rut,
        "Phone": telefono,
    }

    contacto_data = {
        "First_Name": primer_nombre,
        "Last_Name": apellido,
        "Email": correo,
        "Phone": telefono,
    }

    if account_id:
        contacto_data["Account_Name"] = {"id": account_id}

    deal_data = {
        "Deal_Name": "Cotizacion telefonica - " + empresa,
        "Stage": "Pendiente por cotizar",
        "Type": "Llamada telef\u00f3nica",
        "Lead_Source": "Llamada entrante",
        "Retell_Call_ID": call_id,
        "Cantidad_de_productos": len(productos),
        "Description": "\n".join(descripcion),
    }

    if account_id:
        deal_data["Account_Name"] = {"id": account_id}

    if contact_id:
        deal_data["Contact_Name"] = {"id": contact_id}

    return {
        "estado": "registros_preparados",
        "cuenta": cuenta_data,
        "contacto": contacto_data,
        "negocio": deal_data,
        "cantidad_productos": len(productos),
    }
