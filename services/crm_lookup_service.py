import os
import re
import time

import requests

from datetime import timedelta


ACCOUNTS_BASE = "https://accounts.zoho.com"
CRM_API_BASE_V2 = "https://www.zohoapis.com/crm/v2"


# =========================================================
# CACHE DEL ACCESS TOKEN - CRM SOLO LECTURA (independiente
# del que usa zoho_service.py para crear Deals/Contacts)
# =========================================================

crm_readonly_token_cache = {
    "token": None,
    "expires_at": 0.0,
}


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


def extraer_candidatos_telefono(texto_completo: str) -> set:
    """
    Extrae del texto de la conversación cualquier secuencia de
    8 a 11 dígitos (candidatos a ser el teléfono que el
    visitante escribió en el formulario, que puede no coincidir
    con el número de su propio WhatsApp).
    """

    return set(re.findall(r"\d{8,11}", texto_completo or ""))


def buscar_deal_id_por_telefono(
    candidatos_telefono: set,
    hora_creacion,
    hora_finalizacion=None,
) -> str:
    """
    Busca en Zoho CRM (vía COQL) un Deal con Lead_Source=
    'Chat Whatsapp' creado en la ventana real de la conversación,
    cuya Description contenga alguno de los candidatos_telefono.

    Devuelve el Deal ID si encuentra una coincidencia única o la
    más cercana en tiempo; None si no encuentra nada.
    """

    access_token = get_crm_readonly_access_token()

    if not candidatos_telefono or not access_token or not hora_creacion:
        return None

    extremos = [hora_creacion]

    if hora_finalizacion:
        extremos.append(hora_finalizacion)

    inicio = min(extremos) - timedelta(days=1)
    fin = max(extremos) + timedelta(days=1)

    inicio_str = inicio.strftime("%Y-%m-%dT00:00:00-03:00")
    fin_str = fin.strftime("%Y-%m-%dT23:59:59-03:00")

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
        if any(
            cand in (r.get("Description") or "")
            for cand in candidatos_telefono
        )
    ]

    if not coincidencias:
        return None

    if len(coincidencias) == 1:
        return coincidencias[0].get("id")

    from datetime import datetime as _dt

    def _distancia(r):
        try:
            ct = _dt.strptime(r["Created_Time"][:19], "%Y-%m-%dT%H:%M:%S")
            return abs((ct - hora_creacion).total_seconds())
        except Exception:
            return float("inf")

    coincidencias.sort(key=_distancia)

    return coincidencias[0].get("id")