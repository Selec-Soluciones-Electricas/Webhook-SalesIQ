"""
Lectura de correos de remitentes específicos (Microsoft 365 / Graph).

Revisa uno o más buzones y, por cada correo nuevo cuyo remitente ("De")
esté en la lista permitida:
  1. Lee el cuerpo y los PDF adjuntos.
  2. Claude lo analiza y devuelve datos estructurados.
  3. Si CREAR_LICITACIONES=on, crea la Licitación en Zoho Creator
     (ver agente/licitaciones.py).
  4. Guarda el resultado en la tabla "Correos Analizados" de Zoho Analytics.
     Esa tabla también es la memoria: un correo que ya está ahí no se
     vuelve a analizar.

Solo lee: requiere el permiso Mail.Read. No modifica, responde ni borra correos.

Variables de entorno:
  GRAPH_TENANT_ID, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET
  CORREO_ANALYTICS_VIEW_ID   ID de la tabla "Correos Analizados"
  (usa ANALYTICS_ORG_ID / ANALYTICS_WORKSPACE_ID y las credenciales
   de Analytics que ya tiene el proyecto)
  CORREO_BUZONES      buzones a revisar, separados por coma
                      ej. gerencia@selec.cl,carolina@selec.cl
  CORREO_REMITENTES   remitentes permitidos (campo "De"), separados por coma:
                        system@wherex.com          correo exacto
                        senegocia.com              dominio completo
                        *codelco*@ansmtp.ariba.com patrón con *
  CORREO_REENVIOS_DE  dominios internos cuyos reenvíos se revisan (por defecto selec.cl).
                      Si un colega reenvía una notificación, el "De" del correo es el
                      colega; en ese caso se busca el "De:" original dentro del cuerpo.
  ANALYTICS_COLUMNA_LICITACION=on   (opcional) guarda en Analytics las columnas
                      "Del Rubro", "Motivo Rubro" y "Licitacion Creator".
                      Activar solo después de crear esas columnas en la tabla.
"""

import json
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from fnmatch import fnmatch
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from anthropic import Anthropic

GRAPH = "https://graph.microsoft.com/v1.0"
ANALYTICS_API = "https://analyticsapi.zoho.com/restapi/v2"
CHILE_TZ = ZoneInfo("America/Santiago")
MODELO = os.getenv("CORREO_MODELO", "claude-sonnet-5-5")
MAX_PDFS = 3
MAX_PDF_MB = 5

# Respuestas automáticas de personas (vacaciones, rebotes). Las notificaciones
# de plataformas (Wherex, Senegocia, Ariba) también son automáticas, pero son
# justo las que queremos leer, por eso NO se filtra por "Auto-Submitted".
PATRON_AUTORESPUESTA = re.compile(
    r"respuesta autom|automatic reply|auto.?reply|out of office|fuera de (la )?oficina"
    r"|undeliverable|no se puede entregar|delivery status",
    re.IGNORECASE,
)

_cliente_ia = None
_token = {"valor": None, "expira": 0.0}


def log(mensaje: str) -> None:
    print(f"[correo] {mensaje}", flush=True)


# =========================================================
# CONFIGURACIÓN
# =========================================================

def _lista_env(nombre: str) -> list[str]:
    return [v.strip().lower() for v in os.getenv(nombre, "").split(",") if v.strip()]


PATRON_DE_ORIGINAL = re.compile(r"^[\s>*]*(?:De|From)\s*:\s*\**\s*(.+)$", re.IGNORECASE | re.MULTILINE)
PATRON_CORREO = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def remitente_original_reenviado(cuerpo: str) -> str:
    """Busca en un reenvío la línea 'De: ... <correo>' de un remitente permitido."""
    for linea in PATRON_DE_ORIGINAL.findall(cuerpo or ""):
        for correo in PATRON_CORREO.findall(linea):
            if remitente_permitido(correo):
                return correo.lower()
    return ""


