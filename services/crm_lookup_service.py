import os
import re
import time

import unicodedata

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


# Valores de ejemplo que el bot muestra en sus mensajes cuando
# faltan datos (ver ejemplos en finalizar/validar de
# conversation/quotation.py). Aparecen en muchas transcripciones
# y nunca identifican a un cliente.
TELEFONOS_EJEMPLO_BOT = (
    "56912345678",   # "Teléfono: 56912345678"
    "12345678-9",    # "RUT: 12345678-9"
)

EMAILS_EJEMPLO_BOT = (
    "cliente@empresa.com",
)

# Correos de la propia empresa (ejecutivos, pruebas como
# bot@selec.cl): nunca identifican al cliente.
DOMINIOS_EMAIL_INTERNOS_DEFECTO = ("selec.cl",)


def _telefonos_excluidos() -> set:
    """
    Números que NO deben usarse para buscar Deals: los ejemplos
    del bot, más los de la variable de entorno
    TELEFONOS_EXCLUIDOS (separados por coma). Se comparan por
    los últimos 8 dígitos.
    """

    crudo = ",".join(TELEFONOS_EJEMPLO_BOT) + "," + os.environ.get(
        "TELEFONOS_EXCLUIDOS", ""
    )

    return {
        _solo_digitos(t)[-8:]
        for t in crudo.split(",")
        if len(_solo_digitos(t)) >= 8
    }


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

    excluidos = _telefonos_excluidos()

    if excluidos:
        candidatos = {
            c for c in candidatos
            if c[-8:] not in excluidos
        }

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


def _email_excluido(email: str) -> bool:

    dominios = {
        d.strip().lower().lstrip("@")
        for d in (
            ",".join(DOMINIOS_EMAIL_INTERNOS_DEFECTO)
            + ","
            + os.environ.get("DOMINIOS_EMAIL_EXCLUIDOS", "")
        ).split(",")
        if d.strip()
    }

    emails = {
        e.strip().lower()
        for e in (
            ",".join(EMAILS_EJEMPLO_BOT)
            + ","
            + os.environ.get("EMAILS_EXCLUIDOS", "")
        ).split(",")
        if e.strip()
    }

    email = (email or "").lower()

    return email in emails or email.split("@")[-1] in dominios


# Funcion desarrollada con el fin de extraer los correos del cliente que aparecen en el chat, normalizados a minúsculas y sin los correos de ejemplo del bot ni los internos de la empresa.
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
        if not _email_excluido(e.lower().strip("."))
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
    "Contact_Name.Secondary_Email",
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

    campos = ["id", "Deal_Name", "Description", "Created_Time", "Lead_Source"]

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

    for campo in ("Email", "Secondary_Email"):
        valor = _valor_contacto(registro, campo)
        if valor:
            emails.add(str(valor).lower().strip("."))

    return emails


# =========================================================
# BÚSQUEDA GLOBAL (SIN VENTANA DE FECHAS)
# =========================================================
# Para chats antiguos, la fecha registrada puede no ser la de
# creación del Deal (ej. el chat se reabrió o se re-etiquetó
# meses después). En ese caso se busca el Deal directamente por
# el correo o teléfono del cliente, sin depender de la fecha.

_estado_busqueda_global = {
    "coql_contacto": True,
}


def _coql_deals_por_email_contacto(email: str, access_token: str) -> list:

    if not _estado_busqueda_global["coql_contacto"]:
        return []

    email_seguro = email.replace("'", "")

    query = (
        "select id, Description, Created_Time, Lead_Source from Deals "
        f"where Contact_Name.Email = '{email_seguro}' "
        "limit 50"
    )

    status, registros, texto = _ejecutar_coql(query, access_token)

    if registros:
        # Estos Deals se encontraron justamente por el correo del
        # Contacto: se deja registrado para que la verificación
        # posterior los reconozca aunque la Description no lo diga.
        for r in registros:
            r["Contact_Name.Email"] = email

    if registros is None:

        if status == 400:
            # La cuenta no permite filtrar por lookup en COQL.
            print(
                "[_coql_deals_por_email_contacto] COQL no acepta "
                f"filtro por Contact_Name.Email; se desactiva. body={texto}"
            )
            _estado_busqueda_global["coql_contacto"] = False

        return []

    return registros


def _search_deals_por_palabra(palabra: str, access_token: str) -> list:
    """
    Usa la API de búsqueda de Deals (word search). No requiere
    scopes adicionales a ZohoCRM.modules.deals.READ.
    """

    headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}

    try:

        resp = requests.get(
            f"{CRM_API_BASE_V2}/Deals/search",
            headers=headers,
            params={"word": palabra, "per_page": 50},
            timeout=20,
        )

    except Exception as e:
        print(f"[_search_deals_por_palabra] ERROR: {e}")
        return []

    if resp.status_code == 204:
        return []

    if resp.status_code != 200:
        print(
            "[_search_deals_por_palabra] "
            f"status={resp.status_code} body={resp.text[:200]}"
        )
        return []

    return resp.json().get("data") or []


