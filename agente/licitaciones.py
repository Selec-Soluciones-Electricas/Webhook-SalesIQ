"""
Crea la Licitación en Zoho Creator a partir de un correo ya analizado.

Reglas (definidas con el equipo):
  - Solo invitaciones / solicitudes de cotización, del rubro de SELEC y vigentes.
  - Una sola licitación por ID de proceso (va en el Nombre de Trato: "LIC-9643 - Empresa").
  - Cliente: el que coincida en Creator; si no, el cliente "Por Definir".
  - Contacto CRM: siempre el contacto "Por Definir".
  - Asignado a / Propietario: Joaquin Gonzalez.  Cantidad: 1.  Productos: GENERICO.
    (Así se activa la cadena: análisis → identificación de producto → proveedores.)

Variables de entorno:
  CREAR_LICITACIONES=on
  CREATOR_CLIENT_ID, CREATOR_CLIENT_SECRET, CREATOR_REFRESH_TOKEN
      (scopes: ZohoCreator.form.CREATE, ZohoCreator.report.READ)
  CREATOR_OWNER=selecspa  CREATOR_APP=selec
  CREATOR_FORM_LICITACION=Licitaci_n  CREATOR_REPORT_LICITACION=Licitaci_n_Report
  CREATOR_REPORT_CLIENTES=Clientes_Report
  CREATOR_CLIENTE_POR_DEFINIR_ID (opcional) ID del cliente "Por Definir"; si no está, se busca por nombre
  CRM_CONTACTO_POR_DEFINIR_ID    ID del contacto "Por Definir" en Zoho CRM
  LICITACION_ASIGNADO=Joaquin Gonzalez
  GEN_ID=4710567000001934003
"""

import os
import re
import time
import unicodedata
from datetime import datetime, timedelta

from agente.correo import CHILE_TZ, _pedir, log

TIPOS_QUE_CREAN = {"invitacion_licitacion", "solicitud_cotizacion"}

# Plataforma detectada -> opción de "Tipo Cliente" (Portal) en Creator
PORTALES = {"wherex": "Wherex", "senegocia": "Senegocia", "ariba": "Codelco", "codelco": "Codelco"}

MESES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
SUFIJOS = r"\b(ltda|limitada|spa|s\.?a\.?|s\.?p\.?a\.?|eirl|y cia|cia|chile)\b"

_token = {"valor": None, "expira": 0.0}


# =========================================================
# CREATOR
# =========================================================

def _env(nombre, defecto=None):
    valor = os.getenv(nombre, defecto)
    if valor in (None, ""):
        raise RuntimeError(f"Falta la variable {nombre}")
    return valor


def _access_token():
    if _token["valor"] and time.time() < _token["expira"] - 60:
        return _token["valor"]
    resp = _pedir(
        "POST",
        "https://accounts.zoho.com/oauth/v2/token",
        params={
            "grant_type": "refresh_token",
            "client_id": _env("CREATOR_CLIENT_ID"),
            "client_secret": _env("CREATOR_CLIENT_SECRET"),
            "refresh_token": _env("CREATOR_REFRESH_TOKEN"),
        },
    )
    datos = resp.json()
    if "access_token" not in datos:
        raise RuntimeError(f"Zoho OAuth (Creator): {datos.get('error', resp.status_code)}")
    _token["valor"] = datos["access_token"]
    _token["expira"] = time.time() + int(datos.get("expires_in", 3600))
    return _token["valor"]


def _creator(metodo, ruta, params=None, json=None):
    url = (f"https://www.zohoapis.com/creator/v2.1/data/"
           f"{os.getenv('CREATOR_OWNER', 'selecspa')}/{os.getenv('CREATOR_APP', 'selec')}/{ruta}")
    if metodo == "GET":
        params = {"field_config": "all", "max_records": 200, **(params or {})}
    resp = _pedir(metodo, url, headers={"Authorization": f"Zoho-oauthtoken {_access_token()}"},
                  params=params, json=json)
    try:
        cuerpo = resp.json()
    except ValueError:
        cuerpo = {"raw": resp.text[:300]}
    return resp.status_code, cuerpo


