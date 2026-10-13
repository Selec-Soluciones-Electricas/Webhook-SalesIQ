import os
import time
import random
import requests
import unicodedata

from datetime import date, datetime, timedelta

from utils.security import (
    mask_email,
    safe_owner_for_log,
    mask_rut,
    mask_value,
    mask_phone,
)

from werkzeug.utils import secure_filename


ACCOUNTS_BASE = "https://accounts.zoho.com"
CRM_BASE = "https://www.zohoapis.com/crm/v2.1"


# =========================================================
# CONTACTO OBLIGATORIO ANTERIOR EN CRM
# =========================================================

CONTACT_NAME_ID = "4358923000074108191"
CONTACT_NAME_DEFAULT = "Cliente Web Cliente Web"


# =========================================================
# CACHE DEL ACCESS TOKEN
# =========================================================

access_token_cache = {
    "token": None,
    "expires_at": 0.0,
}


# =========================================================
# OWNERS POSIBLES
# =========================================================

OWNERS_POSIBLES = [
    {
        "nombre": os.environ.get(
            "OWNER_1_NAME",
            "Joaquin Gonzalez",
        ),
        "id": os.environ.get(
            "OWNER_1_ID",
            "",
        ),
        "email": os.environ.get(
            "OWNER_1_EMAIL",
            "",
        ),
    },
]


# =========================================================
# OBTENER ACCESS TOKEN
# =========================================================

def get_access_token() -> str:
    """
    Obtiene el access token de Zoho CRM utilizando
    el refresh token.

    El token se mantiene en cache para evitar solicitudes
    innecesarias a Zoho Accounts.
    """

    now = time.time()

    if (
        access_token_cache["token"]
        and access_token_cache["expires_at"] - 60 > now
    ):
        return access_token_cache["token"]

    client_id = os.environ.get(
        "ZOHO_CLIENT_ID"
    )

    client_secret = os.environ.get(
        "ZOHO_CLIENT_SECRET"
    )

    refresh_token = os.environ.get(
        "ZOHO_REFRESH_TOKEN"
    )

    if (
        not client_id
        or not client_secret
        or not refresh_token
    ):
        print(
            "ERROR: faltan "
            "ZOHO_CLIENT_ID / "
            "ZOHO_CLIENT_SECRET / "
            "ZOHO_REFRESH_TOKEN."
        )
        return None

    url = f"{ACCOUNTS_BASE}/oauth/v2/token"

    params = {
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
    }

    try:

        resp = requests.post(
            url,
            params=params,
            timeout=10,
        )

        print(
            "=== Respuesta refresh token Zoho ==="
        )

        print(
            resp.status_code
        )

        if resp.status_code != 200:
            return None

        data = resp.json()

        token = data.get(
            "access_token"
        )

        expires_in = int(
            data.get(
                "expires_in",
                3600,
            )
        )

        if not token:

            print(
                "ERROR: respuesta sin access_token."
            )

            return None

        access_token_cache["token"] = token

        access_token_cache["expires_at"] = (
            time.time() + expires_in
        )

        return token

    except Exception as e:

        print(
            "ERROR llamando a Zoho Accounts:",
            e,
        )

        return None

# =========================================================
# OBTENER ACCESS TOKEN PARA ZOHO CREATOR
# =========================================================

def get_creator_access_token() -> str:

    client_id = os.environ.get(
        "ZOHO_CREATOR_CLIENT_ID"
    )

    client_secret = os.environ.get(
        "ZOHO_CREATOR_CLIENT_SECRET"
    )

    refresh_token = os.environ.get(
        "ZOHO_CREATOR_REFRESH_TOKEN"
    )


    if (
        not client_id
        or not client_secret
        or not refresh_token
    ):

        print(
            "[Creator OAuth] "
            "Faltan credenciales de Creator."
        )

        return None


    url = (
        "https://accounts.zoho.com/"
        "oauth/v2/token"
    )


    params = {
        "refresh_token":
            refresh_token,

        "client_id":
            client_id,

        "client_secret":
            client_secret,

        "grant_type":
            "refresh_token",
    }


    try:

        response = requests.post(
            url,
            params=params,
            timeout=20,
        )


        print(
            "[Creator OAuth] "
            f"Status: {response.status_code}"
        )


        data = response.json()


        access_token = (
            data.get(
                "access_token"
            )
        )


        if not access_token:

            print(
                "[Creator OAuth] "
                "No se recibió access_token:",
                data,
            )

            return None


        return access_token


    except Exception as error:

        print(
            "[Creator OAuth] "
            "Error obteniendo token:",
            error,
        )

        return None

# =========================================================
# CACHE DEL ACCESS TOKEN — SALESIQ (independiente del de CRM)
# =========================================================

salesiq_access_token_cache = {
    "token": None,
    "expires_at": 0.0,
}

