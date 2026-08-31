import os
import time
import unicodedata
import random
import requests
import re
from datetime import datetime, date, timedelta
from flask import Flask, request, jsonify

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

app = Flask(__name__)
# Cargar variables de entorno desde archivos "credentials" y ".env" si la librería dotenv está disponible, para mantener las credenciales y configuraciones sensibles fuera del código fuente y facilitar la gestión de estas variables en diferentes entornos (desarrollo, producción, etc.).
if load_dotenv:
    # Se determina el directorio base del archivo actual para cargar los archivos de variables de entorno desde la ubicación correcta, asegurando que las credenciales se carguen correctamente sin importar el directorio
    base_dir = os.path.dirname(os.path.abspath(__file__))
    load_dotenv(os.path.join(base_dir, "credentials"))
    load_dotenv(os.path.join(base_dir, ".env"))

# ===================== SESIONES EN MEMORIA =====================

# Diccionario en memoria para almacenar las sesiones de los visitantes, utilizando el visitor_id como clave pra mantener el estado de la conversación y la información relevante durante la interacción con el chatbot.
sessions = {}

# Función para enmascarar valores sensibles, mostrando solo los primeros y últimos caracteres según lo especificado, y reemplazando el resto con asteriscos. Esto es útil para proteger la privacidad de los datos del cliente en los logs o en cualquier salida que pueda ser visible, manteniendo solo una referencia útil para identificación.
def mask_value(value: str, show_start: int = 2, show_end: int = 2) -> str:
    if value is None:
        return ""
    raw = str(value).strip()
    if not raw:
        return ""
    if len(raw) <= (show_start + show_end):
        return "*" * len(raw)
    return f"{raw[:show_start]}{'*' * (len(raw) - (show_start + show_end))}{raw[-show_end:]}"
# Función específica para enmascarar correos electrónicos, mostrando solo el primer carácter del usuario y el dominio completo, para proteger la privacidad del cliente mientras se mantiene una referencia útil para identificación.
def mask_email(email: str) -> str:
    if not email:
        return ""
    email = str(email).strip()
    if "@" not in email:
        return mask_value(email)
    user, domain = email.split("@", 1)
    return f"{mask_value(user, 1, 1)}@{domain}"
# Función específica para enmascarar números de teléfono, limpiando el formato y aplicando el enmascaramiento adecuado, mostrando solo el último dígito y los primeros 4 caracteres, para proteger la privacidad del cliente mientras se mantiene una referencia útil para identificación.
def mask_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", str(phone or ""))
    if not digits:
        return ""
    return mask_value(digits, 0, 4)
# Función específica para enmascarar RUT, limpiando el formato y aplicando el enmascaramiento adecuado, mostrando solo los primeros 2 caracteres y el dígito verificador final, para proteger la privacidad del cliente mientras se mantiene una referencia útil para identificación.
def mask_rut(rut: str) -> str:
    cleaned = str(rut or "").strip()
    if not cleaned:
        return ""
    return mask_value(cleaned, 2, 1)
# Función para limpiar y enmascarar el payload recibido desde SalesIQ, asegurando que los datos sensibles del visitante estén protegidos antes de ser registrados en los logs o procesados por el sistema, manteniendo solo la información necesaria para identificar al visitante de forma segura.
def scrub_payload(payload: dict) -> dict:
    safe = dict(payload or {})
    visitor = dict(safe.get("visitor") or {})
    if visitor:
        if visitor.get("phone"):
            visitor["phone"] = mask_phone(visitor.get("phone"))
        if visitor.get("email"):
            visitor["email"] = mask_email(visitor.get("email"))
        if visitor.get("id"):
            visitor["id"] = mask_value(visitor.get("id"), 2, 2)
        if visitor.get("visitor_id"):
            visitor["visitor_id"] = mask_value(visitor.get("visitor_id"), 2, 2)
        if visitor.get("active_conversation_id"):
            visitor["active_conversation_id"] = mask_value(visitor.get("active_conversation_id"), 2, 2)
        safe["visitor"] = visitor
    return safe
# Función auxiliar para formatear la información del owner de forma segura para los logs, mostrando el nombre y un ID parcialmente enmascarado, o indicando que no hay owner si el diccionario está vacío o no tiene la información esperada. Esto ayuda a mantener la privacidad de los datos sensibles en los logs mientras se sigue teniendo una referencia útil para identificar al owner asignado.
def safe_owner_for_log(owner: dict) -> str:
    if not owner:
        return "(sin owner)"
    return f"{owner.get('nombre', 'N/A')} ({mask_value(owner.get('id', ''), 2, 2)})"
# Función para normalizar la información del owner, asegurando que tenga una estructura consistente y que los campos estén presentes aunque sea con valores vacíos. Si no se proporciona un owner, se asigna uno aleatorio de la lista de posibles. Esto es importante para mantener la integridad de los datos y facilitar el seguimiento de las conversaciones asignadas a cada owner.
def normalizar_owner(owner: dict = None) -> dict:
    if owner is None:
        owner = random.choice(OWNERS_POSIBLES)

    owner = {
        "nombre": str(owner.get("nombre") or "").strip(),
        "id": str(owner.get("id") or "").strip(),
        "email": str(owner.get("email") or "").strip(),
    }

    print(
        f"[normalizar_owner] Owner final: {safe_owner_for_log(owner)} / "
        f"email={mask_email(owner.get('email'))}"
    )
    return owner
# Función para obtener un identificador único del visitante a partir de la información disponible en el payload recibido desde SalesIQ, utilizando una jerarquía de campos para asegurar que se obtiene el identificador más relevante y consistente posible, incluso si algunos campos no están presentes. Esto permite mantener un seguimiento adecuado de las interacciones con cada visitante a lo largo del tiempo.
def get_visitor_id(payload: dict) -> str:
    visitor = payload.get("visitor") or {}
    return str(
        visitor.get("active_conversation_id")
        or visitor.get("phone")
        or visitor.get("id")
        or visitor.get("visitor_id")
        or visitor.get("email")
        or "anon"
    )
# Función para construir la respuesta al cliente, formateando los textos de respuesta y opcionalmente incluyendo un input_card para facilitar la interacción. Se asegura que los textos se manejen de forma consistente, permitiendo tanto un string simple como una lista de strings, y se estructura la respuesta según lo requerido por SalesIQ para que el chatbot pueda procesarla correctamente.
def build_reply(texts, input_card=None, action="reply") -> dict:
    if isinstance(texts, str):
        replies = [texts]
    else:
        replies = list(texts)

    response = {"action": action, "replies": replies}

    if input_card is not None:
        response["input"] = input_card

    return response
# Función para construir la respuesta inicial del menú principal, dando la bienvenida al cliente y presentando las opciones disponibles para atender su solicitud, utilizando un input de tipo select para facilitar la interacción y selección de opciones por parte del cliente.
def reply_menu_principal() -> dict:
    return build_reply(
        [
            "¡Bienvenido! Gracias por contactar con Selec.",
            "Por favor, seleccione una de las siguientes opciones para atender su solicitud.",
        ],
        input_card={"type": "select", "options": ["Solicitud Cotización", "Servicio PostVenta"]},
    )
# Función para normalizar texto eliminando acentos, caracteres especiales y convirtiendo a minúsculas, para facilitar comparaciones y validaciones posteriores. Esto es especialmente útil para asegurar que los datos ingresados por los usuarios tengan un formato consistente antes de ser procesados o almacenados.
def normalizar_texto(txt: str) -> str:
    if not txt:
        return ""
    txt = txt.lower()
    txt = "".join(
        c for c in unicodedata.normalize("NFD", txt)
        if unicodedata.category(c) != "Mn"
    )
    return txt.strip()
