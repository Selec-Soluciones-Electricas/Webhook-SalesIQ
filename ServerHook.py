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

if load_dotenv:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    # Prioridad: archivo local "credentials"; fallback: .env estándar.
    load_dotenv(os.path.join(base_dir, "credentials"))
    load_dotenv(os.path.join(base_dir, ".env"))

# ===================== SESIONES EN MEMORIA =====================

sessions = {}


def mask_value(value: str, show_start: int = 2, show_end: int = 2) -> str:
    """Oculta datos sensibles mostrando solo una parte mínima."""
    if value is None:
        return ""
    raw = str(value).strip()
    if not raw:
        return ""
    if len(raw) <= (show_start + show_end):
        return "*" * len(raw)
    return f"{raw[:show_start]}{'*' * (len(raw) - (show_start + show_end))}{raw[-show_end:]}"


def mask_email(email: str) -> str:
    if not email:
        return ""
    email = str(email).strip()
    if "@" not in email:
        return mask_value(email)
    user, domain = email.split("@", 1)
    return f"{mask_value(user, 1, 1)}@{domain}"


def mask_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", str(phone or ""))
    if not digits:
        return ""
    return mask_value(digits, 0, 4)


def mask_rut(rut: str) -> str:
    cleaned = str(rut or "").strip()
    if not cleaned:
        return ""
    return mask_value(cleaned, 2, 1)


def scrub_payload(payload: dict) -> dict:
    """Devuelve una copia del payload con campos sensibles enmascarados para logs."""
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


def safe_owner_for_log(owner: dict) -> str:
    if not owner:
        return "(sin owner)"
    return f"{owner.get('nombre', 'N/A')} ({mask_value(owner.get('id', ''), 2, 2)})"


def get_visitor_id(payload: dict) -> str:
    """Obtiene un identificador estable del visitante (evita colisiones entre conversaciones)."""
    visitor = payload.get("visitor") or {}
    return str(
        visitor.get("active_conversation_id")
        or visitor.get("phone")
        or visitor.get("id")
        or visitor.get("visitor_id")
        or visitor.get("email")
        or "anon"
    )


def build_reply(texts, input_card=None, action="reply") -> dict:
    """Crea la estructura mínima de respuesta que Zobot entiende."""
    if isinstance(texts, str):
        replies = [texts]
    else:
        replies = list(texts)

    response = {"action": action, "replies": replies}

    if input_card is not None:
        response["input"] = input_card

    return response


def reply_menu_principal() -> dict:
    """Respuesta de menú principal con botones (select)."""
    return build_reply(
        [
            "¡Bienvenido! Gracias por contactar con Selec.",
            "Por favor, seleccione una de las siguientes opciones para atender su solicitud.",
        ],
        input_card={"type": "select", "options": ["Solicitud Cotización", "Servicio PostVenta"]},
    )


def normalizar_texto(txt: str) -> str:
    """Normaliza texto (minúsculas y sin acentos) para comparar opciones."""
    if not txt:
        return ""
    txt = txt.lower()
    txt = "".join(
        c for c in unicodedata.normalize("NFD", txt)
        if unicodedata.category(c) != "Mn"
    )
    return txt.strip()

def elegir_owner_session(session: dict) -> dict:
    data = session.setdefault("data", {})
    owner = data.get("owner_asignado")
    if owner:
        return owner

    owner = random.choice(OWNERS_POSIBLES)
    data["owner_asignado"] = owner
    return owner


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

CRM_BASE = "https://www.zohoapis.com/crm/v2.1"
ACCOUNTS_BASE = "https://accounts.zoho.com"

OWNERS_POSIBLES = [

    {
        "nombre": os.environ.get("OWNER_1_NAME", "Alexander Leiva"),
        "id": os.environ.get("OWNER_1_ID", ""),
        "email": os.environ.get("OWNER_1_EMAIL", ""),
    },
]


access_token_cache = {"token": None, "expires_at": 0.0}