# ========================================================
# OBTENER ACCESS TOKEN PARA SALESIQ (independiente del de CRM)
# ========================================================
def get_salesiq_access_token() -> str:
    """
    Obtiene el access token de Zoho SalesIQ utilizando su PROPIO
    refresh token (independiente del que usa Zoho CRM).

    Variables de entorno requeridas:
        SALESIQ_CLIENT_ID
        SALESIQ_CLIENT_SECRET
        SALESIQ_REFRESH_TOKEN

    Este token se usa exclusivamente para acciones sobre SalesIQ
    (por ejemplo, etiquetar conversaciones vía
    agregar_tag_conversacion). No tiene relación con el token de
    CRM ni comparte su cache, por lo que un problema con uno no
    afecta al otro.
    """

    now = time.time()

    if (
        salesiq_access_token_cache["token"]
        and salesiq_access_token_cache["expires_at"] - 60 > now
    ):
        return salesiq_access_token_cache["token"]

    client_id = os.environ.get("SALESIQ_CLIENT_ID")
    client_secret = os.environ.get("SALESIQ_CLIENT_SECRET")
    refresh_token = os.environ.get("SALESIQ_REFRESH_TOKEN")

    if not client_id or not client_secret or not refresh_token:
        print(
            "[get_salesiq_access_token] ERROR: faltan "
            "SALESIQ_CLIENT_ID / SALESIQ_CLIENT_SECRET / "
            "SALESIQ_REFRESH_TOKEN. Se omite el etiquetado."
        )
        return None

    url = f"{ACCOUNTS_BASE}/oauth/v2/token"

    params = {
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
    }

    try:

        resp = requests.post(
            url,
            params=params,
            timeout=10,
        )

        print("=== Respuesta refresh token SalesIQ ===")
        print(resp.status_code)


        if resp.status_code != 200:
            return None

        data = resp.json()

        token = data.get("access_token")
        expires_in = int(data.get("expires_in", 3600))

        if not token:
            print(
                "[get_salesiq_access_token] "
                "ERROR: respuesta sin access_token."
            )
            return None

        salesiq_access_token_cache["token"] = token
        salesiq_access_token_cache["expires_at"] = (
            time.time() + expires_in
        )

        return token

    except Exception as e:

        print(
            "[get_salesiq_access_token] "
            f"ERROR llamando a Zoho Accounts: {e}"
        )

        return None


# =========================================================
# NORMALIZAR OWNER
# =========================================================

def normalizar_owner(
    owner: dict = None
) -> dict:
    """
    Normaliza la información del owner para asegurar
    una estructura consistente.
    """

    if owner is None:

        owner = random.choice(
            OWNERS_POSIBLES
        )

    owner = {
        "nombre": str(
            owner.get("nombre") or ""
        ).strip(),

        "id": str(
            owner.get("id") or ""
        ).strip(),

        "email": str(
            owner.get("email") or ""
        ).strip(),
    }

    print(
        f"[normalizar_owner] Owner final: "
        f"{safe_owner_for_log(owner)} / "
        f"email={mask_email(owner.get('email'))}"
    )

    return owner


# =========================================================
# CALCULAR CLOSING DATE
# =========================================================

def calcular_closing_date(
    fecha_base: date,
) -> str:
    """
    Calcula la fecha de cierre del Deal.

    Si el día es menor a 15:
        último día del mismo mes.

    Si el día es 15 o superior:
        último día del mes siguiente.
    """

    dia = fecha_base.day
    mes = fecha_base.month
    anio = fecha_base.year

    target_mes = mes
    target_anio = anio

    if dia >= 15:

        if mes == 12:

            target_mes = 1
            target_anio = anio + 1

        else:

            target_mes = mes + 1

    if target_mes in (
        4,
        6,
        9,
        11,
    ):

        ultimo_dia = 30

    elif target_mes == 2:

        es_bisiesto = (
            target_anio % 400 == 0
            or (
                target_anio % 4 == 0
                and target_anio % 100 != 0
            )
        )

        ultimo_dia = (
            29
            if es_bisiesto
            else 28
        )

    else:

        ultimo_dia = 31

    fecha_cierre = date(
        target_anio,
        target_mes,
        ultimo_dia,
    )

    return fecha_cierre.strftime(
        "%Y-%m-%d"
    )


# =========================================================
# NORMALIZAR NOMBRE DE EMPRESA PARA COMPARACION
# =========================================================

def normalizar_nombre_empresa(
    nombre: str
) -> str:
    """
    Normaliza el nombre de empresa solo para comparar
    registros.

    No modifica el nombre que se guarda en Zoho.

    Ignora:
    - mayúsculas/minúsculas
    - tildes
    - espacios repetidos
    """

    texto = str(
        nombre or ""
    ).strip().lower()

    texto = unicodedata.normalize(
        "NFKD",
        texto,
    ).encode(
        "ascii",
        "ignore",
    ).decode(
        "ascii"
    )

    return " ".join(
        texto.split()
    )


# =========================================================
# OBTENER O CREAR ACCOUNT
# =========================================================