# Función para elegir el owner asignado a la conversación, verificando si ya existe un owner asignado en la sesión del visitante y si es válido, o asignando uno nuevo de forma aleatoria entre los posibles definidos. El owner se normaliza para asegurar que tenga la estructura correcta y se almacena en la sesión para futuras interacciones.
def elegir_owner_session(session: dict) -> dict:
    data = session.setdefault("data", {})
    owner = data.get("owner_asignado")
    if owner:
        owner = normalizar_owner(owner)
        data["owner_asignado"] = owner
        return owner

    owner = normalizar_owner(random.choice(OWNERS_POSIBLES))
    data["owner_asignado"] = owner
    return owner
# Función para construir el link directo al chat en SalesIQ, utilizando la plantilla definida en variables de entorno y reemplazando el placeholder con el ID de conversación activo del visitante. Si no se encuentra el ID de conversación o la plantilla no está configurada, se devuelve una cadena vacía.
def construir_link_chat(payload: dict) -> str:
    visitor = payload.get("visitor") or {}
    conversation_id = str(visitor.get("active_conversation_id") or "").strip()

    if not conversation_id:
        return ""

    template = os.environ.get("SALESIQ_CHAT_URL_TEMPLATE", "").strip()
    if template:
        return template.replace("{conversation_id}", conversation_id)

    return ""


# ===================== INTEGRACIÓN ZOHO CRM =====================
# Definición de las URLs base para las APIs de Zoho CRM y Zoho Accounts, que se utilizan para realizar las operaciones de autenticación y gestión de datos en el CRM. Estas URLs se mantienen como constantes para facilitar su uso
CRM_BASE = "https://www.zohoapis.com/crm/v2.1"

# URL base para la API de Zoho Accounts, utilizada para obtener el access token mediante el refresh token, que es necesario para autenticar las solicitudes a la API de Zoho CRM. Se mantiene como constante para facilitar su uso y evitar errores en la construcción
ACCOUNTS_BASE = "https://accounts.zoho.com"

OWNERS_POSIBLES = [
    {
        "nombre": os.environ.get("OWNER_1_NAME", "Joaquin Gonzalez"),
        "id": os.environ.get("OWNER_1_ID", ""),
        "email": os.environ.get("OWNER_1_EMAIL", ""),
    },
]

access_token_cache = {"token": None, "expires_at": 0.0}

# Contacto obligatorio anterior en CRM
CONTACT_NAME_ID = "4358923000074108191"
CONTACT_NAME_DEFAULT = "Cliente Web Cliente Web"

# Función para obtener el access token de Zoho CRM utilizando el refresh token, con caching en memoria para evitar llamadas innecesarias a la API de autenticación. Se verifica si el token en cache es válido antes de hacer la solicitud, y se asume un tiempo de expiración de 1 hora.
def get_access_token() -> str:
    now = time.time()
    if access_token_cache["token"] and (access_token_cache["expires_at"] - 60 > now):
        return access_token_cache["token"]

    client_id = os.environ.get("ZOHO_CLIENT_ID")
    client_secret = os.environ.get("ZOHO_CLIENT_SECRET")
    refresh_token = os.environ.get("ZOHO_REFRESH_TOKEN")

    if not client_id or not client_secret or not refresh_token:
        print("ERROR: faltan ZOHO_CLIENT_ID / ZOHO_CLIENT_SECRET / ZOHO_REFRESH_TOKEN.")
        return None

    url = f"{ACCOUNTS_BASE}/oauth/v2/token"
    params = {
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
    }

    try:
        resp = requests.post(url, params=params, timeout=10)
        print("=== Respuesta refresh token Zoho ===")
        print(resp.status_code)
        try:
            print(resp.text)
        except Exception:
            pass

        if resp.status_code != 200:
            return None

        data = resp.json()
        token = data.get("access_token")
        expires_in = int(data.get("expires_in", 3600))

        if not token:
            print("ERROR: respuesta sin access_token.")
            return None

        access_token_cache["token"] = token
        access_token_cache["expires_at"] = time.time() + expires_in
        return token

    except Exception as e:
        print("ERROR llamando a Zoho Accounts:", e)
        return None

# Función para obtener o crear un Account en Zoho CRM, buscando primero por RUT (Billing_Code) y luego por nombre de empresa, y si no existe se crea un nuevo Account con la información disponible, asignando el owner definido. Se maneja con cuidado la normalización de datos y se implementa un fallback en caso de error en la creación con payload completo.
def obtener_o_crear_account(campos: dict, owner: dict = None):
    access_token = get_access_token()
    if not access_token:
        print("[obtener_o_crear_account] No se pudo obtener access token; se omite Accounts.")
        return None

    owner = normalizar_owner(owner)

    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "Content-Type": "application/json",
    }

    rut_raw = (campos.get("rut") or "").strip()
    empresa = (campos.get("empresa") or "").strip()
    telefono = (campos.get("telefono") or "").strip()

    rut_norm = rut_raw.replace(".", "").replace(" ", "").upper()

    print(
        f"[obtener_o_crear_account] rut_raw={mask_rut(rut_raw)!r} "
        f"rut_norm={mask_rut(rut_norm)!r} empresa={mask_value(empresa, 2, 0)!r} "
        f"telefono={mask_phone(telefono)!r}"
    )

    if not rut_norm and not empresa:
        print("[obtener_o_crear_account] Sin RUT ni empresa, no se crea/busca Account.")
        return None

    print(f"[obtener_o_crear_account] Owner elegido: {safe_owner_for_log(owner)}")
    # Primero se intenta buscar el Account por RUT (Billing code) si el RUT está presente, ya que es un identificador más confiable y único que el nombre de la empresa, para evitar duplicados en caso de que haya variaciones.
    if rut_norm:
        try:
            criteria = f"(Billing_Code:equals:{rut_norm})"
            search_url = f"{CRM_BASE}/Accounts/search"
            params = {"criteria": criteria}
            resp = requests.get(search_url, headers=headers, params=params, timeout=10)
            print("[obtener_o_crear_account] === Búsqueda Account por Billing_Code ===")
            print(resp.status_code)
            try:
                print(resp.text)
            except Exception:
                pass
            # Si se encuentra un Account con el mismo RUT, se devuelve su ID sin intentar crear uno nuevo, para mantener la integridad de los datos y evitar duplicados.
            if resp.status_code == 200:
                body = resp.json()
                registros = body.get("data") or []
                if registros and registros[0].get("id"):
                    account_id = registros[0]["id"]
                    print(f"[obtener_o_crear_account] Account encontrado ID={mask_value(account_id, 2, 2)}")
                    return account_id
        except Exception as e:
            print("[obtener_o_crear_account] ERROR buscando Account:", e)

    account_name = empresa or rut_norm or "Sin nombre"
    # Si no se encuentra por RUT, se intenta buscar por nombre de empresa, aunque esto es menos confiable debido a posibles variaciones en el nombre, pero se hace como segundo criterio para intentar relacionar con un Account.
    account_data_full = {
        "Account_Name": account_name,
        "Billing_Code": rut_norm or None,
        "Phone": telefono or None,
        "Cliente_Selec": "NO",
        "Industry": "Por definir",
        "Region1": "Por definir",
        "Ciudad_I": "Por definir",
        "Website": "https://pordefinir.com",
    }

    if owner.get("id"):
        account_data_full["Owner"] = {"id": owner["id"]}
    # Función auxiliar para realizar la solicitud de creación del Account, utilizada tanto para el intento inicial con payload completo como para el fallback
    def post_account(account_data: dict):
        create_url = f"{CRM_BASE}/Accounts"
        payload = {"data": [account_data]}
        print("[obtener_o_crear_account] Payload Account:", payload)
        return requests.post(create_url, headers=headers, json=payload, timeout=10)

    try:
        resp = post_account(account_data_full)
        print("[obtener_o_crear_account] === Creación Account ===")
        print(resp.status_code)
        try:
            print(resp.text)
        except Exception:
            pass
        # Si la creación es exitosa, se devuelve el ID del nuevo Account creado. Si hay un error de validación (400), se intenta un segundo intento con un payload mínimo para aumentar las posibilidades de éxito
        if resp.status_code in (200, 201):
            body = resp.json()
            registros = body.get("data") or []
            if registros:
                details = registros[0].get("details") or registros[0]
                account_id = details.get("id")
                print(f"[obtener_o_crear_account] Account creado ID={mask_value(account_id, 2, 2)}")
                return account_id
        # Si se recibe un error 400, se asume que puede ser por validación de campos, por lo que se hace un segundo intento con un payload minimo que solo incluye campos escenciales, para aumentar las posibilidades de éxito en la creación del Account, aunque con menos información.
        if resp.status_code == 400:
            print("[obtener_o_crear_account] Creación rechazada (400). Reintentando con payload mínimo...")

            account_data_min = {
                "Account_Name": account_name,
                "Phone": telefono or None,
            }

            if rut_norm:
                account_data_min["Billing_Code"] = rut_norm

            if owner.get("id"):
                account_data_min["Owner"] = {"id": owner["id"]}

            # Se hace un segundo intento de creación del Account con un payload mínimo en caso de error 400, para aumentar las posibilidades de éxito, aunque con menos información.
            resp2 = post_account(account_data_min)
            print("[obtener_o_crear_account] === Creación Account fallback ===")
            print(resp2.status_code)
            try:
                print(resp2.text)
            except Exception:
                pass
            
            if resp2.status_code in (200, 201):
                body2 = resp2.json()
                registros2 = body2.get("data") or []
                if registros2:
                    details2 = registros2[0].get("details") or registros2[0]
                    account_id2 = details2.get("id")
                    print(f"[obtener_o_crear_account] Account creado (fallback) ID={mask_value(account_id2, 2, 2)}")
                    return account_id2

    except Exception as e:
        print("[obtener_o_crear_account] ERROR creando Account:", e)

    return None
