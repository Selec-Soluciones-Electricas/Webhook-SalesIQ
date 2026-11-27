"""Resuelve Cuentas y Contactos para cotizaciones comerciales de Sofía.

NO se invoca desde el cron ni desde el escritor de Negocios todavía.
Bloqueado por defecto; exige autorización explícita y dos interruptores.
No modifica registros preexistentes. No registra datos personales en logs.
"""

import os

import requests

from services.retell_validadores import validar_rut_chileno
from services.sofia.busqueda_clientes_produccion import (
    buscar_cuenta_por_rut,
    buscar_contacto_por_correo,
    normalizar_rut,
)
from services.sofia.cotizaciones_sandbox import preparar_registros_cotizacion_sandbox
from services.sofia.crm_produccion import obtener_conexion_produccion

BASE = "https://www.zohoapis.com/crm/v8"


def _activo(nombre):
    return os.getenv(nombre, "false").strip().lower() == "true"


def _bloquear(motivo, estado="bloqueado"):
    return {"estado": estado, "motivo": motivo}


def _id_valido(ident):
    return isinstance(ident, str) and ident.isascii() and ident.isdecimal()


def _leer(conexion, token, modulo, ident, campos):
    try:
        respuesta = conexion["http_get"](
            f"{BASE}/{modulo}/{ident}",
            headers={"Authorization": "Zoho-oauthtoken " + token},
            params={"fields": campos}, timeout=20, allow_redirects=False,
        )
        if respuesta.status_code != 200:
            return None
        cuerpo = respuesta.json()
        filas = cuerpo.get("data") if isinstance(cuerpo, dict) else None
        if not isinstance(filas, list) or len(filas) != 1 or not isinstance(filas[0], dict):
            return None
        if str(filas[0].get("id") or "") != ident:
            return None
        return filas[0]
    except Exception:
        return None


def _listar_busqueda_segura(conexion, token, modulo, campo, valor):
    """Confirma unicidad/ausencia recorriendo todos los registros, o bloquea.

    Listados demasiado grandes/incompletos no autorizan insertar. Esto evita
    tratar un resultado incompleto o indexación tardía como ausencia.
    """
    encontrados = {}
    pagina_token = None
    for pagina in range(1, 21):
        parametros = {"fields": f"id,{campo}", "per_page": 200}
        if pagina <= 10:
            parametros["page"] = pagina
        else:
            if not isinstance(pagina_token, str) or not pagina_token:
                return _bloquear("paginacion_incompleta")
            parametros["page_token"] = pagina_token
        try:
            resp = conexion["http_get"](
                f"{BASE}/{modulo}",
                headers={"Authorization": "Zoho-oauthtoken " + token},
                params=parametros, timeout=20, allow_redirects=False,
            )
            if resp.status_code == 204 and pagina == 1:
                return {"estado": "no_encontrado"}
            if resp.status_code != 200:
                return _bloquear("listado_http_inconcluso")
            cuerpo = resp.json()
            filas = cuerpo.get("data") if isinstance(cuerpo, dict) else None
            info = cuerpo.get("info") if isinstance(cuerpo, dict) else None
            if not isinstance(filas, list) or not isinstance(info, dict) or type(info.get("more_records")) is not bool:
                return _bloquear("listado_invalido")
            for fila in filas:
                if not isinstance(fila, dict):
                    return _bloquear("fila_invalida")
                ident = str(fila.get("id") or "")
                if not _id_valido(ident):
                    return _bloquear("id_invalido")
                candidato = fila.get(campo)
                if modulo == "Accounts":
                    coincide = normalizar_rut(candidato) == valor
                else:
                    coincide = isinstance(candidato, str) and candidato.casefold() == valor.casefold()
                if coincide:
                    encontrados[ident] = True
            if info["more_records"] is False:
                if len(encontrados) > 1:
                    return _bloquear("duplicados_en_listado")
                return ({"estado": "encontrado", "registro_id": next(iter(encontrados))}
                        if encontrados else {"estado": "no_encontrado"})
            if pagina >= 10:
                pagina_token = info.get("next_page_token")
        except Exception:
            return _bloquear("listado_inconcluso")
    return _bloquear("listado_demasiado_grande")


def _insertar(conexion, token, modulo, datos, http_post):
    """Un POST por entidad, sin reintento ante error o resultado incierto."""
    try:
        resp = http_post(
            f"{BASE}/{modulo}",
            headers={"Authorization": "Zoho-oauthtoken " + token,
                     "Content-Type": "application/json"},
            json={"data": [datos], "trigger": []},
            timeout=20, allow_redirects=False,
        )
        cuerpo = resp.json()
        filas = cuerpo.get("data") if isinstance(cuerpo, dict) else None
        fila = filas[0] if isinstance(filas, list) and len(filas) == 1 and isinstance(filas[0], dict) else None
        if (resp.status_code in (200, 201) and isinstance(fila, dict)
                and fila.get("code") == "SUCCESS" and fila.get("status") == "success"):
            ident = str((fila.get("details") or {}).get("id") or "")
            if _id_valido(ident):
                return {"estado": "creado", "registro_id": ident}
        if resp.status_code in (400, 401, 403, 422):
            return _bloquear("zoho_rechazo_confirmado", "rechazado")
        return _bloquear("creacion_no_confirmada", "resultado_incierto")
    except Exception:
        return _bloquear("creacion_no_confirmada", "resultado_incierto")