def obtener_o_crear_account(
    campos: dict,
    owner: dict = None,
):

    access_token = get_access_token()

    if not access_token:

        print(
            "[obtener_o_crear_account] "
            "No se pudo obtener access token; "
            "se omite Accounts."
        )

        return None

    owner = normalizar_owner(
        owner
    )

    headers = {
        "Authorization": (
            f"Zoho-oauthtoken "
            f"{access_token}"
        ),
        "Content-Type": "application/json",
    }

    rut_raw = (
        campos.get("rut") or ""
    ).strip()

    empresa = (
        campos.get("empresa") or ""
    ).strip()

    telefono = (
        campos.get("telefono") or ""
    ).strip()

    # -----------------------------------------------------
    # NORMALIZAR RUT
    # -----------------------------------------------------

    rut_norm = (
        rut_raw
        .replace(".", "")
        .replace(" ", "")
        .upper()
    )

    empresa_norm = (
        normalizar_nombre_empresa(
            empresa
        )
    )

    print(
        f"[obtener_o_crear_account] "
        f"rut_raw={mask_rut(rut_raw)!r} "
        f"rut_norm={mask_rut(rut_norm)!r} "
        f"empresa={mask_value(empresa, 2, 0)!r} "
        f"empresa_norm={mask_value(empresa_norm, 2, 0)!r} "
        f"telefono={mask_phone(telefono)!r}"
    )

    if not rut_norm and not empresa:

        print(
            "[obtener_o_crear_account] "
            "Sin RUT ni empresa, "
            "no se crea/busca Account."
        )

        return None

    print(
        "[obtener_o_crear_account] "
        f"Owner elegido: "
        f"{safe_owner_for_log(owner)}"
    )

    # =====================================================
    # BUSCAR ACCOUNT POR RUT
    # =====================================================
    #
    # IMPORTANTE:
    #
    # EL RUT ES EL IDENTIFICADOR PRINCIPAL.
    #
    # Si encontramos una Account con el mismo RUT,
    # debemos reutilizarla aunque el nombre de empresa
    # recibido desde el chat sea diferente.
    #
    # Esto evita:
    #
    # Empresa A
    # RUT 12345678-9
    #
    # y posteriormente:
    #
    # Empresa B
    # RUT 12345678-9
    #
    # creando dos Accounts distintas.
    #
    # En este sistema:
    #
    # RUT existente = Account existente.
    #
    # =====================================================

    if rut_norm:

        try:

            criteria = (
                f"(Billing_Code:equals:{rut_norm})"
            )

            search_url = (
                f"{CRM_BASE}/Accounts/search"
            )

            params = {
                "criteria": criteria
            }

            resp = requests.get(
                search_url,
                headers=headers,
                params=params,
                timeout=10,
            )

            print(
                "[obtener_o_crear_account] "
                "=== Búsqueda Account por Billing_Code ==="
            )

            print(
                resp.status_code
            )

            if resp.status_code == 200:

                body = resp.json()

                registros = (
                    body.get("data") or []
                )

                if registros:

                    print(
                        "[obtener_o_crear_account] "
                        f"Se encontraron {len(registros)} "
                        "Account(s) con el mismo RUT."
                    )

                    # -------------------------------------------------
                    # RUT ENCONTRADO
                    # -------------------------------------------------
                    #
                    # AQUÍ ESTÁ LA CORRECCIÓN PRINCIPAL.
                    #
                    # Antes se comparaba:
                    #
                    # RUT + nombre empresa
                    #
                    # Ahora:
                    #
                    # RUT = Account
                    #
                    # El nombre enviado por el usuario NO hace que
                    # descartemos la Account.
                    # -------------------------------------------------

                    for registro in registros:

                        account_id = str(
                            registro.get("id") or ""
                        ).strip()

                        if not account_id:
                            continue

                        account_name_actual = str(
                            registro.get(
                                "Account_Name"
                            ) or ""
                        ).strip()

                        account_rut = str(
                            registro.get(
                                "Billing_Code"
                            ) or ""
                        ).strip()

                        print(
                            "[obtener_o_crear_account] "
                            "Account encontrada por RUT: "
                            f"ID={mask_value(account_id, 2, 2)} "
                            f"empresa={mask_value(account_name_actual, 2, 0)!r} "
                            f"rut={mask_rut(account_rut)!r}"
                        )

                        print(
                            "[obtener_o_crear_account] "
                            "RUT existente detectado. "
                            "Se reutilizará esta Account "
                            "sin importar si el nombre recibido "
                            "desde el chat es diferente."
                        )

                        return str(
                            account_id
                        )

            elif resp.status_code == 204:

                print(
                    "[obtener_o_crear_account] "
                    "Zoho no encontró Account "
                    "para el RUT indicado."
                )

            else:

                print(
                    "[obtener_o_crear_account] "
                    "La búsqueda por RUT devolvió "
                    f"HTTP {resp.status_code}."
                )

        except Exception as e:

            print(
                "[obtener_o_crear_account] "
                "ERROR buscando Account por RUT:",
                e,
            )

    # =====================================================
    # SI NO EXISTE RUT EN ZOHO:
    # CREAR ACCOUNT NUEVO
    # =====================================================

    account_name = (
        empresa
        or rut_norm
        or "Sin nombre"
    )

    print(
        "[obtener_o_crear_account] "
        "No existe Account con el RUT indicado. "
        "Se creará una nueva Account."
    )

    account_data_full = {
        "Account_Name": account_name,
        "Billing_Code": rut_norm or None,
        "Phone": telefono or None,
        "Cliente_Selec": "NO",
        "Industry": "Por definir",
        "Region1": "Por definir",
        "Ciudad_I": "Por definir",
        "Website": "www.pordefinir.com",
    }

    if owner.get("id"):

        account_data_full["Owner"] = {
            "id": owner["id"]
        }

    def post_account(
        account_data: dict,
    ):

        create_url = (
            f"{CRM_BASE}/Accounts"
        )

        payload = {
            "data": [
                account_data
            ]
        }

        print(
            "[obtener_o_crear_account] "
            "Payload Account:",
            payload,
        )

        return requests.post(
            create_url,
            headers=headers,
            json=payload,
            timeout=10,
        )

    try:

        resp = post_account(
            account_data_full
        )

        print(
            "[obtener_o_crear_account] "
            "=== Creación Account ==="
        )

        print(
            resp.status_code
        )

        try:

            print(
                resp.text
            )

        except Exception:
            pass

        if resp.status_code in (
            200,
            201,
        ):

            body = resp.json()

            registros = (
                body.get("data") or []
            )

            if registros:

                details = (
                    registros[0].get(
                        "details"
                    )
                    or registros[0]
                )

                account_id = (
                    details.get(
                        "id"
                    )
                )

                if account_id:

                    print(
                        "[obtener_o_crear_account] "
                        f"Account creada "
                        f"ID={mask_value(account_id, 2, 2)}"
                    )

                    return str(
                        account_id
                    )

        # =================================================
        # FALLBACK
        # =================================================

        if resp.status_code == 400:

            print(
                "[obtener_o_crear_account] "
                "Creación rechazada (400). "
                "Reintentando con payload mínimo..."
            )

            account_data_min = {
                "Account_Name": account_name,
                "Phone": telefono or None,
            }

            if rut_norm:

                account_data_min[
                    "Billing_Code"
                ] = rut_norm

            if owner.get("id"):

                account_data_min[
                    "Owner"
                ] = {
                    "id": owner["id"]
                }

            resp2 = post_account(
                account_data_min
            )

            print(
                "[obtener_o_crear_account] "
                "=== Creación Account fallback ==="
            )

            print(
                resp2.status_code
            )

            try:

                print(
                    resp2.text
                )

            except Exception:
                pass

            if resp2.status_code in (
                200,
                201,
            ):

                body2 = resp2.json()

                registros2 = (
                    body2.get("data") or []
                )

                if registros2:

                    details2 = (
                        registros2[0].get(
                            "details"
                        )
                        or registros2[0]
                    )

                    account_id2 = (
                        details2.get(
                            "id"
                        )
                    )

                    if account_id2:

                        print(
                            "[obtener_o_crear_account] "
                            f"Account creada "
                            f"(fallback) "
                            f"ID={mask_value(account_id2, 2, 2)}"
                        )

                        return str(
                            account_id2
                        )

    except Exception as e:

        print(
            "[obtener_o_crear_account] "
            "ERROR creando Account:",
            e,
        )

    return None