def get_access_token() -> str:
    """
    Devuelve un access token válido usando refresh_token si es necesario.
    Usa las variables de entorno:
      - ZOHO_CLIENT_ID
      - ZOHO_CLIENT_SECRET
      - ZOHO_REFRESH_TOKEN
    """
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


def obtener_o_crear_account(campos: dict, owner: dict = None):  
    """
    Busca un Account por Billing_Code (RUT).
    Si existe, devuelve su ID.
    Si no existe, crea uno nuevo (con fallback si Zoho rechaza campos).
    """
    access_token = get_access_token()
    if not access_token:
        print("[obtener_o_crear_account] No se pudo obtener access token; se omite Accounts.")
        return None

    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "Content-Type": "application/json",
    }

    rut_raw = (campos.get("rut") or "").strip()
    empresa = (campos.get("empresa") or "").strip()
    telefono = (campos.get("telefono") or "").strip()

    # Normalizar RUT para búsquedas (sin puntos/espacios; mantiene guión y K si viene)
    rut_norm = rut_raw.replace(".", "").replace(" ", "").upper()

    print(
        f"[obtener_o_crear_account] rut_raw={mask_rut(rut_raw)!r} "
        f"rut_norm={mask_rut(rut_norm)!r} empresa={mask_value(empresa, 2, 0)!r} "
        f"telefono={mask_phone(telefono)!r}"
    )

    if not rut_norm and not empresa:
        print("[obtener_o_crear_account] Sin RUT ni empresa, no se crea/busca Account.")
        return None

    if owner is None:
        owner = random.choice(OWNERS_POSIBLES)

    print(f"[obtener_o_crear_account] Owner elegido: {safe_owner_for_log(owner)}")

    if rut_norm:
        try:
            criteria = f"(Billing_Code:equals:{rut_norm})"
            search_url = f"{CRM_BASE}/Accounts/search"
            params = {"criteria": criteria}
            resp = requests.get(search_url, headers=headers, params=params, timeout=10)
            print("[obtener_o_crear_account] === Búsqueda Account por Billing_Code ===")
            print(resp.status_code)

            if resp.status_code == 200:
                body = resp.json()
                registros = body.get("data") or []
                if registros and registros[0].get("id"):
                    account_id = registros[0]["id"]
                    print(f"[obtener_o_crear_account] Account encontrado ID={mask_value(account_id, 2, 2)}")
                    return account_id
            elif resp.status_code == 204:
                pass
            else:
                print("[obtener_o_crear_account] Búsqueda falló. Continuará a creación.")
        except Exception as e:
            print("[obtener_o_crear_account] ERROR buscando Account:", e)

    account_name = empresa or rut_norm or "Sin nombre"
    account_data_full = {
        "Account_Name": account_name,
        "Billing_Code": rut_norm or None,
        "Phone": telefono or None,
        "Cliente_Selec": "NO",
"Owner": {"id": owner["id"]},
        "Industry": "Por definir",
        "Region1": "Por definir",
        "Ciudad_I": "Por definir",
        "Website": "https://pordefinir.com",
    }

    def post_account(account_data: dict):
        create_url = f"{CRM_BASE}/Accounts"
        payload = {"data": [account_data]}
        resp = requests.post(create_url, headers=headers, json=payload, timeout=10)
        print("[obtener_o_crear_account] === Creación Account ===")
        print(resp.status_code)
        return resp

    try:
        resp = post_account(account_data_full)

        if resp.status_code in (200, 201):
            body = resp.json()
            registros = body.get("data") or []
            if registros:
                details = registros[0].get("details") or registros[0]
                account_id = details.get("id")
                print(f"[obtener_o_crear_account] Account creado ID={mask_value(account_id, 2, 2)}")
                return account_id

        # Fallback si Zoho rechaza campos (400 invalid_data)
        if resp.status_code == 400:
            print("[obtener_o_crear_account] Creación rechazada (400). Reintentando con payload mínimo...")

            account_data_min = {
                "Account_Name": account_name,
                "Phone": telefono or None,
                "Owner": {"id": owner["id"]},
            }
            if rut_norm:
                account_data_min["Billing_Code"] = rut_norm

            resp2 = post_account(account_data_min)
            if resp2.status_code in (200, 201):
                body2 = resp2.json()
                registros2 = body2.get("data") or []
                if registros2:
                    details2 = registros2[0].get("details") or registros2[0]
                    account_id2 = details2.get("id")
                    print(f"[obtener_o_crear_account] Account creado (fallback) ID={mask_value(account_id2, 2, 2)}")
                    return account_id2
            else:
                print("[obtener_o_crear_account] Fallback falló. Revise el detalle del error en Zoho (resp2).")

    except Exception as e:
        print("[obtener_o_crear_account] ERROR creando Account:", e)

    return None