def resolver_clientes_cotizacion_comercial(
    borrador, *, autorizar=False, conexion=None, http_post=None
):
    """Reutiliza o crea una Cuenta y un Contacto y devuelve sus IDs verificados.

    Requiere RUT con dígito verificador correcto, y autorizar=True. Nunca
    reasigna Contactos existentes; un vínculo ambiguo bloquea.
    """
    if (autorizar is not True
            or not _activo("SOFIA_PROD_COMMERCIAL_ENABLED")
            or not _activo("SOFIA_PROD_COMMERCIAL_CLIENTS_WRITES_ENABLED")
            or _activo("SOFIA_PROD_CRON_AUTO_ENABLED")
            or _activo("SOFIA_PROD_AUTO_TEST_ONLY")
            or _activo("SOFIA_PROD_CRON_PILOT_ENABLED")):
        return _bloquear("escritura_comercial_desactivada", "desactivado")

    preparado = preparar_registros_cotizacion_sandbox(borrador)
    if preparado.get("estado") != "registros_preparados":
        return _bloquear("datos_incompletos")
    cuenta_data = dict(preparado["cuenta"])
    contacto_data = dict(preparado["contacto"])
    rut = normalizar_rut(cuenta_data.get("Billing_Code"))
    if rut is None or not validar_rut_chileno(rut):
        return _bloquear("rut_real_invalido")
    correo = contacto_data.get("Email")
    if not isinstance(correo, str) or not correo.strip():
        return _bloquear("correo_faltante")
    if conexion is None:
        conexion = obtener_conexion_produccion()
    if (not isinstance(conexion, dict) or conexion.get("base") != "https://www.zohoapis.com"
            or not callable(conexion.get("obtener_token"))
            or not callable(conexion.get("http_get"))):
        return _bloquear("conexion_invalida")
    if http_post is None:
        http_post = requests.post
    if not callable(http_post):
        return _bloquear("escritor_invalido")

    try:
        token = conexion["obtener_token"]()
        if not isinstance(token, str) or not token:
            return _bloquear("token_no_disponible")
    except Exception:
        return _bloquear("token_no_disponible")

    conexion = dict(conexion)
    conexion["obtener_token"] = lambda: token
    cuenta = buscar_cuenta_por_rut(rut, conexion=conexion)
    contacto = buscar_contacto_por_correo(correo, conexion=conexion)
    if cuenta.get("estado") not in ("encontrado", "no_encontrado"):
        return _bloquear("cuenta_no_verificable")
    if contacto.get("estado") not in ("encontrado", "no_encontrado"):
        return _bloquear("contacto_no_verificable")
    account_id = cuenta.get("account_id")
    contact_id = contacto.get("contact_id")
    # No crear cuenta si un contacto ya existe y su cuenta no coincide.
    if contact_id and (not account_id or contacto.get("account_id") != account_id):
        return _bloquear("contacto_no_pertenece_a_cuenta")

    # Una búsqueda indexada no sustituye a la lectura directa del registro.
    if account_id:
        cuenta_leida = _leer(conexion, token, "Accounts", account_id, "id,Billing_Code")
        if not cuenta_leida or normalizar_rut(cuenta_leida.get("Billing_Code")) != rut:
            return _bloquear("cuenta_existente_no_verificable")
    if contact_id:
        contacto_leido = _leer(conexion, token, "Contacts", contact_id, "id,Email,Account_Name")
        vinculo = contacto_leido.get("Account_Name") if contacto_leido else None
        if (not isinstance(vinculo, dict) or str(vinculo.get("id") or "") != account_id
                or str(contacto_leido.get("Email") or "").casefold() != correo.casefold()):
            return _bloquear("contacto_existente_no_verificable")

    # Verificar listado de manera completa antes de crear Cuenta/Contacto.
    if account_id is None:
        listado = _listar_busqueda_segura(conexion, token, "Accounts", "Billing_Code", rut)
        if listado["estado"] == "encontrado":
            account_id = listado["registro_id"]
        elif listado["estado"] != "no_encontrado":
            return _bloquear("cuenta_sin_ausencia_confirmada")
        else:
            resultado = _insertar(conexion, token, "Accounts", cuenta_data, http_post)
            if resultado["estado"] != "creado":
                return resultado
            account_id = resultado["registro_id"]
            cuenta_leida = _leer(conexion, token, "Accounts", account_id, "id,Billing_Code")
            if not cuenta_leida or normalizar_rut(cuenta_leida.get("Billing_Code")) != rut:
                return _bloquear("cuenta_creada_no_verificable", "resultado_incierto")

    if contact_id is None:
        listado = _listar_busqueda_segura(conexion, token, "Contacts", "Email", correo)
        if listado["estado"] == "encontrado":
            contact_id = listado["registro_id"]
            contacto_leido = _leer(conexion, token, "Contacts", contact_id, "id,Email,Account_Name")
            vinculo = contacto_leido.get("Account_Name") if contacto_leido else None
            if (not isinstance(vinculo, dict) or str(vinculo.get("id") or "") != account_id
                    or str(contacto_leido.get("Email") or "").casefold() != correo.casefold()):
                return _bloquear("contacto_no_pertenece_a_cuenta")
        elif listado["estado"] != "no_encontrado":
            return _bloquear("contacto_sin_ausencia_confirmada")
        else:
            contacto_data["Account_Name"] = {"id": account_id}
            resultado = _insertar(conexion, token, "Contacts", contacto_data, http_post)
            if resultado["estado"] != "creado":
                return resultado
            contact_id = resultado["registro_id"]
            contacto_leido = _leer(conexion, token, "Contacts", contact_id, "id,Email,Account_Name")
            vinculo = contacto_leido.get("Account_Name") if contacto_leido else None
            if (not isinstance(vinculo, dict) or str(vinculo.get("id") or "") != account_id
                    or str(contacto_leido.get("Email") or "").casefold() != correo.casefold()):
                return _bloquear("contacto_creado_no_verificable", "resultado_incierto")

    return {"estado": "resueltos", "account_id": account_id, "contact_id": contact_id}