# Función para obtener o crear un Contact en Zoho CRM, buscando primero por correo electrónico y luego creando el Contact si no existe, relacionándolo con el Account correspondiente y asignando el owner definido.
def obtener_o_crear_contact(campos: dict, account_id: str = None, owner: dict = None):
    access_token = get_access_token()
    if not access_token:
        print("[obtener_o_crear_contact] No se pudo obtener access token; se omite Contacts.")
        return None

    owner = normalizar_owner(owner)

    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "Content-Type": "application/json",
    }

    contacto_full = str(campos.get("contacto") or "").strip()
    correo = str(campos.get("correo") or "").strip()
    telefono = str(campos.get("telefono") or "").strip()

    print(
        f"[obtener_o_crear_contact] contacto={mask_value(contacto_full, 2, 0)!r} "
        f"correo={mask_email(correo)!r} telefono={mask_phone(telefono)!r} "
        f"account_id={mask_value(account_id, 2, 2)!r}"
    )

    if not correo:
        print("[obtener_o_crear_contact] Sin correo, no se puede crear/buscar Contact.")
        return None
    # Se intenta buscar el Contact por correo electrónico, ya que es un identificador más confiables y único que el nombre del contacto, para evitar duplicado en caso de que haya variaciones en el nombre.
    nombre_partes = [p for p in contacto_full.split() if p.strip()]
    if len(nombre_partes) >= 2:
        first_name = " ".join(nombre_partes[:-1]).strip()
        last_name = nombre_partes[-1].strip()
    elif len(nombre_partes) == 1:
        first_name = nombre_partes[0].strip()
        last_name = "Cliente"
    else:
        first_name = "Cliente Web"
        last_name = "Cliente Web"
    # Primero se intenta buscar el Contact por correo electrónico, ya que es un identificador más confiable y único que el nombre del contacto, para evitar duplicados en caso de que haya variaciones en el nombre.
    try:
        search_url = f"{CRM_BASE}/Contacts/search"
        params = {"email": correo}
        resp = requests.get(search_url, headers=headers, params=params, timeout=10)

        print("[obtener_o_crear_contact] === Búsqueda Contact por email ===")
        print(resp.status_code)
        try:
            print(resp.text)
        except Exception:
            pass
        # Si se encuentra un Contact con el mismo correo, se devuelve su ID y se actualiza su información si es necesario, para mantener la integridad de los datos y evitar duplicados, asegurando que el Contact tenga la información.
        if resp.status_code == 200:
            body = resp.json()
            registros = body.get("data") or []
            if registros and registros[0].get("id"):
                contact_id = registros[0]["id"]
                print(f"[obtener_o_crear_contact] Contact encontrado ID={mask_value(contact_id, 2, 2)}")

                try:
                    actual = registros[0]
                    acc_actual = actual.get("Account_Name")
                    acc_actual_id = ""
                    if isinstance(acc_actual, dict):
                        acc_actual_id = str(acc_actual.get("id") or "").strip()

                    needs_update = False
                    update_data = {"id": contact_id}

                    if account_id and acc_actual_id != account_id:
                        update_data["Account_Name"] = {"id": account_id}
                        needs_update = True

                    if not str(actual.get("Cargo") or "").strip():
                        update_data["Cargo"] = "Cliente Web"
                        needs_update = True

                    if not str(actual.get("Lead_Source") or "").strip():
                        update_data["Lead_Source"] = "Chat Pag Web"
                        needs_update = True

                    if telefono and not str(actual.get("Phone") or "").strip():
                        update_data["Phone"] = telefono
                        needs_update = True

                    if needs_update:
                        payload_upd = {"data": [update_data]}
                        upd_url = f"{CRM_BASE}/Contacts"
                        upd_resp = requests.put(upd_url, headers=headers, json=payload_upd, timeout=10)

                        print("[obtener_o_crear_contact] === Update Contact existente ===")
                        print(upd_resp.status_code)
                        try:
                            print(upd_resp.text)
                        except Exception:
                            pass

                except Exception as e_upd:
                    print("[obtener_o_crear_contact] ERROR actualizando Contact existente:", e_upd)

                return contact_id

    except Exception as e:
        print("[obtener_o_crear_contact] ERROR buscando Contact por email:", e)
    # Si no se encuentra por correo, se crea un nuevo Contact con la información disponible, asignándolo al Account correspondiente y al owner definido, para asegurar que el cliente quede registrado en el CRM.
    contact_data = {
        "First_Name": first_name,
        "Last_Name": last_name,
        "Cargo": "Cliente Web",
        "Lead_Source": "Chat Pag Web",
        "Email": correo,
    }

    if telefono:
        contact_data["Phone"] = telefono

    if account_id:
        contact_data["Account_Name"] = {"id": account_id}

    if owner.get("id"):
        contact_data["Owner"] = {"id": owner["id"]}

    payload = {"data": [contact_data]}
    create_url = f"{CRM_BASE}/Contacts"

    try:
        print("[obtener_o_crear_contact] === Creación Contact ===")
        print("[obtener_o_crear_contact] Payload Contact:", payload)

        resp = requests.post(create_url, headers=headers, json=payload, timeout=10)
        print(resp.status_code)
        try:
            print(resp.text)
        except Exception:
            pass

        if resp.status_code in (200, 201):
            body = resp.json()
            registros = body.get("data") or []
            if registros:
                details = registros[0].get("details") or registros[0]
                contact_id = details.get("id")
                if contact_id:
                    print(f"[obtener_o_crear_contact] Contact creado ID={mask_value(contact_id, 2, 2)}")
                    return contact_id

        try:
            print("[obtener_o_crear_contact] Error JSON:", resp.json())
        except Exception:
            pass

    except Exception as e:
        print("[obtener_o_crear_contact] ERROR creando Contact:", e)

    return None