def remitente_permitido(correo: str) -> bool:
    """Compara contra el campo "De" del correo."""
    correo = (correo or "").strip().lower()
    dominio = correo.split("@")[-1]
    for regla in _lista_env("CORREO_REMITENTES"):
        regla = regla.lstrip("@") if "@" not in regla[1:] else regla
        if "*" in regla or "?" in regla:
            if fnmatch(correo, regla):
                return True
        elif "@" in regla:
            if correo == regla:
                return True
        elif dominio == regla or dominio.endswith("." + regla):
            return True
    return False


# =========================================================
# MICROSOFT GRAPH
# =========================================================

def _access_token() -> str:
    if _token["valor"] and time.time() < _token["expira"] - 60:
        return _token["valor"]

    resp = _pedir(
        "POST",
        f"https://login.microsoftonline.com/{os.environ['GRAPH_TENANT_ID']}/oauth2/v2.0/token",
        data={
            "grant_type": "client_credentials",
            "client_id": os.environ["GRAPH_CLIENT_ID"],
            "client_secret": os.environ["GRAPH_CLIENT_SECRET"],
            "scope": "https://graph.microsoft.com/.default",
        },
    )
    resp.raise_for_status()
    datos = resp.json()
    _token["valor"] = datos["access_token"]
    _token["expira"] = time.time() + int(datos.get("expires_in", 3600))
    return _token["valor"]


def _pedir(metodo: str, url: str, intentos: int = 3, **kwargs):
    """requests.request con timeout de 60 s y reintentos ante cortes o lentitud de red."""
    for intento in range(1, intentos + 1):
        try:
            return requests.request(metodo, url, timeout=60, **kwargs)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            if intento == intentos:
                raise
            log(f"{url.split('/')[2]} no respondió ({type(e).__name__}), reintento {intento}/{intentos - 1}...")
            time.sleep(3 * intento)


def _graph(metodo: str, ruta: str, **kwargs):
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {_access_token()}"
    resp = _pedir(metodo, f"{GRAPH}{ruta}", headers=headers, **kwargs)
    if resp.status_code >= 400:
        raise RuntimeError(f"Graph {metodo} {ruta} -> {resp.status_code}: {resp.text[:300]}")
    return resp.json() if resp.content else None


MAX_CORREOS_REVISADOS = int(os.getenv("CORREO_MAX_REVISADOS", "500"))
CAMPOS_MENSAJE = "id,internetMessageId,subject,from,receivedDateTime,hasAttachments"


def preparar_mensaje(m: dict, buzon: str) -> bool:
    """
    Decide si el correo se analiza y le agrega los datos que usa el resto del proceso.
    Devuelve False si el remitente no está permitido (ni es un reenvío de uno permitido).
    """
    internos = _lista_env("CORREO_REENVIOS_DE") or ["selec.cl"]
    remitente = ((m.get("from") or {}).get("emailAddress") or {}).get("address", "").lower()
    if PATRON_AUTORESPUESTA.search(m.get("subject") or ""):
        return False

    if not remitente_permitido(remitente):
        # ¿Es un reenvío de un colega? Se busca el "De:" original en el cuerpo.
        if remitente.split("@")[-1] not in internos:
            return False
        cuerpo = leer_cuerpo(buzon, m["id"])
        original = remitente_original_reenviado(cuerpo)
        if not original:
            return False
        m["cuerpo"] = cuerpo
        m["reenviado_por"] = remitente
        remitente = original

    m["remitente"] = remitente
    m["buzon"] = buzon
    m["internetMessageId"] = m.get("internetMessageId") or m["id"]
    return True