# Funcion desarrollada con el fin de buscar Deals por el correo o teléfono del cliente, sin restringir por fecha.
def _buscar_deals_globales(telefonos: set, emails: set) -> list:

    access_token = get_crm_readonly_access_token()

    if not access_token:
        return None

    encontrados = {}

    for email in emails:

        for r in _coql_deals_por_email_contacto(email, access_token):
            encontrados[r.get("id")] = r

        for r in _search_deals_por_palabra(email, access_token):
            encontrados[r.get("id")] = r

    # Si hubo resultados por correo, no se busca por teléfono:
    # el correo es más específico y el teléfono agrega ruido.
    if encontrados:
        return list(encontrados.values())

    # Teléfonos: solo los de 8+ dígitos, para evitar ruido.
    for tel in telefonos:
        if len(tel) >= 8:
            for r in _search_deals_por_palabra(tel, access_token):
                encontrados[r.get("id")] = r

    return list(encontrados.values())


# =========================================================
# COINCIDENCIA POR NOMBRE DE EMPRESA
# =========================================================
# El bot crea el Deal como "Cotización - <empresa escrita por el
# cliente>" y repite ese nombre en su resumen final
# ("Nombre de la empresa: ..."). Sirve cuando un ejecutivo
# reescribió la Description del Deal y ya no tiene correo ni
# teléfono. Solo se usa dentro de la ventana de fechas del chat,
# nunca en la búsqueda global.

EMPRESAS_EXCLUIDAS = {"empresa ejemplo", "sin empresa", "bot"}

SUFIJOS_EMPRESA = (
    "spa", "s p a", "ltda", "limitada", "s a", "sa",
    "eirl", "e i r l", "sociedad anonima",
)

PATRON_EMPRESA_CHAT = re.compile(
    r"(?:Nombre de la empresa|Empresa)\s*:\s*([^\n]+)",
    re.IGNORECASE,
)


def _normalizar_empresa(nombre: str) -> str:
    """
    Minúsculas, sin tildes, sin puntuación ni sufijos
    societarios (SpA, Ltda, S.A., etc.).
    """

    texto = unicodedata.normalize("NFKD", str(nombre or "").lower())
    texto = texto.encode("ascii", "ignore").decode("ascii")
    texto = re.sub(r"[^a-z0-9 ]", " ", texto)
    texto = " ".join(texto.split())

    cambio = True

    while cambio:
        cambio = False
        for sufijo in SUFIJOS_EMPRESA:
            if texto.endswith(" " + sufijo):
                texto = texto[: -len(sufijo) - 1].strip()
                cambio = True

    return texto


# Funcion desarrollada con el fin de extraer del chat los nombres de empresa que escribió el cliente (o que el bot repitió en su resumen).
def extraer_candidatos_empresa(texto_chat: str) -> set:

    empresas = set()

    for valor in PATRON_EMPRESA_CHAT.findall(texto_chat or ""):

        normalizada = _normalizar_empresa(valor)

        if len(normalizada) >= 3 and normalizada not in EMPRESAS_EXCLUIDAS:
            empresas.add(normalizada)

    return empresas


def _empresa_del_deal(registro: dict) -> str:

    nombre = str(registro.get("Deal_Name") or "")

    # "Cotización - RV Equipos Industriales SpA" -> "RV Equipos..."
    nombre = re.sub(r"^\s*cotizaci[oó]n\s*-\s*", "", nombre, flags=re.IGNORECASE)

    return _normalizar_empresa(nombre)


def _coincide_empresa(registro: dict, empresas: set) -> bool:

    empresa_deal = _empresa_del_deal(registro)

    if len(empresa_deal) < 3 or empresa_deal in EMPRESAS_EXCLUIDAS:
        return False

    compacto_deal = empresa_deal.replace(" ", "")

    for e in empresas:

        # Igualdad ignorando espacios ("r v equipos" = "rv equipos").
        if e.replace(" ", "") == compacto_deal:
            return True

        # Contención solo si el nombre más corto tiene al menos
        # 2 palabras y cubre la mayor parte del más largo, para
        # que "equipos" no calce con "rv equipos industriales".
        corto, largo = sorted((e, empresa_deal), key=len)

        if (
            len(corto.split()) >= 2
            and len(corto) >= 0.6 * len(largo)
            and f" {corto} " in f" {largo} "
        ):
            return True

    return False


