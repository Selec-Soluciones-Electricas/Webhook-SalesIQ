"""
Creacion controlada de cotizaciones en Zoho CRM Sandbox.
No utiliza zoho_service ni la conexion de produccion.
"""

import os
from datetime import date

from services.sofia.cotizaciones_sandbox import (
    buscar_cuenta_sandbox_por_rut,
    buscar_registro_unico_sandbox,
    preparar_registros_cotizacion_sandbox,
)

BASE = "https://sandbox.zohoapis.com/crm/v8"


def registrar_cotizacion_sandbox(
    borrador,
    *,
    conexion=None,
    http_post=None,
    owner_id=None,
    fecha_cierre=None,
    autorizar=False,
):
    def detener(motivo, estado="bloqueado"):
        return {"estado": estado, "motivo": motivo}

    # Doble autorizacion. Por defecto, nunca escribe.
    if (
        autorizar is not True
        or os.getenv(
            "SOFIA_SANDBOX_DEALS_WRITES_ENABLED", "false"
        ).strip().lower() != "true"
    ):
        return detener("escritura_desactivada", "desactivado")

    if (
        not isinstance(owner_id, str)
        or not owner_id.isascii()
        or not owner_id.isdecimal()
        or not callable(http_post)
    ):
        return detener("autorizacion_invalida")

    try:
        if date.fromisoformat(fecha_cierre).isoformat() != fecha_cierre:
            return detener("fecha_invalida")
    except (TypeError, ValueError):
        return detener("fecha_invalida")

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
        return detener("conexion_invalida")


    # Un solo access token por ejecucion.
    # Las consultas y las escrituras reutilizan este token.
    try:
        token = conexion["obtener_token"]()
        if not isinstance(token, str) or not token:
            return detener("token_no_disponible")
    except Exception:
        return detener("token_no_disponible")

    conexion = dict(conexion)
    conexion["obtener_token"] = lambda: token

    preparado = preparar_registros_cotizacion_sandbox(borrador)

    if preparado.get("estado") != "registros_preparados":
        return detener("datos_invalidos")

    call_id = preparado["negocio"]["Retell_Call_ID"]
    cuenta_data = preparado["cuenta"]
    contacto_data = preparado["contacto"]

    def buscar(modulo, campo, valor):
        return buscar_registro_unico_sandbox(
            modulo, campo, valor, conexion=conexion
        )

    def insertar(modulo, datos):
        # Una sola solicitud por modulo, sin reintentos.
        url = BASE + "/" + modulo

        try:
            token = conexion["obtener_token"]()
            respuesta = http_post(
                url,
                headers={
                    "Authorization": "Zoho-oauthtoken " + token,
                    "Content-Type": "application/json",
                },
                json={
                    "data": [datos],
                    "trigger": [],
                },
                timeout=15,
                allow_redirects=False,
            )
        except Exception:
            return detener(
                "insercion_sin_confirmacion",
                "resultado_incierto",
            )

        try:
            cuerpo = respuesta.json()
            filas = cuerpo.get("data") or []
            fila = filas[0] if len(filas) == 1 else {}

            if (
                respuesta.status_code in (200, 201)
                and fila.get("code") == "SUCCESS"
                and fila.get("status") == "success"
            ):
                identificador = str(
                    (fila.get("details") or {}).get("id") or ""
                )

                if (
                    identificador.isascii()
                    and identificador.isdecimal()
                ):
                    return {
                        "estado": "creado",
                        "registro_id": identificador,
                    }

            return detener(
                "respuesta_no_confirmada",
                "resultado_incierto",
            )

        except Exception:
            return detener(
                "respuesta_no_interpretable",
                "resultado_incierto",
            )

    def verificar_listado(modulo, campo, valor):
        """Confirma ausencia con un listado, ademas de /search.

        /search puede tardar en indexar registros creados recientemente.
        Si no se puede recorrer por completo, se bloquean las escrituras.
        """
        coincidencias = set()
        for pagina in range(1, 11):
            try:
                respuesta = conexion["http_get"](
                    BASE + "/" + modulo,
                    headers={
                        "Authorization": "Zoho-oauthtoken "
                        + conexion["obtener_token"]()
                    },
                    params={
                        "fields": "id," + campo,
                        "page": pagina,
                        "per_page": 200,
                    },
                    timeout=20,
                    allow_redirects=False,
                )
                if respuesta.status_code == 204:
                    break
                if respuesta.status_code != 200:
                    return {"estado": "bloqueado"}
                cuerpo = respuesta.json()
                registros = cuerpo.get("data")
                info = cuerpo.get("info")
                if not isinstance(registros, list) or not isinstance(info, dict):
                    return {"estado": "bloqueado"}
                for item in registros:
                    if not isinstance(item, dict):
                        return {"estado": "bloqueado"}
                    recibido = str(item.get(campo) or "").strip()
                    if modulo == "Accounts":
                        recibido = recibido.replace(".", "").replace(" ", "").upper()
                        igual = recibido == valor
                    elif modulo == "Deals":
                        # Call ID exige coincidencia exacta, respetando mayusculas.
                        igual = recibido == valor
                    else:
                        igual = recibido.casefold() == valor.casefold()
                    if igual:
                        identificador = str(item.get("id") or "")
                        if not (identificador.isascii() and identificador.isdecimal()):
                            return {"estado": "bloqueado"}
                        coincidencias.add(identificador)
                if info.get("more_records") is False:
                    break
                if info.get("more_records") is not True:
                    return {"estado": "bloqueado"}
            except Exception:
                return {"estado": "bloqueado"}
        else:
            # Hay mas registros que los auditables de manera segura.
            return {"estado": "bloqueado"}

        if len(coincidencias) > 1:
            return {"estado": "bloqueado"}
        if coincidencias:
            return {"estado": "encontrado", "registro_id": next(iter(coincidencias))}
        return {"estado": "no_encontrado"}

    # 1. Comprobar el Negocio antes de crear clientes.
    negocio = buscar("Deals", "Retell_Call_ID", call_id)

    if negocio["estado"] == "encontrado":
        return {
            "estado": "ya_registrado",
            "negocio_id": negocio["registro_id"],
        }

    # Si /search falla (incluyendo INVALID_QUERY), no asumir ausencia.
    # El listado completo decide si existe el Negocio; solo sus resultados
    # confirmados permiten crear o reutilizar registros.
    if negocio["estado"] not in ("no_encontrado", "bloqueado"):
        return detener("busqueda_negocio_inconclusa")
    if negocio["estado"] == "bloqueado" and negocio.get("motivo") not in (
        "error_http", "error_consulta", "respuesta_invalida", "respuesta_ambigua",
        "registro_invalido", "campo_invalido", "id_invalido",
    ):
        return detener("busqueda_negocio_inconclusa")

    # Zoho puede demorar en indexar /search. Verificar el listado
    # antes de escribir, tambien para Negocios con Call ID unico.
    listado_negocio = verificar_listado("Deals", "Retell_Call_ID", call_id)
    if listado_negocio["estado"] == "encontrado":
        return {
            "estado": "ya_registrado",
            "negocio_id": listado_negocio["registro_id"],
        }
    if listado_negocio["estado"] != "no_encontrado":
        return detener("listado_negocios_inconcluso")

    # Solo fallos de consulta (no de validacion ni duplicados) permiten
    # consultar el listado completo como segunda fuente confiable.
    fallos_busqueda_recuperables = {
        "error_http", "error_consulta", "respuesta_invalida",
        "respuesta_ambigua", "registro_invalido", "campo_invalido",
        "id_invalido",
    }

    # 2. Resolver Cuenta.
    cuenta = buscar_cuenta_sandbox_por_rut(
        cuenta_data["Billing_Code"],
        conexion=conexion,
    )

    if cuenta["estado"] == "encontrado":
        account_id = cuenta["account_id"]
    elif cuenta["estado"] == "no_encontrado" or (
        cuenta["estado"] == "bloqueado"
        and cuenta.get("motivo") in fallos_busqueda_recuperables
    ):
        # Un fallo de /Accounts/search NO prueba que la Cuenta no exista.
        # Confirmar mediante listado completo antes de cualquier POST.
        listado_cuenta = verificar_listado(
            "Accounts", "Billing_Code", cuenta_data["Billing_Code"]
        )
        if listado_cuenta["estado"] == "encontrado":
            account_id = listado_cuenta["registro_id"]
        elif listado_cuenta["estado"] == "no_encontrado":
            respuesta = insertar("Accounts", cuenta_data)
            if respuesta["estado"] != "creado":
                return respuesta
            account_id = respuesta["registro_id"]
        else:
            return detener("listado_cuentas_inconcluso")
    else:
        return detener("busqueda_cuenta_inconclusa")

    # 3. Resolver Contacto.
    contacto = buscar(
        "Contacts", "Email", contacto_data["Email"]
    )

    if contacto["estado"] == "encontrado":
        contact_id = contacto["registro_id"]

        # Nunca asociar un Contacto a otra Cuenta.
        try:
            respuesta = conexion["http_get"](
                BASE + "/Contacts/" + contact_id,
                headers={
                    "Authorization": (
                        "Zoho-oauthtoken "
                        + conexion["obtener_token"]()
                    )
                },
                params={"fields": "id,Account_Name"},
                timeout=15,
                allow_redirects=False,
            )

            if respuesta.status_code != 200:
                return detener("contacto_no_verificado")

            filas = respuesta.json().get("data") or []
            registro = filas[0] if len(filas) == 1 else {}
            cuenta_vinculada = registro.get("Account_Name") or {}

            if str(cuenta_vinculada.get("id")) != account_id:
                return detener("contacto_de_otra_cuenta")

        except Exception:
            return detener("contacto_no_verificado")

    elif contacto["estado"] == "no_encontrado" or (
        contacto["estado"] == "bloqueado"
        and contacto.get("motivo") in fallos_busqueda_recuperables
    ):
        # Zoho puede rechazar /Contacts/search o demorar en indexarlo.
        # Reutilizar solo coincidencia unica del listado completo, y validar
        # su Cuenta asociada antes de continuar.
        listado_contacto = verificar_listado(
            "Contacts", "Email", contacto_data["Email"]
        )
        if listado_contacto["estado"] == "encontrado":
            contact_id = listado_contacto["registro_id"]
            # Si el listado encontro un Contacto reciente, comprobar su
            # Cuenta antes de poder usarlo (no asumir la relacion).
            try:
                respuesta = conexion["http_get"](
                    BASE + "/Contacts/" + contact_id,
                    headers={
                        "Authorization": "Zoho-oauthtoken "
                        + conexion["obtener_token"]()
                    },
                    params={"fields": "id,Account_Name"},
                    timeout=15,
                    allow_redirects=False,
                )
                if respuesta.status_code != 200:
                    return detener("contacto_no_verificado")
                filas = respuesta.json().get("data") or []
                vinculo = (filas[0].get("Account_Name") or {}) if len(filas) == 1 else {}
                if str(vinculo.get("id")) != account_id:
                    return detener("contacto_de_otra_cuenta")
            except Exception:
                return detener("contacto_no_verificado")
        elif listado_contacto["estado"] == "no_encontrado":
            contacto_data["Account_Name"] = {"id": account_id}
            respuesta = insertar("Contacts", contacto_data)
            if respuesta["estado"] != "creado":
                return respuesta
            contact_id = respuesta["registro_id"]
        else:
            return detener("listado_contactos_inconcluso")
    else:
        return detener("busqueda_contacto_inconclusa")

    # 4. Comprobar otra vez el Negocio.
    negocio = buscar("Deals", "Retell_Call_ID", call_id)

    if negocio["estado"] == "encontrado":
        return {
            "estado": "ya_registrado",
            "negocio_id": negocio["registro_id"],
        }

    if negocio["estado"] not in ("no_encontrado", "bloqueado"):
        return detener("segunda_busqueda_inconclusa")
    if negocio["estado"] == "bloqueado" and negocio.get("motivo") not in (
        "error_http", "error_consulta", "respuesta_invalida", "respuesta_ambigua",
        "registro_invalido", "campo_invalido", "id_invalido",
    ):
        return detener("segunda_busqueda_inconclusa")

    # Verificar el listado tambien inmediatamente antes del POST.
    # Protege reintentos tras timeout con escritura efectiva.
    listado_negocio = verificar_listado("Deals", "Retell_Call_ID", call_id)
    if listado_negocio["estado"] == "encontrado":
        return {
            "estado": "ya_registrado",
            "negocio_id": listado_negocio["registro_id"],
        }
    if listado_negocio["estado"] != "no_encontrado":
        return detener("segundo_listado_negocios_inconcluso")

    # 5. Preparar Negocio con relaciones verificadas.
    final = preparar_registros_cotizacion_sandbox(
        borrador,
        account_id=account_id,
        contact_id=contact_id,
    )

    if final.get("estado") != "registros_preparados":
        return detener("negocio_invalido")

    deal_data = final["negocio"]
    deal_data["Closing_Date"] = fecha_cierre
    deal_data["Owner"] = {"id": owner_id}

    respuesta = insertar("Deals", deal_data)

    if respuesta["estado"] != "creado":
        # No repetir el POST: Zoho puede haber confirmado internamente
        # la creacion aunque la respuesta no llegara a Retell/Render.
        # Solo una coincidencia exacta permite resolver la incertidumbre.
        if respuesta["estado"] == "resultado_incierto":
            confirmado = buscar("Deals", "Retell_Call_ID", call_id)
            if confirmado["estado"] == "encontrado":
                return {
                    "estado": "ya_registrado",
                    "negocio_id": confirmado["registro_id"],
                    "verificacion_posterior": "confirmada",
                }
            listado = verificar_listado("Deals", "Retell_Call_ID", call_id)
            if listado["estado"] == "encontrado":
                return {
                    "estado": "ya_registrado",
                    "negocio_id": listado["registro_id"],
                    "verificacion_posterior": "confirmada",
                }
        return respuesta

    return {
        "estado": "creado",
        "account_id": account_id,
        "contact_id": contact_id,
        "negocio_id": respuesta["registro_id"],
        "productos": final["cantidad_productos"],
    }