# =========================================================
# OBTENER O CREAR CONTACT
# =========================================================

def obtener_o_crear_contact(
    campos: dict,
    account_id: str = None,
    owner: dict = None,
):

    access_token = get_access_token()

    if not access_token:

        print(
            "[obtener_o_crear_contact] "
            "No se pudo obtener access token; "
            "se omite Contacts."
        )

        return None

    owner = normalizar_owner(
        owner
    )

    headers = {
        "Authorization": (
            f"Zoho-oauthtoken "
            f"{access_token}"
        ),
        "Content-Type": "application/json",
    }

    contacto_full = str(
        campos.get("contacto") or ""
    ).strip()

    correo = str(
        campos.get("correo") or ""
    ).strip()

    telefono = str(
        campos.get("telefono") or ""
    ).strip()

    print(
        f"[obtener_o_crear_contact] "
        f"contacto={mask_value(contacto_full, 2, 0)!r} "
        f"correo={mask_email(correo)!r} "
        f"telefono={mask_phone(telefono)!r} "
        f"account_id={mask_value(account_id, 2, 2)!r}"
    )

    if not correo:

        print(
            "[obtener_o_crear_contact] "
            "Sin correo, no se puede "
            "crear/buscar Contact."
        )

        return None

    # =====================================================
    # SEPARAR NOMBRE
    # =====================================================

    nombre_partes = [
        p
        for p in contacto_full.split()
        if p.strip()
    ]

    if len(nombre_partes) >= 2:

        first_name = " ".join(
            nombre_partes[:-1]
        ).strip()

        last_name = (
            nombre_partes[-1]
            .strip()
        )

    elif len(nombre_partes) == 1:

        first_name = (
            nombre_partes[0]
            .strip()
        )

        last_name = "Cliente"

    else:

        first_name = "Cliente Web"
        last_name = "Cliente Web"

    # =====================================================
    # BUSCAR CONTACT POR EMAIL
    # =====================================================

    try:

        search_url = (
            f"{CRM_BASE}/Contacts/search"
        )

        params = {
            "email": correo
        }

        resp = requests.get(
            search_url,
            headers=headers,
            params=params,
            timeout=10,
        )

        print(
            "[obtener_o_crear_contact] "
            "=== Búsqueda Contact por email ==="
        )

        print(
            resp.status_code
        )

        try:

            print(
                resp.text
            )

        except Exception:
            pass

        if resp.status_code == 200:

            body = resp.json()

            registros = (
                body.get("data") or []
            )

            if (
                registros
                and registros[0].get("id")
            ):

                contact_id = (
                    registros[0]["id"]
                )

                print(
                    "[obtener_o_crear_contact] "
                    f"Contact encontrado "
                    f"ID={mask_value(contact_id, 2, 2)}"
                )

                # =========================================
                # ACTUALIZAR CONTACT EXISTENTE
                # =========================================

                try:

                    actual = registros[0]

                    acc_actual = (
                        actual.get(
                            "Account_Name"
                        )
                    )

                    acc_actual_id = ""

                    if isinstance(
                        acc_actual,
                        dict,
                    ):

                        acc_actual_id = str(
                            acc_actual.get(
                                "id"
                            )
                            or ""
                        ).strip()

                    needs_update = False

                    update_data = {
                        "id": contact_id
                    }

                    if (
                        account_id
                        and acc_actual_id
                        != account_id
                    ):

                        update_data[
                            "Account_Name"
                        ] = {
                            "id": account_id
                        }

                        needs_update = True

                        print(
                            "[obtener_o_crear_contact] "
                            "Actualizando Account_Name "
                            "del Contact existente."
                        )

                    if not str(
                        actual.get("Cargo")
                        or ""
                    ).strip():

                        update_data[
                            "Cargo"
                        ] = "Cliente Web"

                        needs_update = True

                    if not str(
                        actual.get("Lead_Source")
                        or ""
                    ).strip():

                        update_data[
                            "Lead_Source"
                        ] = "Chat Pag Web"

                        needs_update = True

                    if (
                        telefono
                        and not str(
                            actual.get("Phone")
                            or ""
                        ).strip()
                    ):

                        update_data[
                            "Phone"
                        ] = telefono

                        needs_update = True

                    if needs_update:

                        payload_upd = {
                            "data": [
                                update_data
                            ]
                        }

                        upd_url = (
                            f"{CRM_BASE}/Contacts"
                        )

                        upd_resp = requests.put(
                            upd_url,
                            headers=headers,
                            json=payload_upd,
                            timeout=10,
                        )

                        print(
                            "[obtener_o_crear_contact] "
                            "=== Update Contact existente ==="
                        )

                        print(
                            upd_resp.status_code
                        )

                        try:

                            print(
                                upd_resp.text
                            )

                        except Exception:
                            pass

                except Exception as e_upd:

                    print(
                        "[obtener_o_crear_contact] "
                        "ERROR actualizando "
                        "Contact existente:",
                        e_upd,
                    )

                return contact_id

    except Exception as e:

        print(
            "[obtener_o_crear_contact] "
            "ERROR buscando Contact por email:",
            e,
        )

    # =====================================================
    # CREAR CONTACT
    # =====================================================

    contact_data = {
        "First_Name": first_name,
        "Last_Name": last_name,
        "Cargo": "Cliente Web",
        "Lead_Source": "Chat Pag Web",
        "Email": correo,
    }

    if telefono:

        contact_data[
            "Phone"
        ] = telefono

    if account_id:

        contact_data[
            "Account_Name"
        ] = {
            "id": account_id
        }

    if owner.get("id"):

        contact_data[
            "Owner"
        ] = {
            "id": owner["id"]
        }

    payload = {
        "data": [
            contact_data
        ]
    }

    create_url = (
        f"{CRM_BASE}/Contacts"
    )

    try:

        print(
            "[obtener_o_crear_contact] "
            "=== Creación Contact ==="
        )

        print(
            "[obtener_o_crear_contact] "
            "Payload Contact:",
            payload,
        )

        resp = requests.post(
            create_url,
            headers=headers,
            json=payload,
            timeout=10,
        )

        print(
            resp.status_code
        )

        try:

            print(
                resp.text
            )

        except Exception:
            pass

        if resp.status_code in (
            200,
            201,
        ):

            body = resp.json()

            registros = (
                body.get("data") or []
            )

            if registros:

                details = (
                    registros[0].get(
                        "details"
                    )
                    or registros[0]
                )

                contact_id = (
                    details.get(
                        "id"
                    )
                )

                if contact_id:

                    print(
                        "[obtener_o_crear_contact] "
                        f"Contact creado "
                        f"ID={mask_value(contact_id, 2, 2)}"
                    )

                    return contact_id

        try:

            print(
                "[obtener_o_crear_contact] "
                "Error JSON:",
                resp.json(),
            )

        except Exception:
            pass

    except Exception as e:

        print(
            "[obtener_o_crear_contact] "
            "ERROR creando Contact:",
            e,
        )

    return None

