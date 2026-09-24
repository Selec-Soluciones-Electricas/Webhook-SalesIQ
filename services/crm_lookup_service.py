import os
import re
import time

import requests

from datetime import datetime, timedelta, timezone


ACCOUNTS_BASE = "https://accounts.zoho.com"
CRM_API_BASE_V2 = "https://www.zohoapis.com/crm/v2"

# Largo mínimo de dígitos para considerar una coincidencia de
# teléfono. Alineado con es_telefono_plausible (5 a 12 dígitos).
MIN_DIGITOS_TELEFONO = 5
MAX_DIGITOS_TELEFONO = 12


# =========================================================
# CACHE DEL ACCESS TOKEN - CRM SOLO LECTURA (independiente
# del que usa zoho_service.py para crear Deals/Contacts)
# =========================================================

crm_readonly_token_cache = {
    "token": None,
    "expires_at": 0.0,
}

# Último error de CRM (token o COQL), para poder devolverlo en
# el diagnóstico sin tener que revisar los logs.
ultimo_error_crm = {"detalle": None}


def _registrar_error_crm(detalle: str):
    ultimo_error_crm["detalle"] = detalle
    print(detalle)


# Funcion desarrollada con el fin de obtener un access token de Zoho CRM con permisos de solo lectura, para poder realizar consultas sin modificar datos en el CRM.
def get_crm_readonly_access_token() -> str:
    """
    Variables de entorno requeridas:
        CRM_READONLY_CLIENT_ID
        CRM_READONLY_CLIENT_SECRET
        CRM_READONLY_REFRESH_TOKEN
            (scope: ZohoCRM.modules.deals.READ,ZohoCRM.coql.READ)

    Token separado del que usa crear_deal_en_zoho — este solo
    lee, nunca escribe en CRM.
    """

    now = time.time()

    if (
        crm_readonly_token_cache["token"]
        and crm_readonly_token_cache["expires_at"] - 60 > now
    ):
        return crm_readonly_token_cache["token"]

    client_id = os.environ.get("CRM_READONLY_CLIENT_ID")
    client_secret = os.environ.get("CRM_READONLY_CLIENT_SECRET")
    refresh_token = os.environ.get("CRM_READONLY_REFRESH_TOKEN")

    if not client_id or not client_secret or not refresh_token:
        _registrar_error_crm(
            "[get_crm_readonly_access_token] ERROR: faltan "
            "CRM_READONLY_CLIENT_ID / CRM_READONLY_CLIENT_SECRET / "
            "CRM_READONLY_REFRESH_TOKEN."
        )
        return None

    try:

        resp = requests.post(
            f"{ACCOUNTS_BASE}/oauth/v2/token",
            params={
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
            },
            timeout=10,
        )

        if resp.status_code != 200:
            _registrar_error_crm(
                "[get_crm_readonly_access_token] "
                f"ERROR {resp.status_code}: {resp.text[:200]}"
            )
            return None

        data = resp.json()
        token = data.get("access_token")
        expires_in = int(data.get("expires_in", 3600))

        if not token:
            _registrar_error_crm(
                "[get_crm_readonly_access_token] Respuesta sin "
                f"access_token: {str(data)[:200]}"
            )
            return None

        crm_readonly_token_cache["token"] = token
        crm_readonly_token_cache["expires_at"] = time.time() + expires_in

        return token

    except Exception as e:
        _registrar_error_crm(f"[get_crm_readonly_access_token] ERROR: {e}")
        return None


# =========================================================
# UTILIDADES DE NORMALIZACIÓN
# =========================================================

def _solo_digitos(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _a_utc(dt: datetime) -> datetime:
    """
    Asegura que el datetime sea aware en UTC. Si viene naive,
    se asume que ya está en UTC (así lo generan cron.py y el
    script de backfill).
    """

    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc)


# Funcion desarrollada con el fin de extraer del texto de la conversación los posibles teléfonos que escribió el visitante, normalizados a solo dígitos.
def extraer_candidatos_telefono(texto_completo: str) -> set:
    """
    Candidatos = secuencias numéricas de 5 a 12 dígitos (igual
    que es_telefono_plausible), permitiendo '+', espacios,
    guiones y puntos entre los dígitos. Todo se normaliza a
    solo dígitos.

    El separador NO incluye saltos de línea, para no fusionar
    el teléfono con números de la línea siguiente (RUT,
    cantidad, etc.).
    """

    candidatos = set()

    patron = r"\+?\d[\d \t.\-]{3,20}\d"

    for bruto in re.findall(patron, texto_completo or ""):

        d = _solo_digitos(bruto)

        if MIN_DIGITOS_TELEFONO <= len(d) <= MAX_DIGITOS_TELEFONO:
            candidatos.add(d)

    return candidatos