# Función para calcular la fecha de cierre del Deal según reglas definidas: si el día de la fecha base es antes del 15, se asigna el último día del mismo mes; si es el dia 15 o despues se asigna el ultimo dia del mes.
def calcular_closing_date(fecha_base: date) -> str:
    # Se calcula la fecha de cierre del Deal según las reglas definidas: si el día de la fecha base es antes del 15, se asigna el último día del mismo mes.
    dia = fecha_base.day
    mes = fecha_base.month
    anio = fecha_base.year
    # Se determina el mes y año objetivo para calcular el último día, aplicando la regla de que si el día es 15 o después, se asigna el último día del mes siguiente.
    target_mes = mes
    target_anio = anio
    # Si el día es 15 o después, se asigna el último día del mes siguiente, ajustando el año si el mes es diciembre.
    if dia >= 15:
        if mes == 12:
            target_mes = 1
            target_anio = anio + 1
        else:
            target_mes = mes + 1
    # Se calcula el último día del mes objetivo, teniendo en cuenta los meses con 30 días y el caso especial de febrero con años bisiestos, para asegurar que la fecha de cierre sea válida.
    if target_mes in (4, 6, 9, 11):
        ultimo_dia = 30
    elif target_mes == 2:
        es_bisiesto = (target_anio % 400 == 0) or (target_anio % 4 == 0 and target_anio % 100 != 0)
        ultimo_dia = 29 if es_bisiesto else 28
    else:
        ultimo_dia = 31

    fecha_cierre = date(target_anio, target_mes, ultimo_dia)
    return fecha_cierre.strftime("%Y-%m-%d")



# Variables de entorno para el usuario remitente del correo en Zoho CRM, que se utiliza para enviar las notificaciones al owner asignado y gerencia con los detalles del nuevo Deal creado.
SENDER_USER_ID = os.environ.get("SENDER_USER_ID", "")
SENDER_USER_EMAIL = os.environ.get("SENDER_USER_EMAIL", "")
SENDER_USER_NAME = os.environ.get("SENDER_USER_NAME", "Bot Selec")
# Correos de gerencia y Elian para incluir en CC en las notificaciones de nuevos Deals y primer contacto, asegurando que estén informados de las interacciones.
CC_GERENCIA_EMAIL = "gerencia@selec.cl"
CC_ELIAN_EMAIL = "elian@selec.cl"
CRM_ORG_UI = "org706345205"
MAIL_TO_FIXED = "Joaquin@selec.cl"
MAIL_TO_FIXED = "Ivanna@selec.cl"
MAIL_TO_NAME = "Joaquin Gonzalez"
MAIL_TO_NAME = "Ivanna Vera"

# Función auxiliar para construir la estructura de destinatarios de correo, aplicando formato adecuado para Zoho CRM y asegurando que el email esté presente y el nombre se incluya solo si es válido. Es importante que el formato de destinatarios cumpla con los requisitos de Zoho CRM para que el correo se envíe correctamente.
def build_mail_recipient(email: str, name: str = "") -> dict:
    recipient = {"email": str(email).strip()}
    if str(name or "").strip():
        recipient["user_name"] = str(name).strip()
    return recipient
# Función para enviar correo de notificación al owner asignado y gerencia con los detalles del nuevo Deal creado, incluyendo información relevante del cliente y un link directo al Deal en Zoho CRM para facilitar la gestión comercial. Este correo se envía cada vez que se crea un nuevo Deal desde el chatbot de WhatsApp, para asegurar que el equipo comercial esté informado y pueda dar seguimiento oportuno.
def enviar_correo_owner(owner: dict, deal_id: str, deal_name: str, campos: dict):
    access_token = get_access_token()
    if not access_token:
        print("[enviar_correo_owner] No se pudo obtener access token; no se envía correo.")
        return None

    url = f"{CRM_BASE}/Deals/{deal_id}/actions/send_mail"
    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "Content-Type": "application/json",
    }

    to_email = MAIL_TO_FIXED
    to_name = MAIL_TO_NAME

    subject = f"Nuevo Deal asignado desde WhatsApp: {deal_name}"
    deal_link = f"https://crm.zoho.com/crm/{CRM_ORG_UI}/tab/Potentials/{deal_id}"

    # Construcción del contenido del correo con los detalles del nuevo Deal creado, incluyendo la información del cliente recopilada desde el chatbot de WhatsApp, y un link directo al Deal en Zoho CRM
    content = f"""
    <p>Hola {to_name},</p>
    <p>Se ha creado un nuevo Deal asignado desde el chatbot de WhatsApp.</p>
    <p>Numero de Chat(SalesIQ): {campos.get('num_chat') or '(sin número de chat)'}</p>
    <p><b>Deal:</b> {deal_name}</p>
    <p><b>Link del Deal en Zoho CRM:</b> <a href="{deal_link}">Abrir Deal</a></p>

    <p><b>Empresa:</b> {campos.get('empresa') or '(sin empresa)'}</p>
    <p><b>RUT:</b> {campos.get('rut') or '(sin RUT)'}</p>
    <p><b>Contacto:</b> {campos.get('contacto') or '(sin contacto)'}</p>
    <p><b>Correo:</b> {campos.get('correo') or '(sin correo)'}</p>
    <p><b>Teléfono:</b> {campos.get('telefono') or '(sin teléfono)'}</p>
    <p><b>Número de parte / descripción:</b> {campos.get('num_parte') or '(sin descripción)'}</p>
    <p><b>Marca:</b> {campos.get('marca') or '(sin marca)'}</p>
    <p><b>Cantidad:</b> {campos.get('cantidad') or '(sin cantidad)'}</p>
    <p><b>Dirección de entrega:</b> {campos.get('direccion_entrega') or '(sin dirección)'}</p>

    <p>Saludos,<br/>Bot WhatsApp Selec</p>
    """

    cc_list = [
        build_mail_recipient("elian@selec.cl", "Elian Barra"),
        build_mail_recipient("gerencia@selec.cl", "Gerencia Selec"),
    ]
    # Construcción del payload para enviar el correo a través de la API de Zoho CRM, asegurando que el formato cumpla con los requisitos y que se incluyan correctamente
    payload = {
        "data": [
            {
                "from": {
                    "id": SENDER_USER_ID,
                    "user_name": SENDER_USER_NAME,
                    "email": SENDER_USER_EMAIL
                },
                "to": [
                    build_mail_recipient(to_email, to_name)
                ],
                "cc": cc_list,
                "subject": subject,
                "content": content,
                "mail_format": "html",
            }
        ]
    }

    try:
        print("[enviar_correo_owner] Payload:", payload)
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        print("=== Respuesta Zoho CRM send_mail owner ===")
        print(resp.status_code)
        try:
            print(resp.text)
        except Exception:
            pass
        return resp
    except Exception as e:
        print("ERROR enviando correo de notificación:", e)
        return None
