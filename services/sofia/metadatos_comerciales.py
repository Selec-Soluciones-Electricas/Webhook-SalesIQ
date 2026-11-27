"""Preflight de campos comerciales Zoho CRM: SOLO LECTURA, fail-closed.

No incluye datos de clientes ni secretos en el resultado. Este chequeo protege
las escrituras ante campos ausentes, obligatorios adicionales y claves no únicas.
"""
from services.sofia.crm_produccion import obtener_conexion_produccion

BASE = "https://www.zohoapis.com/crm/v8"
CAMPOS = {
    "Accounts": ("Account_Name", "Billing_Code", "Phone"),
    "Contacts": ("First_Name", "Last_Name", "Email", "Phone", "Account_Name", "Clave_Sof_a_Contacto"),
    "Deals": (
        "Deal_Name", "Stage", "Closing_Date", "Type", "Lead_Source",
        "Retell_Call_ID", "Cantidad_de_productos", "Description",
        "Account_Name", "Contact_Name",
    ),
}
CLAVES_UNICAS = {
    "Accounts": "Billing_Code",
    "Contacts": "Clave_Sof_a_Contacto",
    "Deals": "Retell_Call_ID",
}
# Campos cuyo valor se asigna antes de crear el registro. Campos del sistema
# (Owner, Created_Time, etc.) no se incluyen en este conjunto.


def _unico(campo):
    valor = campo.get("unique")
    return valor is True or (isinstance(valor, dict) and bool(valor))


def diagnosticar_campos_comerciales(*, conexion=None):
    """GET metadata de los 3 módulos. Nunca realiza POST ni devuelve PII."""
    diagnostico = {"estado": "bloqueado", "modulos": {}}
    try:
        c = conexion if conexion is not None else obtener_conexion_produccion()
        if (not isinstance(c, dict) or c.get("base") != "https://www.zohoapis.com"
                or not callable(c.get("obtener_token"))
                or not callable(c.get("http_get"))):
            return {"estado": "bloqueado", "motivo": "conexion_invalida"}
        token = c["obtener_token"]()
        if not isinstance(token, str) or not token:
            return {"estado": "bloqueado", "motivo": "autenticacion_no_disponible"}
    except Exception:
        return {"estado": "bloqueado", "motivo": "autenticacion_no_disponible"}

    todos_listos = True
    for modulo, requeridos in CAMPOS.items():
        info = {"estado": "bloqueado", "faltantes": [], "no_creables": [],
                "obligatorios_extra": [], "sin_unicidad": [], "sin_permisos_o_metadatos": False}
        diagnostico["modulos"][modulo] = info
        try:
            r = c["http_get"](
                BASE + "/settings/fields",
                headers={"Authorization": "Zoho-oauthtoken " + token},
                params={"module": modulo}, timeout=20, allow_redirects=False,
            )
            info["http_status"] = int(r.status_code)
            if r.status_code != 200:
                try:
                    error = r.json()
                    codigo = error.get("code") if isinstance(error, dict) else None
                    permitidos = {
                        "OAUTH_SCOPE_MISMATCH",
                        "INVALID_OAUTHSCOPE",
                        "INVALID_OAUTHTOKEN",
                        "NO_PERMISSION",
                        "NOT_ALLOWED",
                        "INVALID_MODULE",
                        "INVALID_QUERY",
                    }
                    info["codigo_zoho"] = (
                        codigo if codigo in permitidos else "OTRO"
                    )
                except (ValueError, TypeError):
                    info["codigo_zoho"] = "SIN_CODIGO_JSON"
                info["sin_permisos_o_metadatos"] = True
                todos_listos = False
                continue
            cuerpo = r.json()
            filas = cuerpo.get("fields") if isinstance(cuerpo, dict) else None
            if not isinstance(filas, list) or not filas:
                info["sin_permisos_o_metadatos"] = True
                todos_listos = False
                continue
            indices = {}
            for campo in filas:
                if not isinstance(campo, dict) or not isinstance(campo.get("api_name"), str):
                    raise ValueError("metadatos_invalidos")
                nombre = campo["api_name"]
                if nombre in indices:
                    raise ValueError("campos_duplicados")
                indices[nombre] = campo
            info["faltantes"] = [n for n in requeridos if n not in indices]
            info["no_creables"] = [
                n for n in requeridos if n in indices and
                (not isinstance(indices[n].get("operation_type"), dict)
                 or indices[n]["operation_type"].get("api_create") is not True)
            ]
            info["obligatorios_extra"] = sorted(
                n for n, campo in indices.items()
                if campo.get("system_mandatory") is True and
                n not in requeridos and
                isinstance(campo.get("operation_type"), dict) and
                campo["operation_type"].get("api_create") is True
            )
            unico = CLAVES_UNICAS[modulo]
            if unico in indices and not _unico(indices[unico]):
                info["sin_unicidad"] = [unico]
            if not any((info["faltantes"], info["no_creables"],
                        info["obligatorios_extra"], info["sin_unicidad"])):
                info["estado"] = "listo"
            else:
                todos_listos = False
        except Exception as e:
            info["error_tipo"] = type(e).__name__
            info["sin_permisos_o_metadatos"] = True
            todos_listos = False
    diagnostico["estado"] = "listo" if todos_listos else "bloqueado"
    return diagnostico