def _esc(v):
    return v.replace("\\", "\\\\").replace('"', '\\"')


# =========================================================
# UTILIDADES
# =========================================================

def _normalizar(nombre):
    n = unicodedata.normalize("NFKD", nombre or "")
    n = "".join(c for c in n if not unicodedata.combining(c)).lower()
    n = re.sub(SUFIJOS, " ", n)
    return re.sub(r"[^a-z0-9]", "", n)


def _portal(plataforma, remitente):
    texto = f"{plataforma} {remitente}".lower()
    for clave, valor in PORTALES.items():
        if clave in texto:
            return valor
    return "Industrias"


def _fecha_creator(fecha_txt):
    """'27-10-2026 16:00' -> datetime. None si no se puede leer."""
    m = re.search(r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})(?:\s+(\d{1,2}):(\d{2}))?", fecha_txt or "")
    if not m:
        return None
    dia, mes, anio = int(m.group(1)), int(m.group(2)), int(m.group(3))
    hora, minuto = int(m.group(4) or 0), int(m.group(5) or 0)
    try:
        dt = datetime(anio, mes, dia, hora, minuto)
    except ValueError:
        return None
    return dt


def _texto_fecha(dt):
    """datetime -> '27-Oct-2026 16:00' (formato de la app)."""
    return f"{dt.day:02d}-{MESES[dt.month - 1]}-{dt.year} {dt.hour:02d}:{dt.minute:02d}"


# =========================================================
# BÚSQUEDAS
# =========================================================

def licitacion_existente(id_proceso):
    status, datos = _creator("GET", f"report/{os.getenv('CREATOR_REPORT_LICITACION', 'Licitaci_n_Report')}",
                             params={"criteria": f'(Nombre_de_Trato.contains("{_esc(id_proceso)}"))'})
    if status == 200:
        for f in datos.get("data") or []:
            # contains puede traer "LIC-96430": se exige el ID completo seguido de un separador
            if re.search(rf"(^|\s){re.escape(id_proceso)}(\s|$|-)", f.get("Nombre_de_Trato") or ""):
                return f.get("ID")
    return None


def buscar_cliente(empresa):
    clave = _normalizar(empresa)
    palabra = next((w for w in re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ0-9]{3,}", empresa or "")
                    if not re.fullmatch(SUFIJOS, w.lower())), "")
    if clave and palabra:
        status, datos = _creator("GET", f"report/{os.getenv('CREATOR_REPORT_CLIENTES', 'Clientes_Report')}",
                                 params={"criteria": f'(Nombre_de_Cuenta.contains("{_esc(palabra)}"))'})
        if status == 200:
            for f in datos.get("data") or []:
                existente = _normalizar(f.get("Nombre_de_Cuenta") or "")
                if existente and (existente == clave or existente in clave or clave in existente):
                    return f["ID"], f.get("Nombre_de_Cuenta")
    return cliente_por_definir(), "Por Definir"


_por_definir = {"id": None}


def cliente_por_definir():
    """ID del cliente "Por Definir": de la variable o buscándolo una vez por nombre."""
    if os.getenv("CREATOR_CLIENTE_POR_DEFINIR_ID"):
        return os.environ["CREATOR_CLIENTE_POR_DEFINIR_ID"]
    if not _por_definir["id"]:
        status, datos = _creator("GET", f"report/{os.getenv('CREATOR_REPORT_CLIENTES', 'Clientes_Report')}",
                                 params={"criteria": '(Nombre_de_Cuenta == "Por Definir")'})
        filas = (datos.get("data") or []) if status == 200 else []
        if not filas:
            raise RuntimeError('No se encontró el cliente "Por Definir" en Creator')
        _por_definir["id"] = filas[0]["ID"]
    return _por_definir["id"]


# =========================================================
# CREACIÓN
# =========================================================

