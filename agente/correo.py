"""
Lectura de correos de remitentes específicos (Microsoft 365 / Graph).

Revisa uno o más buzones y, por cada correo nuevo cuyo remitente ("De")
esté en la lista permitida:
  1. Lee el cuerpo y los PDF adjuntos.
  2. Claude lo analiza y devuelve datos estructurados.
  3. Guarda el resultado en la tabla "Correos Analizados" de Zoho Analytics.
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
"""

import json
import os
import re
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

    resp = requests.post(
        f"https://login.microsoftonline.com/{os.environ['GRAPH_TENANT_ID']}/oauth2/v2.0/token",
        data={
            "grant_type": "client_credentials",
            "client_id": os.environ["GRAPH_CLIENT_ID"],
            "client_secret": os.environ["GRAPH_CLIENT_SECRET"],
            "scope": "https://graph.microsoft.com/.default",
        },
        timeout=15,
    )
    resp.raise_for_status()
    datos = resp.json()
    _token["valor"] = datos["access_token"]
    _token["expira"] = time.time() + int(datos.get("expires_in", 3600))
    return _token["valor"]


def _graph(metodo: str, ruta: str, **kwargs):
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {_access_token()}"
    resp = requests.request(metodo, f"{GRAPH}{ruta}", headers=headers, timeout=30, **kwargs)
    if resp.status_code >= 400:
        raise RuntimeError(f"Graph {metodo} {ruta} -> {resp.status_code}: {resp.text[:300]}")
    return resp.json() if resp.content else None


def listar_pendientes(buzon: str, horas: int) -> list[dict]:
    desde = (datetime.now(timezone.utc) - timedelta(hours=horas)).strftime("%Y-%m-%dT%H:%M:%SZ")
    datos = _graph(
        "GET",
        f"/users/{buzon}/mailFolders/inbox/messages",
        params={
            "$filter": f"receivedDateTime ge {desde}",
            "$orderby": "receivedDateTime desc",
            "$top": "50",
            "$select": "id,internetMessageId,subject,from,receivedDateTime,hasAttachments",
        },
    )

    pendientes = []
    for m in datos.get("value", []):
        remitente = ((m.get("from") or {}).get("emailAddress") or {}).get("address", "")
        if not remitente_permitido(remitente):
            continue
        if PATRON_AUTORESPUESTA.search(m.get("subject") or ""):
            continue
        m["remitente"] = remitente
        m["buzon"] = buzon
        m["internetMessageId"] = m.get("internetMessageId") or m["id"]
        pendientes.append(m)
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


def ids_ya_analizados(ids: list[str]) -> set[str]:
    """Consulta cuáles de estos Message ID ya están en la tabla."""
    if not ids:
        return set()
    base, headers = _analytics()
    lista = ",".join("'" + i.replace("'", "''") + "'" for i in ids)
    config = {
        "responseFormat": "json",
        "criteria": f"\"Message ID\" in ({lista})",
        "selectedColumns": ["Message ID"],
        "keyValueFormat": True,
    }
    resp = requests.get(f"{base}/data", headers=headers, params={"CONFIG": json.dumps(config)}, timeout=20)
    if resp.status_code != 200:
        raise RuntimeError(f"Analytics consulta -> {resp.status_code}: {resp.text[:300]}")
    return {fila.get("Message ID") for fila in (resp.json().get("data") or [])}


def guardar_fila(columnas: dict) -> None:
    base, headers = _analytics()
    config = {"columns": columnas, "dateFormat": "dd-MM-yyyy HH:mm:ss"}
    resp = requests.post(f"{base}/rows", headers=headers, params={"CONFIG": json.dumps(config)}, timeout=20)
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


def fila_analytics(m: dict, analisis: dict) -> dict:
    return {
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
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "codigo": {"type": "string", "description": "SKU o código del comprador"},
                        "descripcion": {"type": "string"},
                        "marca_modelo": {"type": "string"},
                        "cantidad": {"type": "string"},
                        "unidad": {"type": "string"},
                    },
                    "required": ["descripcion"],
                },
            },
            "resumen": {"type": "string", "description": "2 o 3 frases para el ejecutivo"},
            "accion_sugerida": {"type": "string", "description": "Qué debería hacer el ejecutivo, en una frase"},
            "urgente": {"type": "boolean"},
        },
        "required": ["tipo", "id_proceso", "empresa_compradora", "items", "resumen", "accion_sugerida", "urgente"],
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
- El resumen y la acción sugerida van en español neutro, breves y dirigidos al ejecutivo.

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
    contenido.append({
        "type": "text",
        "text": (
            f"De: {m['remitente']}\n"
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
        tool_choice={"type": "tool", "name": "registrar_analisis"},
        messages=[{"role": "user", "content": contenido}],
    )
    return next(b.input for b in respuesta.content if b.type == "tool_use")


# =========================================================
# PROCESO PRINCIPAL
# =========================================================

def procesar_correo(m: dict, dry_run: bool) -> dict:
    asunto = m.get("subject") or ""
    cuerpo = leer_cuerpo(m["buzon"], m["id"])
    pdfs = leer_pdfs(m["buzon"], m["id"]) if m.get("hasAttachments") else []
    analisis = analizar(m, cuerpo, pdfs)

    if not dry_run:
        guardar_fila(fila_analytics(m, analisis))

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
    }


def ejecutar(horas: int = 24, dry_run: bool = False, limite: int = 10) -> dict:
    buzones = _lista_env("CORREO_BUZONES")
    if not buzones:
        return {"error": "CORREO_BUZONES está vacío"}
    if not _lista_env("CORREO_REMITENTES"):
        return {"error": "CORREO_REMITENTES está vacío"}

    pendientes = []
    for buzon in buzones:
        try:
            pendientes += listar_pendientes(buzon, horas)
        except Exception as e:
            log(f"ERROR leyendo {buzon}: {e}")
    # Quitar los que ya están en Analytics. Si la consulta falla, no se procesa
    # nada en esta corrida, para no duplicar filas ni gastar tokens de más.
    try:
        ya = ids_ya_analizados([m["internetMessageId"] for m in pendientes])
    except Exception as e:
        log(f"ERROR consultando Analytics: {e}")
        return {"error": f"No se pudo consultar Analytics: {e}"}

    pendientes = [m for m in pendientes if m["internetMessageId"] not in ya][:limite]
    log(f"{len(pendientes)} correos nuevos en {len(buzones)} buzones (dry_run={dry_run})")

    resultados = []
    for m in pendientes:
        try:
            resultados.append(procesar_correo(m, dry_run))
        except Exception as e:
            log(f"ERROR en {m['buzon']} {m.get('subject')!r}: {e}")
            resultados.append({"buzon": m["buzon"], "asunto": m.get("subject"), "error": str(e)})
            if not dry_run:
                try:
                    # Se guarda como "error" para no reintentar en bucle (y no gastar tokens)
                    guardar_fila(fila_analytics(m, {"tipo": "error", "resumen": str(e)[:500]}))
                except Exception:
                    pass

    return {"procesados": len(resultados), "resultados": resultados}