# Función para enviar correo de notificación al owner asignado y gerencia con los detalles del primer contacto recibido desde SalesIQ, incluyendo información del visitante y un link directo a la conversación de chat si está disponible. Este correo se envía solo la primera vez que el visitante interactúa, para evitar spam en caso de múltiples mensajes.
def enviar_correo_primer_contacto(owner: dict, payload: dict):
    access_token = get_access_token()
    if not access_token:
        print("[enviar_correo_primer_contacto] No se pudo obtener access token.")
        return None

    to_email = MAIL_TO_FIXED
    to_name = MAIL_TO_NAME

    visitor = payload.get("visitor") or {}
    visitor_name = visitor.get("name") or visitor.get("email") or visitor.get("phone") or "Cliente sin identificar"
    visitor_email = visitor.get("email") or ""
    visitor_phone = visitor.get("phone") or ""
    conversation_id = str(visitor.get("active_conversation_id") or "").strip()
    current_page = visitor.get("current_page_url") or ""
    question = visitor.get("question") or ""
    chat_link = construir_link_chat(payload)

    subject = f"Nuevo contacto recibido por SalesIQ: {visitor_name}"

    if chat_link:
        bloque_chat = f'<p><b>Link directo del chat:</b> <a href="{chat_link}">Abrir conversación</a></p>'
    else:
        bloque_chat = f"<p><b>ID conversación:</b> {conversation_id or '(no disponible)'}</p>"

    content = f"""
    <p>Estimado/a {to_name},</p>

    <p>Se informa que un cliente se ha contactado con Selec mediante SalesIQ.</p>

    <p><b>Nombre:</b> {visitor_name}</p>
    <p><b>Correo:</b> {visitor_email or '(no informado)'}</p>
    <p><b>Teléfono:</b> {visitor_phone or '(no informado)'}</p>
    <p><b>Consulta inicial:</b> {question or '(sin mensaje inicial)'}</p>
    <p><b>Página actual:</b> {current_page or '(no disponible)'}</p>
    {bloque_chat}

    <p>Por favor, revisar la conversación para continuar con la atención del cliente.</p>

    <p>Saludos cordiales,<br/>Sistema de atención Selec</p>
    """

    url = f"{CRM_BASE}/Deals/actions/send_mail"
    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "Content-Type": "application/json",
    }

    cc_list = [
        build_mail_recipient("elian@selec.cl", "Elian Barra"),
        build_mail_recipient("gerencia@selec.cl", "Gerencia Selec"),
    ]

    payload_mail = {
        "data": [
            {
                "from": {
                    "id": SENDER_USER_ID,
                    "user_name": SENDER_USER_NAME,
                    "email": SENDER_USER_EMAIL
                },
                "to": [
                    build_mail_recipient(to_email, to_name)
                ],
                "cc": cc_list,
                "subject": subject,
                "content": content,
                "mail_format": "html",
            }
        ]
    }

    try:
        print("[enviar_correo_primer_contacto] Payload:", payload_mail)
        resp = requests.post(url, headers=headers, json=payload_mail, timeout=10)
        print("=== Respuesta correo primer contacto ===")
        print(resp.status_code)
        try:
            print(resp.text)
        except Exception:
            pass
        return resp
    except Exception as e:
        print("[enviar_correo_primer_contacto] ERROR:", e)
        return None
# Funcion principal para crear el Deal en Zoho CRM, con toda la información recopilada, y asignarlo al owner correspondiente, además de enviar un correo de notifiación al owner y gerencia con los detalles del nuevo Deal creado. Se maneja la fecha de cierre según reglas definidas y se asegura que el contacto y account estén relacionados correctamente.
def crear_deal_en_zoho(campos: dict, account_id: str = None, contact_id: str = None, owner: dict = None):
    # Se obtiene el access token de Zoho CRM para realizar las operaciones de creación del Deal. Si no se puede obtener el token, se omite la creación del Deal para evitar errores en las llamadas a la API
    access_token = get_access_token()
    if not access_token:
        print("[crear_deal_en_zoho] No se pudo obtener access token de Zoho; se omite creación de Deal.")
        return None, None
    # Se normaliza el owner para asegurar que tenga la estructura correcta y se pueda utilizar en la asignación del Deal, además de garantizar que los logs muestren información segura y útil sobre el owner asignado.
    owner = normalizar_owner(owner)

    ahora = datetime.now().astimezone()
    manana = ahora + timedelta(days=1)
    fecha_hora_1_str = manana.isoformat(timespec="seconds")
    fecha_limite_oferta = manana.date()
    closing_date_str = calcular_closing_date(fecha_limite_oferta)
    # Se construye el payload para la creación del Deal en Zoho CRM, incluyendo toda la información relevante del cliente y la cotización, y asignándolo al owner correspondiente. Se maneja con cuidado la estructura
    url = f"{CRM_BASE}/Deals"
    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "Content-Type": "application/json",
    }
    # Se muestra en los logs el owner elegido para asignar el Deal, aplicando la función de enmascaramiento para proteger la información sensible, pero permitiendo identificar al owner asignado.
    print(f"[crear_deal_en_zoho] Owner elegido: {safe_owner_for_log(owner)}")

    deal_name = f"Cotización - {campos.get('empresa') or 'Sin empresa'}"
    # Se construye la descripción del Deal con toda la información relevante del cliente y la cotización, formateada de manera clara para que el equipo comercial pueda entender rápidamente los detalles al revisar el Deal en Zoho CRM.
    deal_data = {
        "Deal_Name": deal_name,
        "Description": (
            f"Empresa: {campos.get('empresa')}\n"
            f"RUT: {campos.get('rut')}\n"
            f"Contacto: {campos.get('contacto')}\n"
            f"Correo: {campos.get('correo')}\n"
            f"Teléfono: {campos.get('telefono')}\n"
            f"Producto / descripción: {campos.get('num_parte')}\n"
            f"Marca: {campos.get('marca')}\n"
            f"Cantidad: {campos.get('cantidad')}\n"
            f"Dirección de entrega: {campos.get('direccion_entrega')}"
        ),
        "Stage": "Pendiente por cotizar",
        "Lead_Source": "Chat Whatsapp",
        "Amount": "1",
        "Type": "Web /WSP",
        "Fecha_hora_1": fecha_hora_1_str,
        "Closing_Date": closing_date_str,
    }
    # Si el owner tiene un ID válido, se asigna el Deal a ese owner en Zoho CRM, para asegurar que quede registrado quién es el responsable de dar seguimiento al cliente y la cotización.
    if owner.get("id"):
        deal_data["Owner"] = {"id": owner["id"]}
        deal_data["Asignado_a"] = {"id": owner["id"]}
    # Si se tiene el ID del Account, se relaciona el Deal con ese Account en Zoho CRM, para mantener la integridad de los datos y asegurar que el Deal quede vinculado al cliente correcto.
    if account_id:
        deal_data["Account_Name"] = {"id": account_id}
    # Si se tiene el ID del Contact, se relaciona el Deal con ese Contact en Zoho CRM, para mantener la integridad de los datos y asegurar que el Deal quede vinculado al contacto correcto.
    if contact_id:
        deal_data["Contact_Name"] = {"id": contact_id}
    else:
        deal_data["Contact_Name"] = {
            "id": CONTACT_NAME_ID,
            "name": CONTACT_NAME_DEFAULT
        }

    payload = {"data": [deal_data]}

    try:
        print("[crear_deal_en_zoho] Payload Deal:", payload)
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        print("=== Respuesta Zoho CRM (Deals) ===")
        print(resp.status_code)
        try:
            print(resp.text)
        except Exception:
            pass
            # Si la creación del Deal es exitosa, se extrae el ID del nuevo Deal creado y se envía un correo de notificación al owner asignado y gerencia con los detalles del nuevo Deal, para asegurar que el equipo comercial esté informado.
        if resp.status_code in (200, 201):
            try:
                body = resp.json()
                registros = body.get("data") or []
                if registros:
                    details = registros[0].get("details") or {}
                    deal_id = details.get("id")
                    print(f"[crear_deal_en_zoho] Deal creado con ID = {mask_value(deal_id, 2, 2)}")
                    if deal_id:
                        enviar_correo_owner(owner, deal_id, deal_name, campos)
                    return resp, deal_id
            except Exception as e:
                print("[crear_deal_en_zoho] Error leyendo respuesta:", e)

        return resp, None
    except Exception as e:
        print("[crear_deal_en_zoho] ERROR llamando a Zoho CRM:", e)
        return None, None

# ===================== FIN INTEGRACIÓN ZOHO CRM =====================

# Endpoint raíz para verificar que el servidor de webhook está corriendo correctamente, respondiendo con un mensaje simple. Esto es útil para monitoreo y pruebas básicas de conectividad.
@app.route("/", methods=["GET"])
def index():
    return "Webhook server running"