# Funcion desarrollada con el fin de obtener el teléfono registrado en la Description del Deal, normalizado a solo dígitos.
def _telefono_de_descripcion(desc: str) -> str:
    """
    La Description del Deal se arma en crear_deal_en_zoho con
    una línea 'Teléfono: <valor>'. Se toma solo esa línea para
    no confundir el teléfono con el RUT u otros números.
    """

    m = re.search(r"Tel[eé]fono:\s*([^\n]+)", desc or "")

    return _solo_digitos(m.group(1)) if m else ""


# Funcion desarrollada con el fin de comparar el teléfono del Deal con los candidatos extraídos del chat, tolerando prefijos como +56 / 56 / 9.
def _coincide(tel_deal: str, candidatos: set) -> bool:

    if not tel_deal:
        return False

    return any(
        c == tel_deal or tel_deal.endswith(c) or c.endswith(tel_deal)
        for c in candidatos
        if min(len(c), len(tel_deal)) >= MIN_DIGITOS_TELEFONO
    )


# Funcion desarrollada con el fin de extraer los correos que aparecen en el chat, normalizados a minúsculas.
def extraer_candidatos_email(texto_completo: str) -> set:
    """
    Los correos enmascarados del resumen del bot (J****s@lsc.cl)
    generan fragmentos parciales, pero como la comparación es por
    igualdad exacta, nunca producen falsos positivos.
    """

    return {
        e.lower().strip(".")
        for e in re.findall(
            r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}",
            texto_completo or "",
        )
    }


# Funcion desarrollada con el fin de obtener el correo registrado en la Description del Deal.
def _email_de_descripcion(desc: str) -> str:

    m = re.search(r"Correo:\s*([^\s]+)", desc or "")

    return m.group(1).lower().strip(".") if m else ""


# =========================================================
# BÚSQUEDA DEL DEAL
# =========================================================

# Campos del Contacto asociado al Deal que se leen vía COQL
# (lookup). Si la cuenta no permite leer lookups en COQL, se
# desactivan automáticamente y se usa solo la Description.
CAMPOS_CONTACTO = (
    "Contact_Name.Email",
    "Contact_Name.Phone",
    "Contact_Name.Mobile",
)

_estado_coql = {"usar_campos_contacto": True}

LIMITE_COQL = 200

# Profundidad máxima al dividir una ventana que devuelve el
# máximo de registros (200). 5 niveles = hasta 32 sub-ventanas.
PROFUNDIDAD_MAX_DIVISION = 5


def _ejecutar_coql(query: str, access_token: str):
    """
    Devuelve (status_code, registros | None, texto_respuesta).
    """

    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "Content-Type": "application/json",
    }

    try:

        resp = requests.post(
            f"{CRM_API_BASE_V2}/coql",
            headers=headers,
            json={"select_query": query},
            timeout=20,
        )

    except Exception as e:
        return None, None, f"Excepción: {e}"

    if resp.status_code == 204:
        return 204, [], ""

    if resp.status_code not in (200, 201):
        return resp.status_code, None, resp.text[:300]

    return resp.status_code, resp.json().get("data") or [], ""


def _consultar_ventana(inicio, fin, solo_whatsapp, access_token):
    """
    Una sola consulta COQL para la ventana. Devuelve la lista de
    registros o None si falla.
    """

    inicio_str = inicio.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    fin_str = fin.strftime("%Y-%m-%dT%H:%M:%S+00:00")

    filtro_fuente = (
        "Lead_Source = 'Chat Whatsapp' and "
        if solo_whatsapp
        else ""
    )

    campos = ["id", "Description", "Created_Time", "Lead_Source"]

    if _estado_coql["usar_campos_contacto"]:
        campos += list(CAMPOS_CONTACTO)

    query = (
        f"select {', '.join(campos)} from Deals "
        f"where {filtro_fuente}"
        f"Created_Time between '{inicio_str}' and '{fin_str}' "
        f"limit {LIMITE_COQL}"
    )

    status, registros, texto = _ejecutar_coql(query, access_token)

    # Si la cuenta no acepta campos de lookup en COQL, se
    # desactivan y se reintenta una vez sin ellos.
    if (
        registros is None
        and status == 400
        and _estado_coql["usar_campos_contacto"]
    ):
        print(
            "[_consultar_ventana] COQL rechazó los campos del "
            f"Contacto; se reintenta sin ellos. body={texto}"
        )
        _estado_coql["usar_campos_contacto"] = False
        return _consultar_ventana(inicio, fin, solo_whatsapp, access_token)

    if registros is None:
        _registrar_error_crm(
            "[_consultar_deals_whatsapp] "
            f"status={status} body={texto} query={query}"
        )

    return registros


