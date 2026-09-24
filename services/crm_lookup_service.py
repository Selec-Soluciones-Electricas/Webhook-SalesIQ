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
        print(
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
            print(
                "[get_crm_readonly_access_token] "
                f"ERROR {resp.status_code}: {resp.text[:200]}"
            )
            return None

        data = resp.json()
        token = data.get("access_token")
        expires_in = int(data.get("expires_in", 3600))

        if not token:
            return None

        crm_readonly_token_cache["token"] = token
        crm_readonly_token_cache["expires_at"] = time.time() + expires_in

        return token

    except Exception as e:
        print(f"[get_crm_readonly_access_token] ERROR: {e}")
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


# =========================================================
# BÚSQUEDA DEL DEAL
# =========================================================

# Funcion desarrollada con el proposito de buscar un Deal en Zoho CRM por telefono, creada para ser utilizada en el flujo de busqueda de Deals por telefono en la ventana de conversacion.
def buscar_deal_id_por_telefono(
    candidatos_telefono: set,
    hora_creacion,
    hora_finalizacion=None,
) -> str:
    """
    Busca en Zoho CRM (vía COQL) un Deal con Lead_Source=
    'Chat Whatsapp' creado en la ventana real de la conversación
    (±1 día), cuyo teléfono en la Description coincida con
    alguno de los candidatos_telefono.

    Devuelve el Deal ID si encuentra una coincidencia única o la
    más cercana en tiempo; None si no encuentra nada.
    """

    if not candidatos_telefono or not hora_creacion:
        return None

    access_token = get_crm_readonly_access_token()

    if not access_token:
        return None

    hora_creacion = _a_utc(hora_creacion)

    extremos = [hora_creacion]

    if hora_finalizacion:
        extremos.append(_a_utc(hora_finalizacion))

    inicio = min(extremos) - timedelta(days=1)
    fin = max(extremos) + timedelta(days=1)

    # Se envía en UTC explícito; así no depende de si Chile
    # está en -03:00 o -04:00.
    inicio_str = inicio.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    fin_str = fin.strftime("%Y-%m-%dT%H:%M:%S+00:00")

    query = (
        "select id, Description, Created_Time from Deals "
        "where Lead_Source = 'Chat Whatsapp' "
        f"and Created_Time between '{inicio_str}' and '{fin_str}' "
        "limit 200"
    )

    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "Content-Type": "application/json",
    }

    try:

        resp = requests.post(
            f"{CRM_API_BASE_V2}/coql",
            headers=headers,
            json={"select_query": query},
            timeout=15,
        )

    except Exception as e:
        print(f"[buscar_deal_id_por_telefono] ERROR: {e}")
        return None

    if resp.status_code == 204:
        return None

    if resp.status_code not in (200, 201):
        print(
            "[buscar_deal_id_por_telefono] "
            f"status={resp.status_code} body={resp.text[:200]}"
        )
        return None

    registros = resp.json().get("data") or []

    coincidencias = [
        r
        for r in registros
        if _coincide(
            _telefono_de_descripcion(r.get("Description")),
            candidatos_telefono,
        )
    ]

    if not coincidencias:
        print(
            "[buscar_deal_id_por_telefono] Sin coincidencias "
            f"({len(registros)} deals revisados en la ventana)."
        )
        return None

    if len(coincidencias) == 1:
        return coincidencias[0].get("id")

    def _distancia(r):
        try:
            # Created_Time viene con offset, ej: 2026-08-26T09:16:00-05:00
            ct = datetime.fromisoformat(r["Created_Time"])
            return abs((_a_utc(ct) - hora_creacion).total_seconds())
        except Exception:
            return float("inf")

    coincidencias.sort(key=_distancia)

    print(
        "[buscar_deal_id_por_telefono] "
        f"{len(coincidencias)} coincidencias; se elige la más cercana."
    )

    return coincidencias[0].get("id")