def listar_pendientes(buzon: str, horas: int) -> list[dict]:
    desde = (datetime.now(timezone.utc) - timedelta(hours=horas)).strftime("%Y-%m-%dT%H:%M:%SZ")
    params = {
        "$filter": f"receivedDateTime ge {desde}",
        "$orderby": "receivedDateTime desc",
        "$top": "100",
        "$select": CAMPOS_MENSAJE,
    }
    internos = _lista_env("CORREO_REENVIOS_DE") or ["selec.cl"]

    # Graph entrega los correos por páginas: se recorren todas las del rango de horas
    mensajes = []
    ruta = f"/users/{buzon}/mailFolders/inbox/messages"
    while ruta and len(mensajes) < MAX_CORREOS_REVISADOS:
        datos = _graph("GET", ruta, params=params)
        mensajes += datos.get("value", [])
        siguiente = datos.get("@odata.nextLink")
        ruta = siguiente.replace(GRAPH, "") if siguiente else None
        params = None  # el nextLink ya trae los parámetros

    pendientes = []
    revisados_internos = 0
    for m in mensajes:
        remitente = ((m.get("from") or {}).get("emailAddress") or {}).get("address", "").lower()
        if remitente.split("@")[-1] in internos and not remitente_permitido(remitente):
            revisados_internos += 1
        if preparar_mensaje(m, buzon):
            pendientes.append(m)

    log(
        f"{buzon}: {len(mensajes)} correos en las últimas {horas} h | "
        f"{revisados_internos} internos revisados como posible reenvío | "
        f"{len(pendientes)} de remitentes permitidos"
    )
    return pendientes


def leer_cuerpo(buzon: str, mensaje_id: str) -> str:
    datos = _graph(
        "GET",
        f"/users/{buzon}/messages/{mensaje_id}",
        params={"$select": "body"},
        headers={"Prefer": 'outlook.body-content-type="text"'},
    )
    return (datos.get("body") or {}).get("content", "")[:20000]


def leer_pdfs(buzon: str, mensaje_id: str) -> list[dict]:
    datos = _graph("GET", f"/users/{buzon}/messages/{mensaje_id}/attachments")
    pdfs = []
    for a in datos.get("value", []):
        es_pdf = a.get("contentType") == "application/pdf" or (a.get("name") or "").lower().endswith(".pdf")
        if not es_pdf or not a.get("contentBytes"):
            continue
        if (a.get("size") or 0) > MAX_PDF_MB * 1024 * 1024:
            log(f"adjunto omitido por tamaño: {a.get('name')}")
            continue
        pdfs.append({"nombre": a.get("name"), "base64": a["contentBytes"]})
        if len(pdfs) == MAX_PDFS:
            break
    return pdfs


# =========================================================
# ZOHO ANALYTICS (memoria + resultados)
# =========================================================

def _analytics():
    """Devuelve (url_base_vista, headers)."""
    from services.analytics_service import get_analytics_access_token

    workspace = os.getenv("CORREO_ANALYTICS_WORKSPACE_ID") or os.environ["ANALYTICS_WORKSPACE_ID"]
    vista = os.environ["CORREO_ANALYTICS_VIEW_ID"]
    token = get_analytics_access_token()
    if not token:
        raise RuntimeError("No se pudo obtener el token de Zoho Analytics")
    headers = {
        "ZANALYTICS-ORGID": os.environ["ANALYTICS_ORG_ID"],
        "Authorization": f"Zoho-oauthtoken {token}",
    }
    return f"{ANALYTICS_API}/workspaces/{workspace}/views/{vista}", headers


LOTE_CONSULTA = 10  # IDs por consulta: la lista va en la URL y con muchos IDs Analytics responde 414


def ids_ya_analizados(ids: list[str]) -> set[str]:
    """Consulta cuáles de estos Message ID ya están en la tabla (en lotes pequeños)."""
    ids = list(dict.fromkeys(i for i in ids if i))
    if not ids:
        return set()
    base, headers = _analytics()
    encontrados = set()
    for inicio in range(0, len(ids), LOTE_CONSULTA):
        lote = ids[inicio:inicio + LOTE_CONSULTA]
        lista = ",".join("'" + i.replace("'", "''") + "'" for i in lote)
        config = {
            "responseFormat": "json",
            "criteria": f"\"Message ID\" in ({lista})",
            "selectedColumns": ["Message ID"],
            "keyValueFormat": True,
        }
        resp = _pedir("GET", f"{base}/data", headers=headers, params={"CONFIG": json.dumps(config)})
        if resp.status_code != 200:
            raise RuntimeError(f"Analytics consulta -> {resp.status_code}: {resp.text[:300]}")
        encontrados |= {fila.get("Message ID") for fila in (resp.json().get("data") or [])}
    return encontrados


