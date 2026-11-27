"""Insercion individual de un Negocio de prueba en Zoho CRM Produccion.

No crea ni modifica Accounts/Contacts. Escrituras apagadas por defecto.
"""

import os
import re
from datetime import date, timedelta

import requests

from services.sofia.crm_produccion import obtener_conexion_produccion
from services.sofia.cotizaciones_sandbox import (
    preparar_borrador_cotizacion_sandbox,
    preparar_registros_cotizacion_sandbox,
)
from services.sofia.marcas_prueba import marcar_registro_prueba
from services.sofia.autorizacion_produccion import llamada_autorizada

BASE = "https://www.zohoapis.com/crm/v8"


def registrar_negocio_prueba_produccion(llamada):
    """Solo la llamada autorizada puede generar UN Deal marcado como prueba.

    Sin Accounts/Contacts nuevos, ni cambios a clientes actuales.
    No reintenta un POST en caso de resultado incierto.
    """
    def bloquear(motivo, estado="bloqueado"):
        return {"estado": estado, "motivo": motivo}

    if os.getenv("SOFIA_PROD_DEALS_WRITES_ENABLED", "false").strip().lower() != "true":
        return {"estado": "desactivado"}

    if not isinstance(llamada, dict):
        return bloquear("llamada_invalida")
    call_id = llamada.get("call_id")
    if (
        not isinstance(call_id, str)
        or not re.fullmatch(r"call_[A-Za-z0-9_-]{1,123}", call_id)
        or not llamada_autorizada("Deals", call_id, llamada.get("start_timestamp"))
    ):
        return bloquear("llamada_no_autorizada")

    borrador = preparar_borrador_cotizacion_sandbox(llamada)
    if not isinstance(borrador, dict) or borrador.get("estado") != "borrador_preparado":
        return bloquear("datos_por_revisar")
    if borrador.get("call_id") != call_id:
        return bloquear("call_id_inconsistente")
    preparados = preparar_registros_cotizacion_sandbox(borrador)
    if preparados.get("estado") != "registros_preparados":
        return bloquear("datos_invalidos")

    dias = os.getenv("SOFIA_PROD_DEALS_CLOSE_DAYS", "7").strip()
    if not dias.isdecimal() or not (1 <= int(dias) <= 90):
        return bloquear("fecha_cierre_invalida")

    # En produccion crear solo el Deal. La descripcion ya contiene
    # empresa, RUT, contacto y productos como fueron dictados.
    negocio = dict(preparados["negocio"])
    negocio["Closing_Date"] = (date.today() + timedelta(days=int(dias))).isoformat()
    try:
        negocio = marcar_registro_prueba("Deals", negocio)
    except (ValueError, TypeError):
        return bloquear("marca_prueba_invalida")

    # Asociar UNICAMENTE una Cuenta de prueba previamente creada
    # que tenga prefijo [PRUEBA SOFIA]. Sin esta configuracion,
    # se intenta crear el Deal sin Account_Name; Zoho puede rechazarlo.
    test_account_id = os.getenv("SOFIA_PROD_TEST_ACCOUNT_ID", "").strip()
    if test_account_id and (not test_account_id.isascii() or not test_account_id.isdecimal()):
        return bloquear("cuenta_prueba_invalida")

    try:
        conexion = obtener_conexion_produccion()
        if (
            not isinstance(conexion, dict)
            or conexion.get("base") != "https://www.zohoapis.com"
            or not callable(conexion.get("obtener_token"))
            or not callable(conexion.get("http_get"))
        ):
            return bloquear("conexion_invalida")
        token = conexion["obtener_token"]()
        if not isinstance(token, str) or not token:
            return bloquear("token_no_disponible")
        headers = {"Authorization": "Zoho-oauthtoken " + token}

        if test_account_id:
            respuesta_cuenta = conexion["http_get"](
                BASE + "/Accounts/" + test_account_id,
                headers=headers,
                params={"fields": "id,Account_Name"},
                timeout=20,
                allow_redirects=False,
            )
            if respuesta_cuenta.status_code != 200:
                return bloquear("cuenta_prueba_no_verificada")
            filas = respuesta_cuenta.json().get("data")
            if not isinstance(filas, list) or len(filas) != 1:
                return bloquear("cuenta_prueba_no_verificada")
            cuenta = filas[0]
            if (
                not isinstance(cuenta, dict)
                or str(cuenta.get("id")) != test_account_id
                or not str(cuenta.get("Account_Name") or "").startswith("[PRUEBA SOFIA]")
            ):
                return bloquear("cuenta_no_exclusiva_prueba")
            negocio["Account_Name"] = {"id": test_account_id}

        # Doble comprobacion, sin presumir ausencia si Zoho falla.
        busqueda = conexion["http_get"](
            BASE + "/Deals/search",
            headers=headers,
            params={"criteria": "(Retell_Call_ID:equals:" + call_id + ")", "fields": "id,Retell_Call_ID,Registro_de_prueba_Sof_a", "per_page": 2},
            timeout=20,
            allow_redirects=False,
        )
        if busqueda.status_code == 200:
            filas = busqueda.json().get("data")
            if not isinstance(filas, list):
                return bloquear("busqueda_inconclusa")
            coincidentes = [f for f in filas if isinstance(f, dict) and f.get("Retell_Call_ID") == call_id]
            if len(coincidentes) == 1 and str(coincidentes[0].get("id") or "").isdecimal():
                return {"estado": "ya_registrado", "deal_id": str(coincidentes[0]["id"]), "registro_de_prueba": coincidentes[0].get("Registro_de_prueba_Sof_a") is True}
            if len(coincidentes) > 1:
                return bloquear("duplicados_detectados")
        elif busqueda.status_code != 204:
            # /search puede fallar con INVALID_QUERY en algunas organizaciones.
            # Continuar solo si un listado completo demuestra ausencia.
            pass

        vistos = {}
        siguiente_token = None
        for pagina in range(1, 21):
            if busqueda.status_code == 204:
                break
            parametros = {
                "fields": "id,Retell_Call_ID,Registro_de_prueba_Sof_a",
                "per_page": 200,
            }
            if pagina <= 10:
                parametros["page"] = pagina
            else:
                # Zoho v8 requiere page_token despues de 2000 registros.
                if not isinstance(siguiente_token, str) or not siguiente_token:
                    return bloquear("token_paginacion_ausente")
                parametros["page_token"] = siguiente_token
            respuesta = conexion["http_get"](
                BASE + "/Deals",
                headers=headers,
                params=parametros,
                timeout=20,
                allow_redirects=False,
            )
            if respuesta.status_code == 204 and pagina == 1:
                break
            if respuesta.status_code != 200:
                # Solo pagina y HTTP; no filtrar datos sensibles de Zoho.
                return bloquear(f"listado_inconcluso_p{pagina}_http{respuesta.status_code}")
            cuerpo = respuesta.json()
            filas = cuerpo.get("data")
            info = cuerpo.get("info")
            if (
                not isinstance(filas, list)
                or not isinstance(info, dict)
                or type(info.get("more_records")) is not bool
            ):
                return bloquear("listado_invalido")
            for fila in filas:
                if not isinstance(fila, dict):
                    return bloquear("listado_invalido")
                if fila.get("Retell_Call_ID") == call_id:
                    ident = str(fila.get("id") or "")
                    if not ident.isascii() or not ident.isdecimal():
                        return bloquear("id_invalido")
                    vistos[ident] = fila.get("Registro_de_prueba_Sof_a") is True
            if info["more_records"] is False:
                break
            if pagina >= 10:
                # El token devuelto tras la pagina 10 permite continuar.
                siguiente_token = info.get("next_page_token")
                if not isinstance(siguiente_token, str) or not siguiente_token:
                    return bloquear("token_paginacion_ausente")
        else:
            # Si aun quedan Negocios sin revisar, no insertar ninguno.
            return bloquear("listado_incompleto")
        if len(vistos) == 1:
            return {"estado": "ya_registrado", "deal_id": next(iter(vistos)), "registro_de_prueba": next(iter(vistos.values()))}
        if vistos:
            return bloquear("duplicados_detectados")

        # Unico POST posible en este flujo: exclusivamente Deals.
        respuesta = requests.post(
            BASE + "/Deals",
            headers={**headers, "Content-Type": "application/json"},
            json={"data": [negocio], "trigger": []},
            timeout=20,
            allow_redirects=False,
        )
        try:
            cuerpo = respuesta.json()
        except ValueError:
            return bloquear("respuesta_invalida", "resultado_incierto")
        if not isinstance(cuerpo, dict):
            return bloquear("respuesta_invalida", "resultado_incierto")
        filas = cuerpo.get("data") or []
        fila = filas[0] if isinstance(filas, list) and len(filas) == 1 and isinstance(filas[0], dict) else {}
        ident = str((fila.get("details") or {}).get("id") or "")
        if (
            respuesta.status_code in (200, 201)
            and fila.get("code") == "SUCCESS"
            and fila.get("status") == "success"
            and ident.isascii() and ident.isdecimal()
        ):
            return {"estado": "creado", "deal_id": ident, "registro_de_prueba": True}

        # Los 400 de Zoho son rechazo confirmado; mostrar codigo seguro.
        if respuesta.status_code == 400:
            codigo = fila.get("code") or cuerpo.get("code")
            permitidos = {"MANDATORY_NOT_FOUND", "INVALID_DATA", "INVALID_MODULE", "DUPLICATE_DATA", "INVALID_REQUEST"}
            return {"estado": "rechazado", "motivo": codigo if codigo in permitidos else "datos_rechazados"}

        return bloquear("creacion_no_confirmada", "resultado_incierto")

    except requests.RequestException:
        return bloquear("conexion_no_confirmada", "resultado_incierto")
    except Exception:
        return bloquear("proceso_no_confirmado", "resultado_incierto")