# =========================================================
# SUBIR ARCHIVOS AL NEGOCIO EN ZOHO CRM
# =========================================================

def subir_archivos_negocio(
    deal_id: str,
    productos: list,
):
    """
    Sube al Negocio de Zoho CRM los archivos adjuntos
    enviados desde el formulario de cotización.

    Los archivos se identifican según el producto al
    que pertenecen.

    Ejemplo:
        Producto_1_foto_motor.jpg
        Producto_2_ficha_tecnica.pdf
    """

    deal_id = str(
        deal_id or ""
    ).strip()

    if not deal_id:

        print(
            "[subir_archivos_negocio] "
            "No se recibió Deal ID."
        )

        return []


    if not productos:

        print(
            "[subir_archivos_negocio] "
            "No hay productos."
        )

        return []


    # =====================================================
    # TOKEN
    # =====================================================

    access_token = get_access_token()

    if not access_token:

        print(
            "[subir_archivos_negocio] "
            "No se pudo obtener access token."
        )

        return []


    # =====================================================
    # ENDPOINT CRM
    # =====================================================

    url = (
        "https://www.zohoapis.com/"
        f"crm/v8/Deals/{deal_id}/Attachments"
    )


    headers = {
        "Authorization":
            f"Zoho-oauthtoken {access_token}"
    }


    resultados = []


    # =====================================================
    # RECORRER PRODUCTOS
    # =====================================================

    for indice_producto, producto in enumerate(
        productos,
        start=1,
    ):

        archivos = (
            producto.get("archivos")
            or []
        )


        if not archivos:

            continue


        # =================================================
        # RECORRER ARCHIVOS DEL PRODUCTO
        # =================================================

        for indice_archivo, archivo in enumerate(
            archivos,
            start=1,
        ):

            nombre_original = str(
                getattr(
                    archivo,
                    "filename",
                    "",
                )
                or ""
            ).strip()


            if not nombre_original:

                continue


            # =============================================
            # NOMBRE SEGURO
            # =============================================

            nombre_seguro = secure_filename(
                nombre_original
            )


            if not nombre_seguro:

                nombre_seguro = (
                    f"archivo_{indice_archivo}"
                )


            nombre_zoho = (
                f"Producto_{indice_producto}_"
                f"{nombre_seguro}"
            )


            tipo_contenido = str(
                getattr(
                    archivo,
                    "mimetype",
                    "",
                )
                or
                "application/octet-stream"
            )


            try:

                # =========================================
                # REINICIAR STREAM
                # =========================================

                try:

                    archivo.stream.seek(0)

                except Exception:

                    pass


                # =========================================
                # MULTIPART
                # =========================================

                files = {
                    "file": (
                        nombre_zoho,
                        archivo.stream,
                        tipo_contenido,
                    )
                }


                print(
                    "[subir_archivos_negocio] "
                    f"Subiendo {nombre_zoho} "
                    f"al Deal {deal_id}..."
                )


                response = requests.post(
                    url,
                    headers=headers,
                    files=files,
                    timeout=30,
                )


                print(
                    "[subir_archivos_negocio] "
                    f"Status: {response.status_code}"
                )


                try:

                    print(
                        "[subir_archivos_negocio] "
                        f"Respuesta: {response.text}"
                    )

                except Exception:

                    pass


                resultado = {
                    "producto":
                        indice_producto,

                    "archivo":
                        nombre_zoho,

                    "status":
                        response.status_code,

                    "ok":
                        response.status_code
                        in (
                            200,
                            201,
                        ),
                }


                resultados.append(
                    resultado
                )


                # =========================================
                # REINICIAR NUEVAMENTE EL ARCHIVO
                # =========================================
                #
                # Esto es importante porque después vamos
                # a reutilizar el mismo archivo para
                # enviarlo también a Zoho Creator.
                # =========================================

                try:

                    archivo.stream.seek(0)

                except Exception:

                    pass


            except Exception as error:

                print(
                    "[subir_archivos_negocio] "
                    f"ERROR subiendo "
                    f"{nombre_zoho}:",
                    error,
                )


                resultados.append({
                    "producto":
                        indice_producto,

                    "archivo":
                        nombre_zoho,

                    "status":
                        0,

                    "ok":
                        False,

                    "error":
                        str(error),
                })


    return resultados