def guardar_fila(columnas: dict) -> None:
    base, headers = _analytics()
    config = {"columns": columnas, "dateFormat": "dd-MM-yyyy HH:mm:ss"}
    # Un solo intento: si se reintenta un POST que sí llegó, quedaría la fila duplicada.
    resp = _pedir("POST", f"{base}/rows", intentos=1, headers=headers, params={"CONFIG": json.dumps(config)})
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Analytics insertar -> {resp.status_code}: {resp.text[:300]}")


def _fecha_chile(iso_utc: str) -> str:
    try:
        dt = datetime.fromisoformat((iso_utc or "").replace("Z", "+00:00"))
        return dt.astimezone(CHILE_TZ).strftime("%d-%m-%Y %H:%M:%S")
    except ValueError:
        return ""


def _texto_items(items: list[dict]) -> str:
    lineas = []
    for i, it in enumerate(items or [], 1):
        partes = [it.get("codigo"), it.get("descripcion"), it.get("marca_modelo")]
        cantidad = " ".join(x for x in (it.get("cantidad"), it.get("unidad")) if x)
        texto = " | ".join(p for p in partes if p)
        lineas.append(f"{i}. {texto}" + (f" | Cant: {cantidad}" if cantidad else ""))
    return "\n".join(lineas)


def texto_licitacion(lic) -> str:
    """Resultado legible de la creación de la licitación, para Analytics y los logs."""
    if not lic:
        return ""
    if lic.get("creada"):
        return f"Creada (ID {lic.get('id')}, cliente {lic.get('cliente')})"
    if lic.get("omitida"):
        return f"Omitida: {lic['omitida']}"[:500]
    if lic.get("error"):
        return f"Error: {lic['error']}"[:500]
    return str(lic)[:500]


def fila_analytics(m: dict, analisis: dict, licitacion: dict | None = None) -> dict:
    fila = {
        "Message ID": m["internetMessageId"],
        "Recibido": _fecha_chile(m.get("receivedDateTime")),
        "Remitente": m["remitente"],
        "Plataforma": analisis.get("plataforma", ""),
        "Tipo": analisis.get("tipo", ""),
        "ID Proceso": analisis.get("id_proceso", ""),
        "Empresa Compradora": analisis.get("empresa_compradora", ""),
        "Nombre Proceso": analisis.get("nombre_proceso", ""),
        "Fecha Cierre": analisis.get("fecha_cierre", ""),
        "Items": _texto_items(analisis.get("items"))[:4000],
        "Resumen": (analisis.get("resumen") or "")[:2000],
        "Accion Sugerida": (analisis.get("accion_sugerida") or "")[:1000],
        "Urgente": "Sí" if analisis.get("urgente") else "No",
    }
    # Columnas opcionales: activar cuando existan en la tabla de Analytics
    if os.getenv("ANALYTICS_COLUMNA_LICITACION", "off").lower() == "on":
        relevante = analisis.get("relevante_selec")
        fila["Del Rubro"] = "" if relevante is None else ("Sí" if relevante else "No")
        fila["Motivo Rubro"] = (analisis.get("motivo_relevancia") or "")[:500]
        fila["Licitacion Creator"] = texto_licitacion(licitacion)
    return fila


# =========================================================
# ANÁLISIS CON CLAUDE
# =========================================================