@app.route("/salesiq-webhook", methods=["GET", "POST"])
# El endpoint principal para manejar los webhooks de Zoho SalesIQ, con lógica de flujo según el estado de la sesión y el tipo de mensaje recibido
def salesiq_webhook():
    if request.method == "GET":
        return jsonify({"status": "ok", "message": "Use POST desde Zoho SalesIQ"})

    payload = request.get_json(force=True, silent=True) or {}
    handler = payload.get("handler")
    visitor_id = get_visitor_id(payload)

    session = sessions.setdefault(visitor_id, {"state": "inicio", "data": {}})

    visitor = payload.get("visitor") or {}
    visitid = visitor.get("visitid")
    conversation_id = str(visitor.get("active_conversation_id") or "").strip()
    if visitid:
        session["data"]["num_chat"] = f"#{visitid}"
    elif conversation_id:
        session["data"]["num_chat"] = conversation_id

    print("=== SalesIQ payload (safe) ===")
    print(scrub_payload(payload))

    if handler == "trigger":
        session["state"] = "menu_principal"
        owner = elegir_owner_session(session)
        if not session.get("primer_correo_enviado"):
            enviar_correo_primer_contacto(owner, payload)
            session["primer_correo_enviado"] = True
        return jsonify(reply_menu_principal())

    if handler == "message":
        message_text = extraer_mensaje(payload)
        print("=== mensaje extraído ===", repr(mask_value(message_text, 0, 0)[:120]))
        state = session.get("state", "inicio")

        if state == "inicio":
            session["state"] = "menu_principal"
            return jsonify(reply_menu_principal())

        if state in ("menu_principal", "inicio"):
            return jsonify(manejar_menu_principal(session, message_text))

        if state == "cotizacion_empresa_bloque":
            return jsonify(manejar_flujo_cotizacion_empresa_bloque(session, message_text))

        if state == "cotizacion_producto_bloque":
            session["state"] = "cotizacion_bloque"
            return jsonify(manejar_flujo_cotizacion_bloque(session, message_text))

        if state == "cotizacion_bloque":
            return jsonify(manejar_flujo_cotizacion_bloque(session, message_text))

        if state == "postventa_bloque":
            return jsonify(manejar_flujo_postventa_bloque(session, message_text))

        session["state"] = "menu_principal"
        return jsonify(reply_menu_principal())

    return jsonify(build_reply("He recibido su mensaje."))
# Función para extraer el mensaje de texto del payload, considerando diferentes estructuras posibles
def extraer_mensaje(payload: dict) -> str:
    # Se intenta extraer el mensaje de texto del payload, considerando diferentes estructuras posibles, para asegurar que se capture el mensaje correctamente.
    msg_obj = payload.get("message")
    # Si no se encuentra en la raíz, se intenta buscar dentro del objeto "request", ya que dependiendo del tipo de evento.
    if not msg_obj:
        req_obj = payload.get("request") or {}
        msg_obj = req_obj.get("message")
    # Si el mensaje es un objeto con campos "text" o "value", se extrae el texto, ya que dependiendo del tipo de mensaje, el contenido puede estar en diferentes campos.
    if isinstance(msg_obj, dict):
        txt = msg_obj.get("text") or msg_obj.get("value") or ""
        return str(txt).strip()
    # Si el mensaje es un string simple, se devuelve directamente, aunque normalmente el mensaje debería estar dentro de un objeto, pero se maneja esta posibilidad para mayor robustez.
    if isinstance(msg_obj, str):
        return msg_obj.strip()

    return ""
# Manejo de flujo principal - elección entre cotización y postventa
def manejar_menu_principal(session: dict, message_text: str) -> dict:
    texto_norm = normalizar_texto(message_text)
    # Se analiza el mensaje del cliente para determinar si está solicitando una cotización o un servicio de postventa, utilizando palabras clave y normalizando el texto para mejorar la detección.
    if ("cotiz" in texto_norm or "solicitud cotizacion" in texto_norm or texto_norm == "cotizacion"):
        session["state"] = "cotizacion_empresa_bloque"
        session["data"] = {}
        # Se responde al cliente solicitando los datos de la empresa y del contacto en un formato específico, para facilitar la recopilación de información necesaria para crear el Deal en Zoho CRM.
        return build_reply(
            [
                "Perfecto, trabajaremos en su solicitud de cotización.",
                (
                    "Por favor, complete los siguientes datos de la empresa y del contacto "
                    "en un solo mensaje (puede copiar y pegar este formato):\n\n"
                    "Nombre de la empresa:\n"
                    "RUT:\n"
                    "Nombre de contacto:\n"
                    "Correo:\n"
                    "Teléfono:"
                ),
            ]
        )
    # Se analiza el mensaje del cliente para detectar si está solicitando un servicio de postventa, utilizando palabras clave relacionadas con postventa y normalizando el texto para mejorar la detección
    if ("postventa" in texto_norm or "post venta" in texto_norm or "servicio postventa" in texto_norm):
        session["state"] = "postventa_bloque"
        formulario = (
            "Perfecto, trabajaremos en su solicitud de postventa.\n"
            "Por favor, responda copiando y completando este formulario en un solo mensaje:\n\n"
            "Nombre:\n"
            "RUT:\n"
            "Número de factura:\n"
            "Descripción del problema:"
        )
        return build_reply(formulario)

    # Si no se detecta una intención clara, se responde al cliente indicando que no se puede gestionar automáticamente y se deriva a un ejecutivo, para asegurar que el cliente reciba atención aunque no se pueda procesar su solicitud.
    session["state"] = "derivado_operador"
    return {
        "action": "forward",
        "replies": [
            "En este momento no puedo gestionar esta solicitud automáticamente.",
            "Le derivaré con un ejecutivo para que pueda asistirle.",
        ],
    }