# Funcion desarrollada con el fin de cruzar una lista de Deals con los correos, teléfonos y empresa del chat, en ese orden de prioridad (del dato más específico al menos específico).
def _buscar_coincidencias(
    registros,
    telefonos,
    emails,
    min_digitos=MIN_DIGITOS_TELEFONO,
    empresas=None,
    excluir_ids=None,
):
    """
    Devuelve (coincidencias, criterio, ya_asignados).

    - coincidencias: Deals que calzan y NO están asignados a otra
      fila de Analytics.
    - ya_asignados: IDs que calzaban por el criterio más fuerte,
      pero ya pertenecen a otra fila. Si el criterio más fuerte
      solo apunta a Deals ya usados, se detiene ahí y no se
      prueba un criterio más débil (evita asignar un Deal
      equivocado de la misma empresa).
    """

    excluir_ids = excluir_ids or set()

    telefonos_validos = {t for t in telefonos if len(t) >= min_digitos}

    criterios = []

    if emails:
        criterios.append((
            "email",
            lambda r: bool(_emails_del_deal(r) & emails),
        ))

    if telefonos_validos:
        criterios.append((
            "telefono",
            lambda r: any(
                _coincide(tel_deal, telefonos_validos)
                for tel_deal in _telefonos_del_deal(r)
                if len(tel_deal) >= min_digitos
            ),
        ))

    if empresas:
        criterios.append((
            "empresa",
            lambda r: _coincide_empresa(r, empresas),
        ))

    for criterio, calza in criterios:

        encontrados = [r for r in registros if calza(r)]

        if not encontrados:
            continue

        disponibles = [
            r for r in encontrados
            if str(r.get("id")) not in excluir_ids
        ]

        if disponibles:
            return disponibles, criterio, []

        return [], criterio, [str(r.get("id")) for r in encontrados]

    return [], None, []


# Margen para considerar que un Deal fue creado "durante" el
# chat: el bot crea el Deal al finalizar la cotización.
MARGEN_CREACION_DEAL = timedelta(hours=2)


# Funcion desarrollada con el fin de elegir un único Deal entre varias coincidencias solo cuando la elección es segura; si no, devuelve None para dejar el caso en revisión manual.
def _elegir_unico(coincidencias: list, referencias: list):
    """
    Reglas, en orden:
        1. Si hay un solo candidato, se elige.
        2. Si solo uno tiene fuente 'Chat Whatsapp', se elige.
        3. Si solo uno fue creado dentro de ±2 h del inicio o
           fin del chat, se elige.
        4. Si no, es ambiguo: no se adivina.

    Devuelve (deal | None, ids_candidatos).
    """

    if len(coincidencias) == 1:
        return coincidencias[0], []

    whatsapp = [
        r for r in coincidencias
        if r.get("Lead_Source") == "Chat Whatsapp"
    ]

    if len(whatsapp) == 1:
        return whatsapp[0], [str(r.get("id")) for r in coincidencias]

    pool = whatsapp or coincidencias

    refs = [_a_utc(r) for r in referencias if r]

    def _cercano(r):
        try:
            ct = _a_utc(datetime.fromisoformat(r["Created_Time"]))
        except Exception:
            return False
        return any(abs(ct - ref) <= MARGEN_CREACION_DEAL for ref in refs)

    cercanos = [r for r in pool if _cercano(r)]

    if len(cercanos) == 1:
        return cercanos[0], [str(r.get("id")) for r in pool]

    return None, [str(r.get("id")) for r in pool][:5]


def _resolver(info, coincidencias, criterio, ya_asignados, referencias, motivo_si_falla, sufijo=""):
    """
    Aplica las reglas de seguridad y completa `info`.
    """

    if not coincidencias:

        if ya_asignados:
            info["motivo"] = "deal_ya_asignado"
            info["candidatos_globales"] = ya_asignados[:5]
            print(
                "[buscar_deal_id_por_chat] El Deal que calza por "
                f"{criterio} ya está asignado a otra fila: {ya_asignados}"
            )
        else:
            info["motivo"] = motivo_si_falla

        return info

    elegido, candidatos = _elegir_unico(coincidencias, referencias)

    if not elegido:
        info["motivo"] = f"ambiguo_{criterio}"
        info["candidatos_globales"] = candidatos
        print(
            "[buscar_deal_id_por_chat] Ambiguo por "
            f"{criterio}{sufijo}: {candidatos}"
        )
        return info

    info["deal_id"] = elegido.get("id")
    info["criterio"] = f"{criterio}{sufijo}"
    info["motivo"] = None

    if len(candidatos) > 1:
        info["candidatos_globales"] = candidatos[:5]

    print(
        "[buscar_deal_id_por_chat] "
        f"{len(coincidencias)} coincidencia(s) por {criterio}{sufijo}; "
        f"deal={info['deal_id']}"
    )

    return info