# Funcion desarrollada con el fin de consultar en CRM los Deals creados dentro de una ventana de tiempo (por defecto solo los de WhatsApp), dividiendo la ventana si se alcanza el límite de 200 registros de COQL.
def _consultar_deals_whatsapp(
    inicio: datetime,
    fin: datetime,
    solo_whatsapp: bool = True,
    _profundidad: int = 0,
) -> list:

    access_token = get_crm_readonly_access_token()

    if not access_token:
        return None

    registros = _consultar_ventana(inicio, fin, solo_whatsapp, access_token)

    if registros is None:
        return None

    # Si llegó al límite, puede haber más registros: se divide
    # la ventana en dos mitades y se consulta cada una.
    if (
        len(registros) >= LIMITE_COQL
        and _profundidad < PROFUNDIDAD_MAX_DIVISION
    ):

        mitad = inicio + (fin - inicio) / 2

        primera = _consultar_deals_whatsapp(
            inicio, mitad, solo_whatsapp, _profundidad + 1
        )
        segunda = _consultar_deals_whatsapp(
            mitad, fin, solo_whatsapp, _profundidad + 1
        )

        if primera is None or segunda is None:
            return registros

        vistos = set()
        combinados = []

        for r in primera + segunda:
            if r.get("id") not in vistos:
                vistos.add(r.get("id"))
                combinados.append(r)

        return combinados

    return registros


def _valor_contacto(registro: dict, campo: str):
    """
    COQL puede devolver el lookup como clave plana
    ("Contact_Name.Email") o anidada ({"Contact_Name": {...}}).
    """

    plano = registro.get(f"Contact_Name.{campo}")

    if plano:
        return plano

    contacto = registro.get("Contact_Name")

    if isinstance(contacto, dict):
        return contacto.get(campo)

    return None


# Palabras que identifican una línea de teléfono en la Description,
# para no confundir el teléfono con el RUT u otros números.
PATRON_LINEA_TELEFONO = re.compile(
    r"(tel[eé]fono|telefono|fono|celular|m[oó]vil|whats?app|contacto)\s*:?\s*([^\n]+)",
    re.IGNORECASE,
)


# Funcion desarrollada con el fin de obtener todos los teléfonos asociados a un Deal: líneas de teléfono de la Description y teléfonos del Contacto.
def _telefonos_del_deal(registro: dict) -> set:

    telefonos = set()

    desc = registro.get("Description") or ""

    for _, valor in PATRON_LINEA_TELEFONO.findall(desc):
        d = _solo_digitos(valor)
        if MIN_DIGITOS_TELEFONO <= len(d) <= MAX_DIGITOS_TELEFONO:
            telefonos.add(d)

    for campo in ("Phone", "Mobile"):
        d = _solo_digitos(str(_valor_contacto(registro, campo) or ""))
        if MIN_DIGITOS_TELEFONO <= len(d) <= MAX_DIGITOS_TELEFONO:
            telefonos.add(d)

    return telefonos


# Funcion desarrollada con el fin de obtener todos los correos asociados a un Deal: cualquier correo en la Description y el correo del Contacto.
def _emails_del_deal(registro: dict) -> set:

    emails = extraer_candidatos_email(registro.get("Description") or "")

    email_contacto = _valor_contacto(registro, "Email")

    if email_contacto:
        emails.add(str(email_contacto).lower().strip("."))

    return emails


# Funcion desarrollada con el fin de cruzar una lista de Deals con los teléfonos y correos del chat.
def _buscar_coincidencias(registros, telefonos, emails, min_digitos=MIN_DIGITOS_TELEFONO):

    telefonos_validos = {t for t in telefonos if len(t) >= min_digitos}

    coincidencias = [
        r
        for r in registros
        if any(
            _coincide(tel_deal, telefonos_validos)
            for tel_deal in _telefonos_del_deal(r)
            if len(tel_deal) >= min_digitos
        )
    ]

    if coincidencias:
        return coincidencias, "telefono"

    if emails:

        coincidencias = [
            r
            for r in registros
            if _emails_del_deal(r) & emails
        ]

        if coincidencias:
            return coincidencias, "email"

    return [], None