# Manejo de flujo de Cotizacion - bloque de datos de empresa y contacato
def manejar_flujo_cotizacion_empresa_bloque(session: dict, message_text: str) -> dict:
    # Se maneja el bloque de información de empresa y contacto para la cotización, extrayendo los datos del mensaje del cliente, validando los campos obligatorios y actualizando la sesión con la información recopilado.
    data = session.setdefault("data", {})
    texto = (message_text or "").strip()
    lineas = [l.strip() for l in texto.splitlines() if l.strip()]
    # Se inicializan los campos esperados con valores vacíos, para luego ir completándolos a medida que se procesan las líneas del mensaje, asegurando que todos los campos estén presentes en el diccionario final.
    campos = {
        "empresa": data.get("empresa", ""),
        "rut": data.get("rut", ""),
        "contacto": data.get("contacto", ""),
        "correo": data.get("correo", ""),
        "telefono": data.get("telefono", ""),
    }
    # Función auxiliar para normalizar el texto de las etiquetas, eliminando acentos, caracteres especiales y convirtiendo a minúsculas, para facilitar la detección de los campos en el mensaje del cliente.
    def extraer_email(s: str):
        m = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", s or "")
        return m.group(0).strip() if m else None
    # Función auxiliar para limpiar un string y dejar solo los dígitos, eliminando cualquier otro carácter, para facilitar la validación de campos como RUT o teléfono que deben contener principalmente números.
    def limpiar_digitos(s: str) -> str:
        return re.sub(r"\D", "", s or "")

    def es_rut_plausible(s: str) -> bool:
        s_norm = (s or "").strip()
        if re.search(r"\d{1,3}\.?\d{3}\.?\d{3}-[\dkK]", s_norm):
            return True
        d = limpiar_digitos(s_norm)
        return 7 <= len(d) <= 12
    # Función auxiliar para validar si un string es un teléfono plausible, considerando que debe contener principalmente dígitos y tener una longitud razonable para números de teléfono, para ayudar a identificar el campo de teléfono incluso si no está etiquetado.
    def es_telefono_plausible(s: str) -> bool:
        d = limpiar_digitos(s or "")
        return 5 <= len(d) <= 12

    sin_label = []
    for linea in lineas:
        if ":" in linea:
            etiqueta, valor = linea.split(":", 1)
            etiqueta_norm = normalizar_texto(etiqueta)
            valor_clean = valor.strip()
            if not valor_clean:
                continue

            if "empresa" in etiqueta_norm or "razon social" in etiqueta_norm or "razon_social" in etiqueta_norm:
                campos["empresa"] = valor_clean
            elif etiqueta_norm in ("rut", "r.u.t", "r u t"):
                campos["rut"] = valor_clean
            elif "contacto" in etiqueta_norm:
                campos["contacto"] = valor_clean
            elif "correo" in etiqueta_norm or "email" in etiqueta_norm:
                campos["correo"] = valor_clean
            elif "telefono" in etiqueta_norm or "teléfono" in etiqueta_norm:
                campos["telefono"] = valor_clean
            else:
                sin_label.append(linea)
        else:
            sin_label.append(linea)

    for linea in list(sin_label):
        if not campos["correo"]:
            em = extraer_email(linea)
            if em:
                campos["correo"] = em
                sin_label.remove(linea)

    for linea in list(sin_label):
        if not campos["rut"] and es_rut_plausible(linea):
            campos["rut"] = linea.strip()
            sin_label.remove(linea)

    for linea in list(sin_label):
        if not campos["telefono"] and es_telefono_plausible(linea):
            campos["telefono"] = limpiar_digitos(linea)
            sin_label.remove(linea)
    # Función auxiliar para determinar si una línea es mayormente numérica, calculando la proporción de dígitos respecto al total de caracteres (excluyendo espacios), para ayudar a identificar campos como empresa o contacto.
    def es_mayormente_numerico(s: str) -> bool:
        d = limpiar_digitos(s)
        return bool(d) and (len(d) / max(len(s.replace(" ", "")), 1)) > 0.6

    if not campos["empresa"]:
        for linea in list(sin_label):
            if extraer_email(linea):
                continue
            if es_mayormente_numerico(linea):
                continue
            campos["empresa"] = linea
            sin_label.remove(linea)
            break

    if not campos["contacto"]:
        for linea in list(sin_label):
            if extraer_email(linea):
                continue
            if es_mayormente_numerico(linea):
                continue
            campos["contacto"] = linea
            sin_label.remove(linea)
            break



    data.update(campos)




    faltantes = []

    if not str(data.get("empresa", "")).strip():
        faltantes.append("Nombre de la empresa")

    if not str(data.get("rut", "")).strip():
        faltantes.append("RUT")

    if not str(data.get("contacto", "")).strip():
        faltantes.append("Nombre de contacto")

    correo_val = str(data.get("correo", "")).strip()
    if not correo_val:
        faltantes.append("Correo")
    elif not re.search(r"[\w\.-]+@[\w\.-]+\.\w+", correo_val):
        faltantes.append("Correo (formato inválido)")

    tel_val = str(data.get("telefono", "")).strip()
    if not tel_val:
        faltantes.append("Teléfono")

    if faltantes:
        session["state"] = "cotizacion_empresa_bloque"
        return build_reply(
            [
                "No fue posible registrar la información, ya que faltan datos obligatorios o el correo presenta un formato inválido.",
                "Campos a corregir:\n- " + "\n- ".join(faltantes),
                (
                    "Por favor, envíe únicamente los campos faltantes o corregidos. "
                    "Ejemplo:\nCorreo: cliente@empresa.com\nTeléfono: 56912345678"
                ),
            ]
        )
    # Si la información de empresa y contacto es válida, se actualiza el estado de la sesión para avanzar al bloque de información del producto, y se solicita al cliente que envíe los detalles del producto en un formato específico.
    session["state"] = "cotizacion_producto_bloque"
    return build_reply(
        [
            "Gracias. A continuación, por favor envíe la información del producto.",
            (
                "En un SOLO mensaje, indique:\n"
                "Número de parte, marca, descripción detallada y cantidad.\n\n"
                "Ejemplo:\n"
                "Número de parte: ABC123\n"
                "Marca: Siemens\n"
                "Descripción: ...\n"
                "Cantidad: 5"
            ),
        ]
    )

 # Manejar flujo de cotizacion bloque. Este bloque se puede usar tanto para la parte de empresa como para la parte de producto, ya que el formato es similar y permite extraer campos de forma flexible.
# Se priorizan las líneas con etiqueta (ej. "Número de parte: ABC123"), pero si no se encuentra cierta información, se intenta inferir a partir de líneas sin etiqueta.
def manejar_flujo_cotizacion_bloque(session: dict, message_text: str) -> dict:
    data = session["data"]
    texto = message_text or ""
    lineas = [l for l in texto.splitlines() if l.strip()]
# Campos a extraer: empresa,rut,contacto,correo,telefono,num_parte,cantidad,marca,direccion_entrega
    campos = {
        "empresa": data.get("empresa", ""),
        "rut": data.get("rut", ""),
        "contacto": data.get("contacto", ""),
        "correo": data.get("correo", ""),
        "telefono": data.get("telefono", ""),
        "num_parte": data.get("num_parte", ""),
        "cantidad": data.get("cantidad", ""),
        "marca": data.get("marca", ""),
        "direccion_entrega": data.get("direccion_entrega", ""),
    }

    lineas_sin_label = []
    # Se procesan las líneas del mensaje para extraer la información, buscando etiquetas conocidas para cada campo, pero también almacenando líneas sin etiqueta para intentar inferir información si no se encentra.
    for linea in lineas:
        linea = linea.strip()
        if not linea:
            continue
        # Si la línea contiene ":", se intenta extraer una etiqueta y un valor, y se asigna el valor al campo correspondiente según
        if ":" in linea:
            etiqueta, valor = linea.split(":", 1)
            etiqueta_norm = normalizar_texto(etiqueta)
            valor_clean = valor.strip()
            if not valor_clean:
                continue

            if "empresa" in etiqueta_norm or "razon social" in etiqueta_norm or "razon_social" in etiqueta_norm:
                campos["empresa"] = valor_clean
            elif etiqueta_norm in ("rut", "r.u.t", "r u t"):
                campos["rut"] = valor_clean
            elif "contacto" in etiqueta_norm:
                campos["contacto"] = valor_clean
            elif "correo" in etiqueta_norm or "email" in etiqueta_norm:
                campos["correo"] = valor_clean
            elif "telefono" in etiqueta_norm or "teléfono" in etiqueta_norm:
                campos["telefono"] = valor_clean
            elif (
                "numero de parte" in etiqueta_norm
                or "numero parte" in etiqueta_norm
                or "descripcion" in etiqueta_norm
                or "descripción" in etiqueta_norm
            ):
                campos["num_parte"] = valor_clean
            elif "marca" in etiqueta_norm:
                campos["marca"] = valor_clean
            elif (
                "direccion de entrega" in etiqueta_norm
                or "dirección de entrega" in etiqueta_norm
                or "direccion" in etiqueta_norm
                or "dirección" in etiqueta_norm
                or "domicilio" in etiqueta_norm
            ):
                campos["direccion_entrega"] = valor_clean
            elif "cantidad" in etiqueta_norm:
                campos["cantidad"] = valor_clean
            else:
                lineas_sin_label.append(linea)
        else:
            lineas_sin_label.append(linea)

    if not campos["num_parte"] and lineas_sin_label:
        campos["num_parte"] = " ".join(lineas_sin_label)

    if not str(campos["cantidad"]).strip():
        numeros = re.findall(r"\b\d+(?:[.,]\d+)?\b", texto)
        if numeros:
            campos["cantidad"] = numeros[-1].replace(",", ".")

    data.update(campos)
    # Listado para definir campos obligatorios
    obligatorios = ["empresa", "rut", "contacto", "correo", "telefono", "num_parte", "cantidad"]
    nombres_legibles = {
        "empresa": "Nombre de la empresa",
        "rut": "RUT",
        "contacto": "Nombre de contacto",
        "correo": "Correo",
        "telefono": "Teléfono",
        "num_parte": "Número de parte o descripción detallada",
        "cantidad": "Cantidad",
    }
    # Se verifica que los campos obligatorios estén presentes y no estén vacíos, y se valida que el campo de cantidad sea un número mayor a 0, para asegurar que se tiene la información mínima necesaria para crear el Deal.
    faltantes = [nombres_legibles[c] for c in obligatorios if not str(data.get(c, "")).strip()]
    try:
        cantidad_val = float(str(data.get("cantidad", "")).replace(",", "."))
        if cantidad_val <= 0:
            if "Cantidad (debe ser mayor a 0)" not in faltantes:
                faltantes.append("Cantidad (debe ser mayor a 0)")
    except Exception:
        if "Cantidad (valor numérico)" not in faltantes:
            faltantes.append("Cantidad (valor numérico)")
    # Si faltan campos obligatorios o el formato de cantidad es incorrecto, se responde al cliente indicando cuáles son los campos faltantes o inválidos, y se mantiene el estado en el bloque de cotización para que pueda corregir.
    if faltantes:
        session["state"] = "cotizacion_bloque"
        return build_reply(
            [
                "No fue posible registrar su solicitud, ya que existen campos obligatorios faltantes o inválidos.",
                "Campos a corregir:\n- " + "\n- ".join(faltantes),
                "Por favor, envíe únicamente los datos faltantes o corregidos.",
            ]
        )