# Funcion desarrollada con el fin de resolver el Deal buscando por correo/teléfono en todo el CRM, cuando la búsqueda por ventana de fechas no encontró nada.
def _busqueda_global(
    info,
    telefonos,
    emails,
    referencias,
    motivo_si_falla,
    excluir_ids=None,
):

    candidatos = _buscar_deals_globales(telefonos, emails)

    if candidatos is None:
        info["motivo"] = "error_crm"
        info["detalle_error"] = ultimo_error_crm["detalle"]
        return info

    info["deals_busqueda_global"] = len(candidatos)

    # Se verifica que el Deal realmente contenga el dato del
    # cliente (la búsqueda por palabra puede traer ruido). Aquí
    # nunca se usa el nombre de empresa: sin ventana de fechas
    # no es lo bastante específico.
    coincidencias, criterio, ya_asignados = _buscar_coincidencias(
        candidatos,
        telefonos,
        emails,
        min_digitos=8,
        excluir_ids=excluir_ids,
    )

    return _resolver(
        info,
        coincidencias,
        criterio,
        ya_asignados,
        referencias,
        motivo_si_falla,
        sufijo="_busqueda_global",
    )


# Funcion desarrollada con el fin de buscar el Deal de un chat usando todo el texto de la conversación (teléfono y, como respaldo, correo), devolviendo además el motivo cuando no lo encuentra.
def buscar_deal_id_por_chat_detallado(
    texto_chat: str,
    hora_creacion,
    hora_finalizacion=None,
    margen_dias: int = 1,
    excluir_ids: set = None,
) -> dict:
    """
    Devuelve un dict:
        {
            "deal_id": str | None,
            "motivo": None | "sin_texto" | "sin_fecha" |
                      "error_crm" | "sin_deals_en_ventana" |
                      "sin_coincidencia" | "ambiguo_<criterio>" |
                      "deal_ya_asignado",
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

    empresas = extraer_candidatos_empresa(texto_chat)

    info["telefonos"] = len(telefonos)
    info["emails"] = len(emails)
    info["empresas"] = len(empresas)

    excluir_ids = {str(x) for x in (excluir_ids or set())}

    if not hora_creacion:
        return _busqueda_global(
            info, telefonos, emails, [], "sin_fecha", excluir_ids
        )

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

    referencias = [hora_creacion] + (
        [_a_utc(hora_finalizacion)] if hora_finalizacion else []
    )

    coincidencias, criterio, ya_asignados = _buscar_coincidencias(
        registros,
        telefonos,
        emails,
        min_digitos=MIN_DIGITOS_TELEFONO,
        empresas=empresas,
        excluir_ids=excluir_ids,
    )

    sufijo = ""

    # ---------------------------------------------------------
    # 2) Respaldo: cualquier Deal de la ventana, sin importar la
    #    fuente (un ejecutivo pudo cambiar el Lead_Source, o el
    #    bot antiguo usaba otro valor). Aquí se exige un match
    #    más estricto: teléfono de 8+ dígitos.
    # ---------------------------------------------------------
    if not coincidencias and not ya_asignados:

        todos = _consultar_deals_whatsapp(inicio, fin, solo_whatsapp=False)

        if todos:

            info["deals_en_ventana_cualquier_fuente"] = len(todos)

            coincidencias, criterio, ya_asignados = _buscar_coincidencias(
                todos,
                telefonos,
                emails,
                min_digitos=8,
                empresas=empresas,
                excluir_ids=excluir_ids,
            )

            sufijo = "_cualquier_fuente"

    if coincidencias or ya_asignados:
        return _resolver(
            info,
            coincidencias,
            criterio,
            ya_asignados,
            referencias,
            "sin_coincidencia",
            sufijo=sufijo,
        )

    motivo = (
        "sin_coincidencia"
        if registros or info.get("deals_en_ventana_cualquier_fuente")
        else "sin_deals_en_ventana"
    )

    print(
        "[buscar_deal_id_por_chat] Sin coincidencias en la ventana "
        f"({len(registros)} deals WhatsApp, "
        f"{info.get('deals_en_ventana_cualquier_fuente', 0)} en total, "
        f"{len(telefonos)} teléfonos, {len(emails)} correos). "
        "Se intenta búsqueda global."
    )

    # ---------------------------------------------------------
    # 3) Búsqueda global por correo/teléfono, sin fechas.
    # ---------------------------------------------------------
    return _busqueda_global(
        info, telefonos, emails, referencias, motivo, excluir_ids
    )


# Funcion desarrollada con el fin de buscar el Deal de un chat y devolver solo su ID (o None).
def buscar_deal_id_por_chat(
    texto_chat: str,
    hora_creacion,
    hora_finalizacion=None,
    margen_dias: int = 1,
    excluir_ids: set = None,
) -> str:

    return buscar_deal_id_por_chat_detallado(
        texto_chat,
        hora_creacion,
        hora_finalizacion,
        margen_dias,
        excluir_ids,
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