"""Resuelve Cuentas y Contactos para cotizaciones comerciales de Sofía.

NO se invoca desde el cron ni desde el escritor de Negocios todavía.
Bloqueado por defecto; exige autorización explícita y dos interruptores.
No modifica registros preexistentes. No registra datos personales en logs.
"""

import hashlib
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
CAMPO_CLAVE_CONTACTO = "Clave_Sof_a_Contacto"


def clave_contacto_sofia(account_id, correo):
    """Clave estable por Cuenta + correo, sin exponer el correo en texto plano.

    Accounts y Contacts ya deben haberse verificado. La unicidad se impone
    globalmente en Zoho sobre este campo, sin cambiar la unicidad de Email.
    """
    if not _id_valido(account_id) or not isinstance(correo, str) or not correo.strip():
        raise ValueError("contacto_invalido")
    digest = hashlib.sha256(correo.strip().casefold().encode("utf-8")).hexdigest()
    return "SFC1:" + str(account_id) + ":" + digest



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


def _listar_busqueda_segura(conexion, token, modulo, campo, valor, *, account_id=None):
    """Segunda busqueda exacta, sin barrer miles de Clientes/Contactos.

    El cron valida previamente la unicidad de Billing_Code y
    Clave_Sof_a_Contacto. Una ausencia indexada no garantiza por si sola
    inexistencia inmediata; ante una carrera, la clave unica de Zoho
    debe rechazar la insercion en lugar de duplicar el registro.
    """
    if modulo == "Accounts" and campo == "Billing_Code" and account_id is None:
        encontrado = buscar_cuenta_por_rut(valor, conexion=conexion)
        if encontrado.get("estado") == "encontrado":
            return {"estado": "encontrado", "registro_id": encontrado["account_id"]}
        if encontrado.get("estado") == "no_encontrado":
            return {"estado": "no_encontrado"}
        return _bloquear("cuenta_busqueda_inconclusa")
    if modulo == "Contacts" and campo == "Email" and account_id is not None:
        encontrado = buscar_contacto_por_correo(
            valor, account_id=account_id, conexion=conexion,
        )
        if encontrado.get("estado") == "encontrado":
            return {"estado": "encontrado", "registro_id": encontrado["contact_id"]}
        if encontrado.get("estado") == "no_encontrado":
            return {"estado": "no_encontrado"}
        return _bloquear("contacto_busqueda_inconclusa")
    return _bloquear("busqueda_no_autorizada")


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
    # En pruebas autorizadas se admite un RUT con formato válido aunque
    # falle su dígito verificador; la clave única de Zoho sigue protegiendo
    # las Cuentas y su asociación a Contactos.
    if rut is None or (
        not _activo("SOFIA_PROD_COMMERCIAL_RUT_SIN_DV_ENABLED")
        and not validar_rut_chileno(rut)
    ):
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
    if cuenta.get("estado") not in ("encontrado", "no_encontrado"):
        return _bloquear("cuenta_no_verificable")
    account_id = cuenta.get("account_id")
    contact_id = None

    # Una búsqueda indexada no sustituye a la lectura directa del registro.
    if account_id:
        cuenta_leida = _leer(conexion, token, "Accounts", account_id, "id,Billing_Code")
        if not cuenta_leida or normalizar_rut(cuenta_leida.get("Billing_Code")) != rut:
            return _bloquear("cuenta_existente_no_verificable")
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

    # Buscar por correo DENTRO de la cuenta ya verificada; un mismo correo
    # puede pertenecer a otra empresa sin que ello impida este contacto.
    contacto = buscar_contacto_por_correo(correo, account_id=account_id, conexion=conexion)
    if contacto.get("estado") not in ("encontrado", "no_encontrado"):
        return _bloquear("contacto_no_verificable")
    contact_id = contacto.get("contact_id")
    if contact_id and contacto.get("account_id") != account_id:
        return _bloquear("contacto_no_pertenece_a_cuenta")
    if contact_id:
        contacto_leido = _leer(conexion, token, "Contacts", contact_id, "id,Email,Account_Name")
        vinculo = contacto_leido.get("Account_Name") if contacto_leido else None
        if (not isinstance(vinculo, dict) or str(vinculo.get("id") or "") != account_id
                or str(contacto_leido.get("Email") or "").strip().casefold() != correo.strip().casefold()):
            return _bloquear("contacto_existente_no_verificable")

    if contact_id is None:
        listado = _listar_busqueda_segura(conexion, token, "Contacts", "Email", correo, account_id=account_id)
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
            contacto_data[CAMPO_CLAVE_CONTACTO] = clave_contacto_sofia(account_id, correo)
            resultado = _insertar(conexion, token, "Contacts", contacto_data, http_post)
            if resultado["estado"] != "creado":
                # DUPLICATE_DATA por la clave única no debe reintentarse con POST.
                # La ejecución siguiente puede localizar el Contacto existente.
                return resultado
            contact_id = resultado["registro_id"]
            contacto_leido = _leer(
                conexion, token, "Contacts", contact_id,
                "id,Email,Account_Name," + CAMPO_CLAVE_CONTACTO,
            )
            vinculo = contacto_leido.get("Account_Name") if contacto_leido else None
            if (not isinstance(vinculo, dict) or str(vinculo.get("id") or "") != account_id
                    or str(contacto_leido.get("Email") or "").strip().casefold() != correo.strip().casefold()
                    or contacto_leido.get(CAMPO_CLAVE_CONTACTO) != contacto_data[CAMPO_CLAVE_CONTACTO]):
                return _bloquear("contacto_creado_no_verificable", "resultado_incierto")

    return {"estado": "resueltos", "account_id": account_id, "contact_id": contact_id}