# =========================================================
# OBTENER ID DE LA LICITACIÓN CREADA EN ZOHO CREATOR
# =========================================================

def obtener_creator_record_id(
    deal_id: str,
    access_token: str,
):
    """
    Espera a que la automatización CRM -> Creator
    genere la Licitación y escriba el link en el campo
    Zoho_One_Negocio del Deal.

    Del link se obtiene el recLinkID de Creator.
    """

    deal_id = str(
        deal_id or ""
    ).strip()

    if not deal_id:
        return None


    url = (
        "https://www.zohoapis.com/"
        f"crm/v8/Deals/{deal_id}"
    )


    headers = {
        "Authorization":
            f"Zoho-oauthtoken {access_token}"
    }


    params = {
        "fields":
            "Zoho_One_Negocio"
    }


    # =====================================================
    # ESPERAR AUTOMATIZACIÓN CRM -> CREATOR
    # =====================================================

    for intento in range(
        1,
        13,
    ):

        try:

            response = requests.get(
                url,
                headers=headers,
                params=params,
                timeout=20,
            )


            if response.status_code == 200:

                data = response.json()

                registros = (
                    data.get("data")
                    or []
                )


                if registros:

                    creator_url = str(
                        registros[0].get(
                            "Zoho_One_Negocio"
                        )
                        or ""
                    ).strip()


                    if "recLinkID=" in creator_url:

                        parte = creator_url.split(
                            "recLinkID=",
                            1,
                        )[1]


                        creator_record_id = (
                            parte.split(
                                "&",
                                1,
                            )[0]
                            .strip()
                        )


                        if creator_record_id:

                            print(
                                "[Creator archivos] "
                                "Licitación encontrada: "
                                f"{creator_record_id}"
                            )

                            return (
                                creator_record_id
                            )


            print(
                "[Creator archivos] "
                "Esperando creación de la "
                f"Licitación... intento {intento}/12"
            )


        except Exception as error:

            print(
                "[Creator archivos] "
                "Error consultando link:",
                error,
            )


        time.sleep(1)


    print(
        "[Creator archivos] "
        "No se encontró el link de Creator "
        "después de esperar."
    )

    return None


# =========================================================
# SUBIR ARCHIVOS A ZOHO CREATOR
# =========================================================

def subir_archivos_creator(
    deal_id: str,
    productos: list,
):
    """
    Sube a la Licitación de Zoho Creator los mismos
    archivos que fueron adjuntados al Negocio en CRM.

    El campo destino en Creator es:
        Archivos

    Los archivos se identifican por producto.
    """

    deal_id = str(
        deal_id or ""
    ).strip()


    if not deal_id:

        print(
            "[Creator archivos] "
            "No se recibió Deal ID."
        )

        return []


    if not productos:

        return []


    # =====================================================
    # ACCESS TOKENS
    # =====================================================

    # Token exclusivo para Zoho Creator
    creator_access_token = (
        get_creator_access_token()
    )

    if not creator_access_token:

        print(
            "[Creator archivos] "
            "No fue posible obtener access token de Creator."
        )

        return []


    # Token normal de Zoho CRM
    # Se utiliza para consultar Zoho_One_Negocio
    crm_access_token = (
        get_access_token()
    )

    if not crm_access_token:

        print(
            "[Creator archivos] "
            "No fue posible obtener access token de CRM."
        )

        return []


    # =====================================================
    # BUSCAR REGISTRO CREADO EN CREATOR
    # =====================================================

    creator_record_id = (
        obtener_creator_record_id(
            deal_id,
            crm_access_token,
        )
    )


    if not creator_record_id:

        return []


    # =====================================================
    # URL CREATOR
    # =====================================================

    url = (
        "https://www.zohoapis.com/"
        "creator/v2.1/data/"
        "selecspa/"
        "selec/"
        "report/"
        "Licitaci_n_Report/"
        f"{creator_record_id}/"
        "Archivos/"
        "upload"
    )


    headers = {
        "Authorization":
            f"Zoho-oauthtoken {creator_access_token}"
    }


    # Evita que subir cada archivo vuelva a disparar
    # todos los workflows de la Licitación.
    params = {
        "skip_workflow":
            '["all"]'
    }


    resultados = []


    # =====================================================
    # RECORRER PRODUCTOS
    # =====================================================

    for indice_producto, producto in enumerate(
        productos,
        start=1,
    ):

        archivos = (
            producto.get("archivos")
            or []
        )


        for indice_archivo, archivo in enumerate(
            archivos,
            start=1,
        ):

            nombre_original = str(
                getattr(
                    archivo,
                    "filename",
                    "",
                )
                or ""
            ).strip()


            if not nombre_original:

                continue


            nombre_seguro = secure_filename(
                nombre_original
            )


            if not nombre_seguro:

                nombre_seguro = (
                    f"archivo_{indice_archivo}"
                )


            nombre_creator = (
                f"Producto_{indice_producto}_"
                f"{nombre_seguro}"
            )


            tipo_contenido = str(
                getattr(
                    archivo,
                    "mimetype",
                    "",
                )
                or
                "application/octet-stream"
            )


            try:

                # Volvemos al inicio del archivo.
                archivo.stream.seek(0)


                files = {
                    "file": (
                        nombre_creator,
                        archivo.stream,
                        tipo_contenido,
                    )
                }


                print(
                    "[Creator archivos] "
                    f"Subiendo {nombre_creator}..."
                )


                response = requests.post(
                    url,
                    headers=headers,
                    params=params,
                    files=files,
                    timeout=60,
                )


                print(
                    "[Creator archivos] "
                    f"Status: {response.status_code}"
                )


                try:

                    respuesta_json = (
                        response.json()
                    )

                except Exception:

                    respuesta_json = {
                        "respuesta":
                            response.text
                    }


                print(
                    "[Creator archivos] "
                    "Respuesta:",
                    respuesta_json,
                )


                codigo_creator = (
                    respuesta_json.get(
                        "code"
                    )
                    if isinstance(
                        respuesta_json,
                        dict,
                    )
                    else None
                )


                ok = (
                    response.status_code
                    in (
                        200,
                        201,
                    )
                    and codigo_creator
                    in (
                        3000,
                        "3000",
                    )
                )


                resultados.append({
                    "producto":
                        indice_producto,

                    "archivo":
                        nombre_creator,

                    "ok":
                        ok,

                    "status":
                        response.status_code,

                    "respuesta":
                        respuesta_json,
                })


                # Lo dejamos nuevamente al inicio
                # por seguridad.
                archivo.stream.seek(0)


            except Exception as error:

                print(
                    "[Creator archivos] "
                    f"ERROR con {nombre_creator}:",
                    error,
                )


                resultados.append({
                    "producto":
                        indice_producto,

                    "archivo":
                        nombre_creator,

                    "ok":
                        False,

                    "error":
                        str(error),
                })


    return resultados

