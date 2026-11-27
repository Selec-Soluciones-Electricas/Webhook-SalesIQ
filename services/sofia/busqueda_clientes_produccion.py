"""Búsquedas seguras y EXCLUSIVAMENTE DE LECTURA de clientes de Sofía.

No crea, modifica ni vincula registros. Pensado para comprobar la unicidad
antes de incorporar escrituras comerciales a Zoho CRM producción.
"""

import re

from services.sofia.crm_produccion import obtener_conexion_produccion

BASE = "https://www.zohoapis.com/crm/v8"
_CORREO = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\Z")


def normalizar_rut(rut):
    if not isinstance(rut, str):
        return None
    normalizado = rut.replace(".", "").replace(" ", "").upper().strip()
    if not re.fullmatch(r"[0-9]{7,8}-[0-9K]", normalizado):
        return None
    return normalizado


def _id_valido(identificador):
    ident = str(identificador or "")
    return ident.isascii() and ident.isdecimal()


def _consultar(conexion, token, modulo, params):
    resp = conexion["http_get"](
        f"{BASE}/{modulo}/search",
        headers={"Authorization": "Zoho-oauthtoken " + token},
        params=params,
        timeout=20,
        allow_redirects=False,
    )
    if resp.status_code == 204:
        return {"estado": "sin_resultados", "registros": []}
    if resp.status_code != 200:
        return {"estado": "bloqueado", "motivo": "consulta_http_no_concluyente"}
    datos = resp.json()
    if not isinstance(datos, dict) or not isinstance(datos.get("data"), list):
        return {"estado": "bloqueado", "motivo": "respuesta_invalida"}
    info = datos.get("info") or {}
    if not isinstance(info, dict) or info.get("more_records") is True:
        return {"estado": "bloqueado", "motivo": "busqueda_incompleta"}
    return {"estado": "ok", "registros": datos["data"]}


def buscar_cuenta_por_rut(rut, *, conexion=None):
    """No supone ausencia si Zoho devuelve resultados parciales o errores."""
    rut_norm = normalizar_rut(rut)
    if rut_norm is None:
        return {"estado": "bloqueado", "motivo": "rut_formato_invalido"}
    if conexion is None:
        conexion = obtener_conexion_produccion()
    if conexion.get("base") != "https://www.zohoapis.com":
        return {"estado": "bloqueado", "motivo": "conexion_no_produccion"}

    variantes = {rut_norm, rut_norm.replace("-", "")}
    digitos, dv = rut_norm.split("-")
    if len(digitos) == 8:
        variantes.add(f"{digitos[:2]}.{digitos[2:5]}.{digitos[5:]}-{dv}")
    else:
        variantes.add(f"{digitos[0]}.{digitos[1:4]}.{digitos[4:]}-{dv}")
    try:
        token = conexion["obtener_token"]()
        coincidencias = {}
        resultados = False
        for variante in sorted(variantes):
            consulta = _consultar(
                conexion, token, "Accounts",
                {"criteria": f"(Billing_Code:equals:{variante})", "fields": "id,Account_Name,Billing_Code", "per_page": 200},
            )
            if consulta["estado"] == "bloqueado":
                return consulta
            for fila in consulta["registros"]:
                if not isinstance(fila, dict):
                    return {"estado": "bloqueado", "motivo": "fila_invalida"}
                resultados = True
                codigo = normalizar_rut(str(fila.get("Billing_Code") or ""))
                if codigo != rut_norm:
                    continue
                identificador = fila.get("id")
                if not _id_valido(identificador):
                    return {"estado": "bloqueado", "motivo": "id_invalido"}
                coincidencias[str(identificador)] = True
        if len(coincidencias) > 1:
            return {"estado": "bloqueado", "motivo": "rut_duplicado"}
        if len(coincidencias) == 1:
            return {"estado": "encontrado", "account_id": next(iter(coincidencias))}
        if resultados:
            return {"estado": "bloqueado", "motivo": "resultados_sin_coincidencia_exacta"}
        # Esto es una ausencia en búsquedas conocidas, no certifica unicidad global.
        return {"estado": "no_encontrado", "account_id": None}
    except Exception:
        return {"estado": "bloqueado", "motivo": "consulta_inconclusa"}


def buscar_contacto_por_correo(correo, *, account_id=None, conexion=None):
    if not isinstance(correo, str) or not _CORREO.fullmatch(correo.strip()):
        return {"estado": "bloqueado", "motivo": "correo_invalido"}
    correo = correo.strip()
    if account_id is not None and not _id_valido(account_id):
        return {"estado": "bloqueado", "motivo": "account_id_invalido"}
    if conexion is None:
        conexion = obtener_conexion_produccion()
    if conexion.get("base") != "https://www.zohoapis.com":
        return {"estado": "bloqueado", "motivo": "conexion_no_produccion"}
    try:
        token = conexion["obtener_token"]()
        consulta = _consultar(
            conexion, token, "Contacts",
            {"email": correo, "fields": "id,Email,Account_Name", "per_page": 200},
        )
        if consulta["estado"] == "bloqueado":
            return consulta
        if consulta["estado"] == "sin_resultados":
            return {"estado": "no_encontrado", "contact_id": None}
        coincidencias = {}
        for fila in consulta["registros"]:
            if not isinstance(fila, dict):
                return {"estado": "bloqueado", "motivo": "fila_invalida"}
            if str(fila.get("Email") or "").casefold() != correo.casefold():
                continue
            ident = fila.get("id")
            if not _id_valido(ident):
                return {"estado": "bloqueado", "motivo": "id_invalido"}
            coincidencias[str(ident)] = fila
        if len(coincidencias) > 1:
            return {"estado": "bloqueado", "motivo": "correo_duplicado"}
        if len(coincidencias) == 0:
            return {"estado": "bloqueado", "motivo": "resultados_sin_coincidencia_exacta"}
        contact_id, contacto = next(iter(coincidencias.items()))
        relacionado = contacto.get("Account_Name")
        relacionado_id = str(relacionado.get("id") or "") if isinstance(relacionado, dict) else ""
        if account_id is not None and relacionado_id != str(account_id):
            return {"estado": "bloqueado", "motivo": "contacto_cuenta_distinta_o_sin_vinculo"}
        return {"estado": "encontrado", "contact_id": contact_id, "account_id": relacionado_id or None}
    except Exception:
        return {"estado": "bloqueado", "motivo": "consulta_inconclusa"}