def calcular_closing_date(fecha_base: date) -> str:
    """
    - Si día < 15   => último día del mismo mes
    - Si día >= 15  => último día del mes siguiente
    Devuelve string YYYY-MM-DD (Closing_Date).
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

    if target_mes in (4, 6, 9, 11):
        ultimo_dia = 30
    elif target_mes == 2:
        es_bisiesto = (target_anio % 400 == 0) or (target_anio % 4 == 0 and target_anio % 100 != 0)
        ultimo_dia = 29 if es_bisiesto else 28
    else:
        ultimo_dia = 31

    fecha_cierre = date(target_anio, target_mes, ultimo_dia)
    return fecha_cierre.strftime("%Y-%m-%d")


# ===================== Estructura y configuración de correo para CRM =====================

SENDER_USER_ID = os.environ.get("SENDER_USER_ID", "")
SENDER_USER_EMAIL = os.environ.get("SENDER_USER_EMAIL", "")
SENDER_USER_NAME = os.environ.get("SENDER_USER_NAME", "Bot Selec")

CC_GERENCIA_EMAIL = os.environ.get("CC_GERENCIA_EMAIL", "")
CC_Elian_EMAIL = os.environ.get("CC_ELIAN_EMAIL", "")

CRM_ORG_UI = "org706345205"


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

    to_email = owner.get("email")
    to_name = owner.get("nombre", "Ejecutivo")

    if not to_email:
        print("[enviar_correo_owner] Owner sin email definido, no se envía correo.")
        return None

    subject = f"Nuevo Deal asignado desde WhatsApp: {deal_name}"
    deal_link = f"https://crm.zoho.com/crm/{CRM_ORG_UI}/tab/Potentials/{deal_id}"

    content = f"""
    <p>Hola {to_name},</p>
    <p>Se ha creado un nuevo Deal asignado a usted desde el chatbot de WhatsApp.</p>

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
    <p><b>Dirección de entrega:</b> {campos.get('direccion_entrega') or '(sin dirección)'} </p>

    <p>Saludos,<br/>Bot WhatsApp Selec</p>
    """

    cc_list = []
    if CC_GERENCIA_EMAIL:
        cc_list.append({"email": CC_GERENCIA_EMAIL, "user_name": "Gerencia Selec"})
    if CC_Elian_EMAIL:
        cc_list.append({"email": CC_Elian_EMAIL, "user_name": "Elian Barra"})

    payload = {
        "data": [
            {
                "from": {"id": SENDER_USER_ID, "user_name": SENDER_USER_NAME, "email": SENDER_USER_EMAIL},
                "to": [{"email": to_email, "user_name": to_name}],
                "cc": cc_list,
                "subject": subject,
                "content": content,
                "mail_format": "html",
            }
        ]
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        print("=== Respuesta Zoho CRM send_mail ===")
        print(resp.status_code)
        return resp
    except Exception as e:
        print("ERROR enviando correo de notificación:", e)
        return None


def enviar_correo_primer_contacto(owner: dict, payload: dict):
    access_token = get_access_token()
    if not access_token:
        print("[enviar_correo_primer_contacto] No se pudo obtener access token.")
        return None

    to_email = owner.get("email")
    to_name = owner.get("nombre", "Ejecutivo")

    if not to_email:
        print("[enviar_correo_primer_contacto] Owner sin email.")
        return None

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

    cc_list = []
    if CC_GERENCIA_EMAIL:
        cc_list.append({"email": CC_GERENCIA_EMAIL, "user_name": "Gerencia Selec"})

    payload_mail = {
        "data": [
            {
                "from": {"id": SENDER_USER_ID, "user_name": SENDER_USER_NAME, "email": SENDER_USER_EMAIL},
                "to": [{"email": to_email, "user_name": to_name}],
                "cc": cc_list,
                "subject": subject,
                "content": content,
                "mail_format": "html",
            }
        ]
    }

    try:
        resp = requests.post(url, headers=headers, json=payload_mail, timeout=10)
        print("=== Respuesta correo primer contacto ===")
        print(resp.status_code)
        return resp
    except Exception as e:
        print("[enviar_correo_primer_contacto] ERROR:", e)
        return None


def crear_deal_en_zoho(campos: dict, account_id: str = None, owner: dict = None):
    access_token = get_access_token()
    if not access_token:
        print("No se pudo obtener access token de Zoho; se omite creación de Deal.")
        return None

    ahora = datetime.now().astimezone()
    manana = ahora + timedelta(days=1)
    fecha_hora_1_str = manana.isoformat(timespec="seconds")
    fecha_limite_oferta = manana.date()
    closing_date_str = calcular_closing_date(fecha_limite_oferta)

    url = f"{CRM_BASE}/Deals"
    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "Content-Type": "application/json",
    }

    if owner is None:
        owner = random.choice(OWNERS_POSIBLES)

    print(f"[crear_deal_en_zoho] Owner elegido: {safe_owner_for_log(owner)}")

    deal_name = f"Cotización - {campos.get('empresa') or 'Sin empresa'}"

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
        "Owner": {"id": owner["id"]},
        "Asignado_a": {"id": owner["id"]},
        "Type": "Industrias",
        "Fecha_hora_1": fecha_hora_1_str,
        "Closing_Date": closing_date_str,
    }

    if account_id:
        deal_data["Account_Name"] = {"id": account_id}

    payload = {"data": [deal_data]}

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        print("=== Respuesta Zoho CRM (Deals) ===")
        print(resp.status_code)

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
            except Exception as e:
                print("Error leyendo respuesta de creación de Deal:", e)

        return resp
    except Exception as e:
        print("ERROR llamando a Zoho CRM:", e)
        return None


# ===================== ENDPOINT WEBHOOK SALESIQ =====================

@app.route("/", methods=["GET"])
def index():
    return "Webhook server running"


@app.route("/salesiq-webhook", methods=["GET", "POST"])
def salesiq_webhook():
    if request.method == "GET":
        return jsonify({"status": "ok", "message": "Use POST desde Zoho SalesIQ"})

    payload = request.get_json(force=True, silent=True) or {}
    handler = payload.get("handler")
    visitor_id = get_visitor_id(payload)

    session = sessions.setdefault(visitor_id, {"state": "inicio", "data": {}})

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

        # Empresa/contacto en un solo bloque; producto en bloque separado
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


def extraer_mensaje(payload: dict) -> str:
    msg_obj = payload.get("message")
    if not msg_obj:
        req_obj = payload.get("request") or {}
        msg_obj = req_obj.get("message")

    if isinstance(msg_obj, dict):
        txt = msg_obj.get("text") or msg_obj.get("value") or ""
        return str(txt).strip()

    if isinstance(msg_obj, str):
        return msg_obj.strip()

    return ""


def manejar_menu_principal(session: dict, message_text: str) -> dict:
    texto_norm = normalizar_texto(message_text)

    if ("cotiz" in texto_norm or "solicitud cotizacion" in texto_norm or texto_norm == "cotizacion"):
        session["state"] = "cotizacion_empresa_bloque"
        session["data"] = {}
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

    session["state"] = "derivado_operador"
    return {
        "action": "forward",
        "replies": [
            "En este momento no puedo gestionar esta solicitud automáticamente.",
            "Le derivaré con un ejecutivo para que pueda asistirle.",
        ],
    }


# ===================== CAMBIO SOLICITADO AQUÍ =====================
def manejar_flujo_cotizacion_empresa_bloque(session: dict, message_text: str) -> dict:
    """
    Etapa 1 (un solo mensaje): empresa + rut + contacto + correo + teléfono.
    Acepta:
      - Formato con etiquetas (Empresa:..., RUT:..., etc.)
      - Texto libre por líneas (sin etiquetas), asignando por heurísticas y, si corresponde, por orden.
    Luego solicita producto en etapa 2 (mensaje separado).
    """
    data = session.setdefault("data", {})
    texto = (message_text or "").strip()
    lineas = [l.strip() for l in texto.splitlines() if l.strip()]

    campos = {
        "empresa": data.get("empresa", ""),
        "rut": data.get("rut", ""),
        "contacto": data.get("contacto", ""),
        "correo": data.get("correo", ""),
        "telefono": data.get("telefono", ""),
    }

    # Helpers tolerantes (sin exigir copiar formato)
    def extraer_email(s: str):
        m = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", s or "")
        return m.group(0).strip() if m else None

    def limpiar_digitos(s: str) -> str:
        return re.sub(r"\D", "", s or "")

    def es_rut_plausible(s: str) -> bool:
        # Acepta RUT con o sin puntos/guión y también solo dígitos (7 a 12) para tolerancia.
        s_norm = (s or "").strip()
        if re.search(r"\d{1,3}\.?\d{3}\.?\d{3}-[\dkK]", s_norm):
            return True
        d = limpiar_digitos(s_norm)
        return 7 <= len(d) <= 12

    def es_telefono_plausible(s: str) -> bool:
        # Acepta teléfono 5 a 12 dígitos (tolerante para evitar bloquear por errores).
        d = limpiar_digitos(s or "")
        return 5 <= len(d) <= 12

    # 1) Parseo por etiquetas (si vienen)
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

    # 2) Heurísticas: email / rut / teléfono en cualquier orden, aunque no haya etiquetas
    for linea in list(sin_label):
        if not campos["correo"]:
            em = extraer_email(linea)
            if em:
                campos["correo"] = em
                sin_label.remove(linea)

    for linea in list(sin_label):
        if not campos["rut"] and es_rut_plausible(linea):
            # Preferir el texto original (por si trae guion/k)
            campos["rut"] = linea.strip()
            sin_label.remove(linea)

    for linea in list(sin_label):
        if not campos["telefono"] and es_telefono_plausible(linea):
            campos["telefono"] = limpiar_digitos(linea)
            sin_label.remove(linea)

    # 3) Asignación por orden para lo restante (evita exigir “copiar/pegar formato”)
    #    Regla: empresa = primera línea no numérica; contacto = siguiente línea no numérica.
    def es_mayormente_numerico(s: str) -> bool:
        d = limpiar_digitos(s)
        return bool(d) and (len(d) / max(len(s.replace(" ", "")), 1)) > 0.6

    # Empresa
    if not campos["empresa"]:
        for linea in list(sin_label):
            if extraer_email(linea):
                continue
            if es_mayormente_numerico(linea):
                continue
            campos["empresa"] = linea
            sin_label.remove(linea)
            break

    # Contacto
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

    # 4) Validación (tolerante): no bloquea por RUT sin guión o teléfono “corto”, pero sí exige correo válido.
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

    # Etapa 2: solicitar producto en bloque separado
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
# ===================== FIN CAMBIO SOLICITADO =====================


def manejar_flujo_cotizacion_bloque(session: dict, message_text: str) -> dict:
    data = session["data"]
    texto = message_text or ""
    lineas = [l for l in texto.splitlines() if l.strip()]

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

    for linea in lineas:
        linea = linea.strip()
        if not linea:
            continue

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
            elif ("numero de parte" in etiqueta_norm or "numero parte" in etiqueta_norm or "descripcion" in etiqueta_norm or "descripción" in etiqueta_norm):
                campos["num_parte"] = valor_clean
            elif "marca" in etiqueta_norm:
                campos["marca"] = valor_clean
            elif ("direccion de entrega" in etiqueta_norm or "dirección de entrega" in etiqueta_norm or "direccion" in etiqueta_norm or "dirección" in etiqueta_norm or "domicilio" in etiqueta_norm):
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

    faltantes = [nombres_legibles[c] for c in obligatorios if not str(data.get(c, "")).strip()]

    try:
        cantidad_val = float(str(data.get("cantidad", "")).replace(",", "."))
        if cantidad_val <= 0:
            if "Cantidad (debe ser mayor a 0)" not in faltantes:
                faltantes.append("Cantidad (debe ser mayor a 0)")
    except Exception:
        if "Cantidad (valor numérico)" not in faltantes:
            faltantes.append("Cantidad (valor numérico)")

    if faltantes:
        session["state"] = "cotizacion_bloque"
        return build_reply(
            [
                "No fue posible registrar su solicitud, ya que existen campos obligatorios faltantes o inválidos.",
                "Campos a corregir:\n- " + "\n- ".join(faltantes),
                "Por favor, envíe únicamente los datos faltantes o corregidos.",
            ]
        )

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

    owner = data.get("owner_asignado")
    account_id = obtener_o_crear_account(data, owner=owner)
    crear_deal_en_zoho(data, account_id=account_id, owner=owner)

    session["state"] = "menu_principal"
    session["data"] = {}
    session["primer_correo_enviado"] = False

    return build_reply(
        [
            "Gracias. Hemos registrado su solicitud con el siguiente detalle:",
            resumen,
            "Un ejecutivo de Selec se pondrá en contacto con usted.",
        ]
    )
#Testeo ejemplo GitBook

def manejar_flujo_postventa_bloque(session: dict, message_text: str) -> dict:
    data = session["data"]
    texto = message_text or ""
    lineas = texto.splitlines()

    campos = {
        "nombre": data.get("nombre", ""),
        "rut": data.get("rut", ""),
        "numero_factura": data.get("numero_factura", ""),
        "detalle": data.get("detalle", ""),
    }

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

        if "nombre" in etiqueta_norm:
            campos["nombre"] = valor_clean
        elif etiqueta_norm in ("rut", "r.u.t", "r u t"):
            campos["rut"] = valor_clean
        elif "factura" in etiqueta_norm or "n° factura" in etiqueta_norm:
            campos["numero_factura"] = valor_clean
        elif "descripcion" in etiqueta_norm or "descripción" in etiqueta_norm or "problema" in etiqueta_norm:
            campos["detalle"] = valor_clean

    data.update(campos)

    obligatorios = ["nombre", "rut", "numero_factura"]
    nombres_legibles = {"nombre": "Nombre", "rut": "RUT", "numero_factura": "Número de factura"}

    faltantes = [nombres_legibles[c] for c in obligatorios if not str(data.get(c, "")).strip()]

    if faltantes:
        session["state"] = "postventa_bloque"
        return build_reply(
            [
                "No fue posible registrar correctamente su solicitud de postventa, ya que faltan datos obligatorios.",
                "Campos a corregir:\n- " + "\n- ".join(faltantes),
                "Por favor, envíe únicamente los datos faltantes o corregidos (por ejemplo: Número de factura: 12345).",
            ]
        )

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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    debug_mode = os.environ.get("FLASK_DEBUG", "false").strip().lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug_mode)