# =========================================================
# CREAR DEAL EN ZOHO CRM
# =========================================================

def crear_deal_en_zoho(
    campos: dict,
    account_id: str = None,
    contact_id: str = None,
    owner: dict = None,
):

    access_token = get_access_token()

    if not access_token:

        print(
            "[crear_deal_en_zoho] "
            "No se pudo obtener access token "
            "de Zoho; se omite creación de Deal."
        )

        return None, None


    # =====================================================
    # OWNER
    # =====================================================

    owner = normalizar_owner(
        owner
    )


    # =====================================================
    # FECHAS
    # =====================================================

    ahora = datetime.now().astimezone()

    manana = (
        ahora
        + timedelta(days=1)
    )

    fecha_hora_1_str = (
        manana.isoformat(
            timespec="seconds"
        )
    )

    fecha_limite_oferta = (
        manana.date()
    )

    closing_date_str = (
        calcular_closing_date(
            fecha_limite_oferta
        )
    )


    # =====================================================
    # URL / HEADERS
    # =====================================================

    url = (
        f"{CRM_BASE}/Deals"
    )

    headers = {
        "Authorization": (
            f"Zoho-oauthtoken "
            f"{access_token}"
        ),
        "Content-Type": "application/json",
    }


    print(
        "[crear_deal_en_zoho] "
        f"Owner elegido: "
        f"{safe_owner_for_log(owner)}"
    )


    # =====================================================
    # NOMBRE DEL NEGOCIO
    # =====================================================
    #
    # Se genera un número aleatorio de 6 dígitos
    # para identificar fácilmente la cotización.
    #
    # Ejemplo:
    # Cotización - 583742
    # =====================================================

    identificador_cotizacion = (
        random.randint(
            100000,
            999999,
        )
    )

    deal_name = (
        f"Cotización - "
        f"{identificador_cotizacion}"
    )


    # =====================================================
    # PRODUCTOS
    # =====================================================
    #
    # El formulario nuevo puede enviar varios productos.
    #
    # Se guardan dentro de Description del Negocio.
    # Esa información posteriormente aparece en
    # el campo Notas de Zoho Creator.
    # =====================================================

    productos = (
        campos.get(
            "productos"
        )
        or []
    )


    # =====================================================
    # COMPATIBILIDAD CON FLUJO ANTIGUO
    # =====================================================
    #
    # Si el flujo antiguo envía un solo producto,
    # lo convertimos a la nueva estructura.
    # =====================================================

    if not productos:

        productos = [
            {
                "numero_parte":
                    campos.get(
                        "num_parte"
                    )
                    or "",

                "marca":
                    campos.get(
                        "marca"
                    )
                    or "",

                "descripcion":
                    campos.get(
                        "descripcion"
                    )
                    or "",

                "cantidad":
                    campos.get(
                        "cantidad"
                    )
                    or "1",
            }
        ]


    # =====================================================
    # CREAR NOTAS DE PRODUCTOS
    # =====================================================

    bloques_productos = []


    for indice, producto in enumerate(
        productos,
        start=1
    ):

        numero_parte = str(
            producto.get(
                "numero_parte"
            )
            or ""
        ).strip()

        marca = str(
            producto.get(
                "marca"
            )
            or ""
        ).strip()

        descripcion = str(
            producto.get(
                "descripcion"
            )
            or ""
        ).strip()

        cantidad = str(
            producto.get(
                "cantidad"
            )
            or "1"
        ).strip()


        bloque_producto = (
            f"Producto {indice}\n"
            f"Número de parte: "
            f"{numero_parte or 'No informado'}\n"
            f"Marca: "
            f"{marca or 'No informada'}\n"
            f"Descripción: "
            f"{descripcion or 'No informada'}\n"
            f"Cantidad: "
            f"{cantidad or '1'}"
        )


        bloques_productos.append(
            bloque_producto
        )


    descripcion_deal = (
        "\n\n".join(
            bloques_productos
        )
    )


    # =====================================================
    # ENTREGA
    # =====================================================

    direccion_entrega = str(
        campos.get(
            "direccion_entrega"
        )
        or ""
    ).strip()


    if direccion_entrega:

        descripcion_deal += (
            "\n\n"
            "Dirección de entrega: "
            f"{direccion_entrega}"
        )


      # =====================================================
    # CANTIDAD DE PRODUCTOS SOLICITADOS
    # =====================================================

    cantidad_productos_solicitados = int(
        campos.get(
            "cantidad_productos_solicitados"
        )
        or len(
            productos
        )
        or 1
    )


        # =====================================================
    # ORIGEN DE LA COTIZACIÓN
    # =====================================================

    origen = str(
        campos.get(
            "origen"
        )
        or ""
    ).strip().lower()


    if origen == "web":

        tipo_negocio = "Web"
        fuente_posible_cliente = "Chat Pag Web"


    elif origen == "whatsapp":

        tipo_negocio = "WhatsApp"
        fuente_posible_cliente = "Chat Whatsapp"


    else:

        tipo_negocio = "Web /WSP"
        fuente_posible_cliente = "Chat Whatsapp"


    # =====================================================
    # DATOS DEL NEGOCIO
    # =====================================================

    deal_data = {

        "Deal_Name":
            deal_name,

        "Description":
            descripcion_deal,

        "Stage":
            "Pendiente por cotizar",

        "Lead_Source":
            fuente_posible_cliente,

        "Amount":
            "1",

        "Type":
            "TI",

        "Fecha_hora_1":
            fecha_hora_1_str,

        "Closing_Date":
            closing_date_str,

        # ---------------------------------------------
        # CANTIDAD DE PRODUCTOS
        # ---------------------------------------------

        "Cantidad_de_productos":
            cantidad_productos_solicitados,
    }

    # =====================================================
    # OWNER DEL NEGOCIO
    # =====================================================

    if owner.get(
        "id"
    ):

        deal_data[
            "Owner"
        ] = {
            "id":
                owner[
                    "id"
                ]
        }

        deal_data[
            "Asignado_a"
        ] = {
            "id":
                owner[
                    "id"
                ]
        }


    # =====================================================
    # ACCOUNT
    # =====================================================

    if account_id:

        deal_data[
            "Account_Name"
        ] = {
            "id":
                str(
                    account_id
                )
        }

        print(
            "[crear_deal_en_zoho] "
            "Account_Name asignado al Deal: "
            f"{mask_value(str(account_id), 2, 2)}"
        )

    else:

        print(
            "[crear_deal_en_zoho] "
            "ADVERTENCIA: no se recibió account_id. "
            "El Deal se creará sin Account_Name."
        )


    # =====================================================
    # CONTACT
    # =====================================================

    if contact_id:

        deal_data[
            "Contact_Name"
        ] = {
            "id":
                str(
                    contact_id
                )
        }

    else:

        deal_data[
            "Contact_Name"
        ] = {
            "id":
                CONTACT_NAME_ID,

            "name":
                CONTACT_NAME_DEFAULT,
        }


    # =====================================================
    # PAYLOAD
    # =====================================================

    payload = {
        "data": [
            deal_data
        ]
    }


 # =========================================================