def crear_licitacion(m: dict, analisis: dict) -> dict:
    tipo = analisis.get("tipo")
    id_proceso = (analisis.get("id_proceso") or "").strip()

    if tipo not in TIPOS_QUE_CREAN:
        return {"omitida": f"tipo {tipo}"}
    if not analisis.get("relevante_selec"):
        return {"omitida": f"fuera del rubro: {analisis.get('motivo_relevancia', '')}"}
    if not id_proceso:
        return {"omitida": "sin ID de proceso"}

    cierre = _fecha_creator(analisis.get("fecha_cierre"))
    ahora = datetime.now(CHILE_TZ).replace(tzinfo=None)
    if cierre and cierre < ahora:
        return {"omitida": f"cerrada el {analisis.get('fecha_cierre')}"}

    existente = licitacion_existente(id_proceso)
    if existente:
        return {"omitida": "ya existe", "id": existente}

    empresa = (analisis.get("empresa_compradora") or "").strip()
    cliente_id, cliente_nombre = buscar_cliente(empresa)

    nota_fecha = ""
    if not cierre:
        cierre = (ahora + timedelta(days=3)).replace(hour=12, minute=0, second=0, microsecond=0)
        nota_fecha = "\n⚠ El correo no indica fecha de cierre: se puso una provisoria (+3 días). Verificar en la plataforma."

    productos = []
    for it in analisis.get("items") or []:
        descripcion = " ".join(x for x in [it.get("descripcion"), f"(SKU comprador {it['codigo']})" if it.get("codigo") else ""] if x)
        fila = {
            "Codigo_Producto": _env("GEN_ID", "4710567000001934003"),
            "Descripcion": descripcion[:1000] or "Sin descripción",
            "Cantidadsub": 1,
        }
        if it.get("numero_parte"):
            fila["Numero_de_parte"] = it["numero_parte"][:250]
        if it.get("marca"):
            fila["Marca"] = it["marca"][:250]
        productos.append(fila)
    if not productos:
        return {"omitida": "sin productos"}

    asignado = os.getenv("LICITACION_ASIGNADO", "Joaquin Gonzalez")
    plataforma = analisis.get("plataforma") or ""
    notas = (
        f"Creada automáticamente desde correo de {plataforma or m.get('remitente')} ({m.get('remitente')}).\n"
        f"Proceso: {id_proceso} | Comprador: {empresa or 'no indicado'} | Cierre: {analisis.get('fecha_cierre') or 'no indicado'}\n\n"
        f"{analisis.get('resumen', '')}\n\nAcción sugerida: {analisis.get('accion_sugerida', '')}"
        f"{nota_fecha}"
        + ("" if cliente_nombre != "Por Definir" else f"\n⚠ Cliente '{empresa}' no encontrado en Creator: asignado a 'Por Definir'.")
    )

    datos = {
        "Propietario_de_negocio": asignado,
        "Asignado_a": asignado,
        "Portal": _portal(plataforma, m.get("remitente", "")),
        "Nombre_de_Trato": f"{id_proceso} - {empresa or 'Comprador por definir'}"[:250],
        "Clientes": cliente_id,
        "Contactos_CRM": _env("CRM_CONTACTO_POR_DEFINIR_ID"),
        "fecha_limite_oferta": _texto_fecha(cierre),
        "Fase": "Pendiente por cotizar",
        "Probabilidad": 10,
        "Importe": 1,
        "Fuente_de_Posible_cliente": "Portales",
        "Notas": notas[:5000],
        "Listado_de_productos": productos,
    }

    status, resp = _creator("POST", f"form/{os.getenv('CREATOR_FORM_LICITACION', 'Licitaci_n')}",
                            json={"data": datos})
    if status in (200, 201) and resp.get("code") == 3000:
        lic_id = (resp.get("data") or {}).get("ID")
        log(f"licitación creada en Creator: {datos['Nombre_de_Trato']} (ID {lic_id}, cliente {cliente_nombre})")
        return {"creada": True, "id": lic_id, "cliente": cliente_nombre}
    raise RuntimeError(f"Creator {status}: {str(resp)[:400]}")