# Si llegamos aqui, todos los campos obligatorios están presentes y el formato de cantidad es correcto. Procedemos a crear el Deal en Zoho CRM.
    resumen = (
        "Resumen de su solicitud de cotización:\n"
        f"Nombre de la empresa: {data.get('empresa','')}\n"
        f"RUT: {mask_rut(data.get('rut',''))}\n"
        f"Nombre de contacto: {data.get('contacto','')}\n"
        f"Correo: {mask_email(data.get('correo',''))}\n"
        f"Teléfono: {mask_phone(data.get('telefono',''))}\n"
        f"Número de parte / descripción: {data.get('num_parte','')}\n"
        f"Cantidad: {data.get('cantidad','')}\n"
        f"Marca: {data.get('marca','')}\n"
        f"Dirección de entrega: {data.get('direccion_entrega','')}"
    )
    # Se normaliza el owner asignado para asegurar que tenga la estructura correcta y se pueda utilizar en la creación del Deal, además de garantizar que los logs muestren información segura y útil sobre el owner asignado.
    owner = normalizar_owner(data.get("owner_asignado"))
    account_id = obtener_o_crear_account(data, owner=owner)
    contact_id = obtener_o_crear_contact(data, account_id=account_id, owner=owner)
    deal_resp, deal_id = crear_deal_en_zoho(data, account_id=account_id, contact_id=contact_id, owner=owner)

    session["state"] = "menu_principal"
    session["data"] = {}
    session["primer_correo_enviado"] = False
    # Si el Deal se creó correctamente, se responde al cliente con un resumen de su solicitud y se informa que un ejecutivo se pondrá en contacto con él. Si hubo un inconveniente al crear el Deal, se responde al cliente indicando que hubo un problema.
    if deal_id:
        return build_reply(
            [
                "Gracias. Hemos registrado su solicitud con el siguiente detalle:",
                resumen,
                "Un ejecutivo de Selec se pondrá en contacto con usted.",
            ]
        )
    # Si no se pudo crear el Deal, se responde al cliente indicando que hubo un inconveniente, pero que su solicitud ha sido recibida y será revisada manualmente por un ejecutivo.
    return build_reply(
        [
            "Gracias. Hemos recibido su solicitud, pero ocurrió un inconveniente al registrarla automáticamente en nuestro sistema.",
            resumen,
            "Un ejecutivo revisará su caso manualmente y se pondrá en contacto con usted.",
        ]
    )
# Manejar flujo de postventa bloque. En este caso, no se crea un Deal, pero se podría integrar con sistema de postventa o CRM si se desea.
def manejar_flujo_postventa_bloque(session: dict, message_text: str) -> dict:
    # Se maneja el bloque de información para postventa, extrayendo los datos del mensaje del cliente, validando los campos obligatorios y actualizando la sesión con la información recopilada. Luego se responde al cliente con un resumen de su solicitud.
    data = session["data"]
    texto = message_text or ""
    lineas = texto.splitlines()
    # Se inicializan los campos esperados con valores vacíos, para luego ir completándolos a medida que se procesan las líneas del mensaje, asegurando que todos los campos estén presentes en el diccionario final.
    campos = {
        "nombre": data.get("nombre", ""),
        "rut": data.get("rut", ""),
        "numero_factura": data.get("numero_factura", ""),
        "detalle": data.get("detalle", ""),
    }
    # Se procesa cada línea del mensaje para extraer los campos de nombre, RUT, número de factura y detalle del problema, utilizando etiquetas y también considerando líneas sin etiqueta para completar el detalle, asegurando que se capture toda la información relevante.
    for linea in lineas:
        if ":" not in linea:
            linea_plana = linea.strip()
            if linea_plana:
                campos["detalle"] = (campos["detalle"] + " " + linea_plana).strip() if campos["detalle"] else linea_plana
            continue

        etiqueta, valor = linea.split(":", 1)
        etiqueta_norm = normalizar_texto(etiqueta)
        valor_clean = valor.strip()
        if not valor_clean:
            continue
        # Se asignan los campos según las etiquetas encontradas, utilizando la normalización para mejorar la detección, y se va completando el detalle con cualquier línea que no tenga etiqueta para asegurar que se capturen todos los detalles del problema.
        if "nombre" in etiqueta_norm:
            campos["nombre"] = valor_clean
        elif etiqueta_norm in ("rut", "r.u.t", "r u t"):
            campos["rut"] = valor_clean
        elif "factura" in etiqueta_norm or "n° factura" in etiqueta_norm:
            campos["numero_factura"] = valor_clean
        elif "descripcion" in etiqueta_norm or "descripción" in etiqueta_norm or "problema" in etiqueta_norm:
            campos["detalle"] = valor_clean

    data.update(campos)
    # Listado para definir campos
    obligatorios = ["nombre", "rut", "numero_factura"]
    nombres_legibles = {"nombre": "Nombre", "rut": "RUT", "numero_factura": "Número de factura"}
    # Se verifica que los campos obligatorios estén presentes y no sean solo espacios en blanco. Si faltan campos, se responde al cliente indicando cuáles son los campos faltantes o inválidos, y se mantiene el estado en el bloque de postventa para que pueda corregirlo.
    faltantes = [nombres_legibles[c] for c in obligatorios if not str(data.get(c, "")).strip()]
    # En este caso, no se validan formatos específicos para RUT o número de factura, pero se podría agrega validaciones adicionales si se desea, por ejemplo para verificar que el número de factura tenga un formato establecido.
    if faltantes:
        session["state"] = "postventa_bloque"
        return build_reply(
            [
                "No fue posible registrar correctamente su solicitud de postventa, ya que faltan datos obligatorios.",
                "Campos a corregir:\n- " + "\n- ".join(faltantes),
                "Por favor, envíe únicamente los datos faltantes o corregidos (por ejemplo: Número de factura: 12345).",
            ]
        )
# Si llegamos aquí, los campos obligatorios están presentes. Procedemos a registrar la solicitud de postventa (en este caso, simplemente construiremos un resumen para el operador, pero aqui se podria integrar con zoho CRM o sistema interno de postventa si se desea).
    resumen = (
        "Resumen de su solicitud de postventa:\n"
        f"Nombre: {data['nombre']}\n"
        f"RUT: {mask_rut(data['rut'])}\n"
        f"Número de factura: {data['numero_factura']}\n"
        f"Descripción del problema: {data['detalle'] or '(sin detalle adicional)'}"
    )

    session["state"] = "menu_principal"

    return build_reply(
        [
            "Gracias. Hemos registrado su solicitud de postventa con el siguiente detalle:",
            resumen,
            "En unos momentos un operador de Selec revisará su caso.",
        ]
    )
# ===================== FIN MANEJO DE FLUJOS =====================
# ===================== INICIO SERVIDOR WEB =====================
# Finalmente, se levanta el servidor Flask para escuchar los webhooks de zoho SalsIQ. Se configura para escuchar en todas las interfaces y el puerto se puede definir mediante la variable de entorno PORT, con un valor por defecto de 3000. También se puede activar el modo debug de Flask mediante la variable de entorno FLASK_DEBUG.
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    debug_mode = os.environ.get("FLASK_DEBUG", "false").strip().lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug_mode)