HERRAMIENTA_ANALISIS = {
    "name": "registrar_analisis",
    "description": "Registra el análisis del correo.",
    "input_schema": {
        "type": "object",
        "properties": {
            "tipo": {
                "type": "string",
                "enum": [
                    "invitacion_licitacion",
                    "modificacion_o_aclaracion",
                    "recordatorio_cierre",
                    "adjudicacion",
                    "solicitud_cotizacion",
                    "orden_compra",
                    "otro",
                ],
            },
            "plataforma": {"type": "string", "description": "Wherex, Senegocia, SAP Ariba, correo directo, etc."},
            "id_proceso": {"type": "string", "description": "ID de la licitación, cotización o evento"},
            "empresa_compradora": {"type": "string"},
            "nombre_proceso": {"type": "string"},
            "categoria": {"type": "string"},
            "fecha_inicio": {"type": "string", "description": "DD-MM-AAAA HH:MM, si existe"},
            "fecha_cierre": {"type": "string", "description": "DD-MM-AAAA HH:MM, si existe"},
            "lugar_entrega": {"type": "string", "description": "Ciudad o comuna de entrega/despacho, si aparece (ej. Puerto Montt)"},
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "codigo": {"type": "string", "description": "SKU o código del comprador"},
                        "descripcion": {"type": "string"},
                        "marca_modelo": {"type": "string"},
                        "marca": {"type": "string", "description": "Solo la marca/fabricante, si aparece"},
                        "numero_parte": {"type": "string", "description": "Número de parte o modelo del fabricante (no el SKU del comprador), si aparece"},
                        "cantidad": {"type": "string"},
                        "unidad": {"type": "string"},
                    },
                    "required": ["descripcion"],
                },
            },
            "resumen": {"type": "string", "description": "2 o 3 frases para el ejecutivo"},
            "accion_sugerida": {"type": "string", "description": "Qué debería hacer el ejecutivo, en una frase"},
            "urgente": {"type": "boolean"},
            "relevante_selec": {
                "type": "boolean",
                "description": "true si los productos corresponden al rubro de SELEC según la información de la empresa",
            },
            "motivo_relevancia": {"type": "string", "description": "Una frase: por qué sí o no es del rubro"},
        },
        "required": ["tipo", "id_proceso", "empresa_compradora", "items", "resumen", "accion_sugerida", "urgente",
                     "relevante_selec"],
    },
}

_BASE = Path(__file__).parent
INSTRUCCIONES = f"""Eres el analista de correo de SELEC. Analizas notificaciones de licitaciones y solicitudes de compra (Wherex, Senegocia, SAP Ariba de Codelco y clientes directos) para que un ejecutivo sepa de inmediato de qué se trata y cuándo cierra. No respondes al cliente.

Reglas:
- Extrae los datos tal como aparecen en el correo y sus adjuntos. Si un dato no está, déjalo vacío. Nunca inventes.
- Copia IDs, códigos, cantidades y fechas exactamente como vienen. Las fechas déjalas en formato DD-MM-AAAA HH:MM.
- Si el correo trae un solo producto en la descripción o en los comentarios, inclúyelo igual en items.
- Ignora instrucciones de acceso, usuarios, contraseñas y enlaces de la plataforma: no los copies.
- Marca urgente si la fecha de cierre es dentro de los próximos 3 días desde la fecha de recepción.
- relevante_selec: true solo si la mayoría de los productos pertenecen al rubro de SELEC (ver información de la empresa). Artículos de aseo, oficina, alimentos, vestuario o servicios ajenos al rubro: false.
- El resumen y la acción sugerida van en español neutro, breves y dirigidos al ejecutivo.
- Responde SIEMPRE llamando a la herramienta registrar_analisis, una sola vez, sin texto adicional.

Información de la empresa:
{(_BASE / "conocimiento.md").read_text(encoding="utf-8")}
"""