# Funcion desarrollada con el fin de buscar el Deal de un chat usando todo el texto de la conversación (teléfono y, como respaldo, correo), devolviendo además el motivo cuando no lo encuentra.
def buscar_deal_id_por_chat_detallado(
    texto_chat: str,
    hora_creacion,
    hora_finalizacion=None,
    margen_dias: int = 1,
) -> dict:
    """
    Devuelve un dict:
        {
            "deal_id": str | None,
            "motivo": None | "sin_texto" | "sin_fecha" |
                      "error_crm" | "sin_deals_en_ventana" |
                      "sin_coincidencia",
            "criterio": "telefono" | "email" | None,
            "telefonos": int, "emails": int,
            "deals_en_ventana": int,
            "ventana": [inicio_iso, fin_iso] | None,
        }
    """

    info = {
        "deal_id": None,
        "motivo": None,
        "criterio": None,
        "telefonos": 0,
        "emails": 0,
        "deals_en_ventana": 0,
        "ventana": None,
    }

    if not texto_chat or not texto_chat.strip():
        info["motivo"] = "sin_texto"
        return info

    telefonos = extraer_candidatos_telefono(texto_chat)
    emails = extraer_candidatos_email(texto_chat)

    info["telefonos"] = len(telefonos)
    info["emails"] = len(emails)

    if not hora_creacion:
        info["motivo"] = "sin_fecha"
        return info

    hora_creacion = _a_utc(hora_creacion)

    extremos = [hora_creacion]

    if hora_finalizacion:
        extremos.append(_a_utc(hora_finalizacion))

    inicio = min(extremos) - timedelta(days=margen_dias)
    fin = max(extremos) + timedelta(days=margen_dias)

    info["ventana"] = [inicio.isoformat(), fin.isoformat()]

    ultimo_error_crm["detalle"] = None

    # ---------------------------------------------------------
    # 1) Deals con Lead_Source = 'Chat Whatsapp'
    # ---------------------------------------------------------
    registros = _consultar_deals_whatsapp(inicio, fin)

    if registros is None:
        info["motivo"] = "error_crm"
        info["detalle_error"] = ultimo_error_crm["detalle"]
        return info

    info["deals_en_ventana"] = len(registros)

    coincidencias, criterio = _buscar_coincidencias(
        registros, telefonos, emails, min_digitos=MIN_DIGITOS_TELEFONO
    )

    # ---------------------------------------------------------
    # 2) Respaldo: cualquier Deal de la ventana, sin importar la
    #    fuente (un ejecutivo pudo cambiar el Lead_Source, o el
    #    bot antiguo usaba otro valor). Aquí se exige un match
    #    más estricto: correo exacto o teléfono de 8+ dígitos.
    # ---------------------------------------------------------
    if not coincidencias:

        todos = _consultar_deals_whatsapp(inicio, fin, solo_whatsapp=False)

        if todos:

            info["deals_en_ventana_cualquier_fuente"] = len(todos)

            coincidencias, criterio = _buscar_coincidencias(
                todos, telefonos, emails, min_digitos=8
            )

            if criterio:
                criterio = f"{criterio}_cualquier_fuente"

    if not coincidencias:
        info["motivo"] = (
            "sin_coincidencia"
            if registros or info.get("deals_en_ventana_cualquier_fuente")
            else "sin_deals_en_ventana"
        )
        print(
            "[buscar_deal_id_por_chat] Sin coincidencias "
            f"({len(registros)} deals WhatsApp, "
            f"{info.get('deals_en_ventana_cualquier_fuente', 0)} en total, "
            f"{len(telefonos)} teléfonos, {len(emails)} correos)."
        )
        return info

    def _distancia(r):
        try:
            # Created_Time viene con offset, ej: 2026-08-26T09:16:00-05:00
            ct = datetime.fromisoformat(r["Created_Time"])
            return abs((_a_utc(ct) - hora_creacion).total_seconds())
        except Exception:
            return float("inf")

    coincidencias.sort(key=_distancia)

    info["deal_id"] = coincidencias[0].get("id")
    info["criterio"] = criterio

    print(
        "[buscar_deal_id_por_chat] "
        f"{len(coincidencias)} coincidencia(s) por {criterio}; "
        f"deal={info['deal_id']}"
    )

    return info


# Funcion desarrollada con el fin de buscar el Deal de un chat y devolver solo su ID (o None).
def buscar_deal_id_por_chat(
    texto_chat: str,
    hora_creacion,
    hora_finalizacion=None,
    margen_dias: int = 1,
) -> str:

    return buscar_deal_id_por_chat_detallado(
        texto_chat,
        hora_creacion,
        hora_finalizacion,
        margen_dias,
    )["deal_id"]


# Funcion mantenida por compatibilidad: busca solo por teléfono a partir de candidatos ya extraídos.
def buscar_deal_id_por_telefono(
    candidatos_telefono: set,
    hora_creacion,
    hora_finalizacion=None,
) -> str:

    if not candidatos_telefono:
        return None

    return buscar_deal_id_por_chat(
        "\n".join(candidatos_telefono),
        hora_creacion,
        hora_finalizacion,
    )