# CREAR NEGOCIO
# =========================================================

    try:

        print(
            "[crear_deal_en_zoho] "
            "Payload Deal:",
            payload,
        )

        resp = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=10,
        )

        print(
            "=== Respuesta Zoho CRM (Deals) ==="
        )

        print(
            resp.status_code
        )

        try:

            print(
                resp.text
            )

        except Exception:

            pass


        # =================================================
        # RESPUESTA CORRECTA
        # =================================================

        if resp.status_code in (
            200,
            201,
        ):

            try:

                body = resp.json()

                registros = (
                    body.get(
                        "data"
                    )
                    or []
                )

                if registros:

                    details = (
                        registros[0].get(
                            "details"
                        )
                        or {}
                    )

                    deal_id = (
                        details.get(
                            "id"
                        )
                    )

                    print(
                        "[crear_deal_en_zoho] "
                        f"Deal creado con ID = "
                        f"{mask_value(deal_id, 2, 2)}"
                    )


                    # =====================================
                    # SI EL NEGOCIO SE CREÓ CORRECTAMENTE
                    # =====================================

                    if deal_id:

                        # ===============================
                        # SUBIR ARCHIVOS A ZOHO CRM
                        # ===============================

                        try:

                            resultado_archivos = (
                                subir_archivos_negocio(
                                    str(
                                        deal_id
                                    ),
                                    productos,
                                )
                            )

                            print(
                                "[crear_deal_en_zoho] "
                                "Resultado archivos CRM:",
                                resultado_archivos,
                            )

                        except Exception as error:

                            print(
                                "[crear_deal_en_zoho] "
                                "ERROR subiendo archivos a CRM:",
                                error,
                            )


                        # ===============================
                        # SUBIR ARCHIVOS A ZOHO CREATOR
                        # ===============================

                        try:

                            resultado_archivos_creator = (
                                subir_archivos_creator(
                                    str(
                                        deal_id
                                    ),
                                    productos,
                                )
                            )

                            print(
                                "[crear_deal_en_zoho] "
                                "Resultado archivos Creator:",
                                resultado_archivos_creator,
                            )

                        except Exception as error:

                            print(
                                "[crear_deal_en_zoho] "
                                "ERROR subiendo archivos a Creator:",
                                error,
                            )


                        # ===============================
                        # DEVOLVER NEGOCIO CREADO
                        # ===============================

                        return (
                            resp,
                            deal_id
                        )


            except Exception as error:

                print(
                    "[crear_deal_en_zoho] "
                    "Error leyendo respuesta:",
                    error,
                )


        # =================================================
        # ZOHO RESPONDIÓ, PERO NO SE OBTUVO DEAL ID
        # =================================================

        return (
            resp,
            None
        )


    except Exception as error:

        print(
            "[crear_deal_en_zoho] "
            "ERROR llamando a Zoho CRM:",
            error,
        )

        return (
            None,
            None
        )