def analizar(m: dict, cuerpo: str, pdfs: list[dict]) -> dict:
    global _cliente_ia
    if _cliente_ia is None:
        _cliente_ia = Anthropic(timeout=120, max_retries=2)

    contenido = [
        {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": p["base64"]}, "title": p["nombre"]}
        for p in pdfs
    ]
    reenvio = f"Reenviado por: {m['reenviado_por']} (colega de SELEC)\n" if m.get("reenviado_por") else ""
    contenido.append({
        "type": "text",
        "text": (
            f"De: {m['remitente']}\n"
            f"{reenvio}"
            f"Para (buzón SELEC): {m['buzon']}\n"
            f"Recibido: {m.get('receivedDateTime', '')}\n"
            f"Asunto: {m.get('subject') or ''}\n\n"
            f"{cuerpo}"
        ),
    })

    respuesta = _cliente_ia.messages.create(
        model=MODELO,
        max_tokens=4000,
        system=[{"type": "text", "text": INSTRUCCIONES, "cache_control": {"type": "ephemeral"}}],
        tools=[HERRAMIENTA_ANALISIS],
        # "auto": algunos modelos no aceptan forzar la herramienta (tool_choice "tool").
        # El prompt le pide usarla siempre y abajo se valida que lo haya hecho.
        tool_choice={"type": "auto"},
        messages=[{"role": "user", "content": contenido}],
    )
    for bloque in respuesta.content:
        if bloque.type == "tool_use" and bloque.name == "registrar_analisis":
            return bloque.input

    texto = "".join(getattr(b, "text", "") for b in respuesta.content)[:200]
    raise RuntimeError(f"El modelo no devolvió el análisis estructurado. Respuesta: {texto!r}")


# =========================================================
# PROCESO PRINCIPAL
# =========================================================

def procesar_correo(m: dict, dry_run: bool) -> dict:
    asunto = m.get("subject") or ""
    cuerpo = m.get("cuerpo") or leer_cuerpo(m["buzon"], m["id"])
    pdfs = leer_pdfs(m["buzon"], m["id"]) if m.get("hasAttachments") else []
    analisis = analizar(m, cuerpo, pdfs)

    licitacion = None
    if not dry_run:
        # 1) Crear la Licitación en Zoho Creator (no detiene el proceso si falla).
        #    Va antes de guardar en Analytics para registrar el resultado en la misma fila.
        #    No hay riesgo de duplicar: crear_licitacion revisa si ya existe por ID de proceso.
        if os.getenv("CREAR_LICITACIONES", "off").lower() == "on":
            try:
                from agente.licitaciones import crear_licitacion
                licitacion = crear_licitacion(m, analisis)
            except Exception as e:
                log(f"ERROR creando licitación en Creator: {e}")
                licitacion = {"error": str(e)[:300]}
            log(f"licitación {analisis.get('id_proceso', '')}: {texto_licitacion(licitacion)}")
        # 2) Guardar en Analytics
        guardar_fila(fila_analytics(m, analisis, licitacion))

    log(
        f"{m['buzon']} <- {m['remitente']} | {analisis['tipo']} | "
        f"{analisis.get('empresa_compradora', '')} {analisis.get('id_proceso', '')} | "
        f"cierre={analisis.get('fecha_cierre', '')} | {len(analisis.get('items', []))} ítems | "
        f"urgente={'sí' if analisis.get('urgente') else 'no'}"
    )
    return {
        "buzon": m["buzon"],
        "remitente": m["remitente"],
        "asunto": asunto,
        "recibido": m.get("receivedDateTime"),
        "analisis": analisis,
        "licitacion": licitacion,
    }


def ejecutar(horas: int = 24, dry_run: bool = False, limite: int = 10) -> dict:
    buzones = _lista_env("CORREO_BUZONES")
    if not buzones:
        return {"error": "CORREO_BUZONES está vacío"}
    if not _lista_env("CORREO_REMITENTES"):
        return {"error": "CORREO_REMITENTES está vacío"}

    pendientes = []
    errores_buzon = {}
    for buzon in buzones:
        try:
            pendientes += listar_pendientes(buzon, horas)
        except Exception as e:
            log(f"ERROR leyendo {buzon}: {e}")
            errores_buzon[buzon] = str(e)[:300]
    if len(errores_buzon) == len(buzones):
        return {"error": "No se pudo leer ningún buzón", "buzones": errores_buzon}
    # Quitar los que ya están en Analytics. Si la consulta falla, no se procesa
    # nada en esta corrida, para no duplicar filas ni gastar tokens de más.
    try:
        ya = ids_ya_analizados([m["internetMessageId"] for m in pendientes])
    except Exception as e:
        log(f"ERROR consultando Analytics: {e}")
        return {"error": f"No se pudo consultar Analytics: {e}"}

    pendientes = [m for m in pendientes if m["internetMessageId"] not in ya][:limite]
    log(f"{len(pendientes)} correos nuevos en {len(buzones)} buzones (dry_run={dry_run})")

    resultados = [r for r in (_procesar_una_vez(m, dry_run) for m in pendientes) if r]

    respuesta = {"procesados": len(resultados), "resultados": resultados}
    if errores_buzon:
        respuesta["errores_buzon"] = errores_buzon
    return respuesta


_en_proceso: set[str] = set()
_candado = threading.Lock()


def _procesar_una_vez(m: dict, dry_run: bool) -> dict | None:
    """
    Procesa un correo evitando que dos ejecuciones simultáneas (notificación en
    tiempo real + revisión periódica) lo analicen al mismo tiempo.
    """
    clave = m["internetMessageId"]
    with _candado:
        if clave in _en_proceso:
            return None
        _en_proceso.add(clave)
    try:
        return procesar_correo(m, dry_run)
    except Exception as e:
        log(f"ERROR en {m['buzon']} {m.get('subject')!r}: {e}")
        if not dry_run:
            try:
                # Se guarda como "error" para no reintentar en bucle (y no gastar tokens)
                guardar_fila(fila_analytics(m, {"tipo": "error", "resumen": str(e)[:250]}))
            except Exception:
                pass
        return {"buzon": m["buzon"], "asunto": m.get("subject"), "error": str(e)}
    finally:
        with _candado:
            _en_proceso.discard(clave)


# =========================================================
# TIEMPO REAL: NOTIFICACIONES DE MICROSOFT GRAPH
# =========================================================
#
# Graph avisa a /graph/notificaciones cada vez que llega un correo al Inbox.
# La suscripción dura como máximo ~7 días, por eso /cron/suscripciones la
# renueva (se programa una vez al día). La revisión periódica de /cron/correos
# queda como respaldo por si se pierde alguna notificación.

DIAS_SUSCRIPCION = 3


def procesar_notificacion(buzon: str, mensaje_id: str) -> None:
    """Se llama en segundo plano por cada correo nuevo notificado por Graph."""
    try:
        m = _graph("GET", f"/users/{buzon}/messages/{mensaje_id}", params={"$select": CAMPOS_MENSAJE})
        if not preparar_mensaje(m, buzon):
            return
        if ids_ya_analizados([m["internetMessageId"]]):
            return
        log(f"tiempo real: correo nuevo de {m['remitente']} en {buzon}")
        _procesar_una_vez(m, dry_run=False)
    except Exception as e:
        log(f"ERROR procesando notificación {buzon}/{mensaje_id[:20]}...: {e}")


def asegurar_suscripciones(url_publica: str) -> dict:
    """Crea o renueva la suscripción de cada buzón. Idempotente."""
    client_state = os.environ["CORREO_GRAPH_CLIENT_STATE"]
    expira = (datetime.now(timezone.utc) + timedelta(days=DIAS_SUSCRIPCION)).strftime("%Y-%m-%dT%H:%M:%SZ")
    existentes = (_graph("GET", "/subscriptions") or {}).get("value", [])

    resultado = {}
    for buzon in _lista_env("CORREO_BUZONES"):
        url = f"{url_publica.rstrip('/')}/graph/notificaciones?buzon={buzon}"
        recurso = f"users/{buzon}/mailFolders('inbox')/messages"
        actual = next(
            (s for s in existentes
             if s.get("notificationUrl") == url and s.get("resource", "").lower() == recurso.lower()),
            None,
        )
        if actual:
            _graph("PATCH", f"/subscriptions/{actual['id']}", json={"expirationDateTime": expira})
            resultado[buzon] = f"renovada hasta {expira}"
        else:
            # Al crearla, Graph llama a la URL con ?validationToken=... y espera
            # recibir el token de vuelta: el servidor tiene que estar publicado.
            _graph("POST", "/subscriptions", json={
                "changeType": "created",
                "notificationUrl": url,
                "resource": recurso,
                "expirationDateTime": expira,
                "clientState": client_state,
            })
            resultado[buzon] = f"creada hasta {expira}"
        log(f"suscripción {buzon}: {resultado[buzon]}")
    return resultado