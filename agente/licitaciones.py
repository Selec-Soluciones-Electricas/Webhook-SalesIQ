"""
Crea la Licitación en Zoho Creator a partir de un correo ya analizado.

Reglas (definidas con el equipo):
  - Solo invitaciones / solicitudes de cotización, del rubro de SELEC y vigentes.
  - Una sola licitación por ID de proceso (va en el Nombre de Trato: "LIC-9643 - Empresa").
  - Cliente: el que coincida en Creator; si no, el cliente "Por Definir".
  - Contacto CRM: el contacto del portal si está configurado (ej. Wherex → "Cliente Wherex");
    si no, el contacto "Por Definir".
  - Numero de Licitacion: Wherex/Senegocia → número del ID de proceso (LIC-4674 → 4674).
    Codelco (SAP Ariba) → número del evento (6001102591_SA01_... → 6001102591), no el Doc.
    Si no existe en el formulario de números, se crea.
  - Notas: solo los productos solicitados, uno por línea.
  - Asignado a / Propietario: Luis Hurtado.  Cantidad: 1.  Productos: GENERICO.
    (Así se activa la cadena: análisis → identificación de producto → proveedores.)

Variables de entorno:
  CREAR_LICITACIONES=on
  CREATOR_CLIENT_ID, CREATOR_CLIENT_SECRET, CREATOR_REFRESH_TOKEN
      (scopes: ZohoCreator.form.CREATE, ZohoCreator.report.READ, ZohoCreator.meta.form.READ)
  CREATOR_OWNER=selecspa  CREATOR_APP=selec
  CREATOR_FORM_LICITACION=Licitaci_n  CREATOR_REPORT_LICITACION=Licitaci_n_Report
  CREATOR_REPORT_CLIENTES=Clientes_Report
  CREATOR_CLIENTE_POR_DEFINIR_ID (opcional) ID del cliente "Por Definir"; si no está, se busca por nombre
  CRM_CONTACTO_POR_DEFINIR_ID    ID del contacto "Por Definir" en Zoho CRM
  CRM_CONTACTO_WHEREX_ID         (opcional) ID del contacto "Cliente Wherex" en Zoho CRM.
      Sirve para cualquier portal: CRM_CONTACTO_SENEGOCIA_ID, CRM_CONTACTO_CODELCO_ID, etc.
  CREATOR_REPORT_NUMERO_LIC=Numeros_Licitaciones_report  (por defecto) reporte de los números
  CREATOR_FORM_NUMERO_LIC  (opcional) se deduce del reporte: Numeros_Licitaciones
  CREATOR_CAMPO_NUMERO_LIC (opcional) se detecta leyendo un registro del reporte
  CREATOR_LOOKUP_NUMERO_LIC      (opcional) link name del lookup en Licitación; si no está,
      se busca por la etiqueta "Numero de Licitacion".
  LICITACION_ASIGNADO=Luis Hurtado
  LUGAR_ENTREGA_DEFECTO=Santiago
  GEN_ID=4710567000001934003
"""

import html
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
    return f"{dt.day:02d}-{MESES[dt.month - 1]}-{dt.year} {dt.hour:02d}:{dt.minute:02d}"


_campos = {"lista": None}


def campos_licitacion():
    """Campos del formulario Licitación (API de metadatos), leídos una sola vez."""
    if _campos["lista"] is None:
        url = (f"https://www.zohoapis.com/creator/v2.1/meta/"
               f"{os.getenv('CREATOR_OWNER', 'selecspa')}/{os.getenv('CREATOR_APP', 'selec')}"
               f"/form/{os.getenv('CREATOR_FORM_LICITACION', 'Licitaci_n')}/fields")
        resp = _pedir("GET", url, headers={"Authorization": f"Zoho-oauthtoken {_access_token()}"})
        if resp.status_code == 200:
            _campos["lista"] = resp.json().get("fields", [])
        else:
            log(f"No se pudieron leer los campos de Licitación: {resp.status_code} {resp.text[:200]}")
            return []
    return _campos["lista"]


def opciones_lugar_entrega():
    for campo in campos_licitacion():
        if campo.get("link_name") == "Lugar_de_entrega":
            return [c.get("value") for c in campo.get("choices") or [] if c.get("value")]
    return []


def elegir_lugar(lugar_correo):
    """Devuelve (opción válida, ¿se usó el valor por defecto?)."""
    defecto = os.getenv("LUGAR_ENTREGA_DEFECTO", "Santiago")
    buscado = _normalizar(lugar_correo)
    if buscado:
        for opcion in opciones_lugar_entrega():
            normal = _normalizar(opcion)
            if normal and (normal == buscado or normal in buscado or buscado in normal):
                return opcion, False
    return defecto, True


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
# CONTACTO, NÚMERO DE LICITACIÓN Y NOTAS
# =========================================================

def contacto_crm(portal):
    """Contacto del portal (CRM_CONTACTO_WHEREX_ID, ...) o, si no hay, el contacto "Por Definir"."""
    clave = re.sub(r"[^A-Z0-9]", "_", (portal or "").upper())
    return os.getenv(f"CRM_CONTACTO_{clave}_ID") or _env("CRM_CONTACTO_POR_DEFINIR_ID")


def campo_lookup_numero():
    """Link name del lookup "Numero de Licitacion" en el formulario Licitación."""
    if os.getenv("CREATOR_LOOKUP_NUMERO_LIC"):
        return os.environ["CREATOR_LOOKUP_NUMERO_LIC"]
    campos = campos_licitacion()
    # La API de metadatos devuelve la etiqueta como "display_name" (según versión, "display_label")
    for campo in campos:
        etiqueta = campo.get("display_name") or campo.get("display_label") or ""
        if _normalizar(etiqueta) == "numerodelicitacion":
            return campo.get("link_name")
    # Respaldo: por el link name (ej. Numero_de_Licitacion, N_mero_de_Licitaci_n)
    for campo in campos:
        nombre = _normalizar(campo.get("link_name"))
        if nombre.startswith("n") and "licit" in nombre and "mero" in nombre:
            return campo.get("link_name")
    log("campos de Licitación: " + ", ".join(
        f"{c.get('link_name')}={c.get('display_name') or c.get('display_label')}" for c in campos))
    return None


_numeros = {"campo": None}


def config_numeros():
    """(formulario, reporte, campo) donde se guardan los números de licitación."""
    report = os.getenv("CREATOR_REPORT_NUMERO_LIC", "Numeros_Licitaciones_report")
    form = os.getenv("CREATOR_FORM_NUMERO_LIC") or re.sub(r"_[Rr]eport$", "", report)
    campo = os.getenv("CREATOR_CAMPO_NUMERO_LIC") or _numeros["campo"]
    if not campo:
        # El formulario tiene un solo campo: se toma el nombre desde un registro existente
        status, datos = _creator("GET", f"report/{report}")
        filas = (datos.get("data") or []) if status == 200 else []
        if filas:
            campo = next((k for k in filas[0] if k != "ID"), None)
        if not campo:
            raise RuntimeError(f"no se pudo detectar el campo del reporte {report}: {str(datos)[:200]}")
        _numeros["campo"] = campo
        log(f"campo de números de licitación detectado: {form}.{campo}")
    return form, report, campo


PATRON_EVENTO_ARIBA = re.compile(r"(?<!\d)(\d{8,})_[A-Za-z]{2}\d{2}")


def extraer_numero(id_proceso, portal="", textos=()):
    """
    Número que va en "Numero de Licitacion".
      Codelco (SAP Ariba): número del evento, ej. "6001102591_SA01_SUM MTTO..." -> 6001102591
                           (el id_proceso suele ser el Doc2453266452, que no sirve aquí).
      Otros portales:      dígitos del ID de proceso, ej. LIC-4674 -> 4674.
    """
    if portal == "Codelco":
        for texto in textos:
            encontrado = PATRON_EVENTO_ARIBA.search(texto or "")
            if encontrado:
                return encontrado.group(1)
    encontrado = re.search(r"\d+", id_proceso or "")
    return encontrado.group() if encontrado else None


def numero_licitacion(id_proceso, portal="", textos=()):
    """
    Devuelve (campo_lookup, ID del registro con el número) o (None, motivo).
    Si el número no existe en Numeros_Licitaciones, se crea.
    """
    lookup = campo_lookup_numero()
    if not lookup:
        return None, "no se encontró el campo 'Numero de Licitacion' en el formulario"

    numero = extraer_numero(id_proceso, portal, textos)
    if not numero:
        return None, f"el ID '{id_proceso}' no tiene número"

    form, report, campo = config_numeros()

    # El campo puede ser numérico o de texto: se prueba con y sin comillas
    for criterio in (f"({campo} == {numero})", f'({campo} == "{numero}")'):
        status, datos = _creator("GET", f"report/{report}", params={"criteria": criterio})
        if status == 200 and datos.get("data"):
            return lookup, datos["data"][0]["ID"]

    status, resp = _creator("POST", f"form/{form}", json={"data": {campo: numero}})
    if status in (200, 201) and resp.get("code") == 3000:
        log(f"número de licitación {numero} creado en {form}")
        return lookup, (resp.get("data") or {}).get("ID")
    return None, f"no se pudo crear el número {numero}: {str(resp)[:300]}"


def notas_productos(items):
    """Productos solicitados, uno por línea (el campo Notas es texto enriquecido: salto = <br>)."""
    lineas = []
    for i, it in enumerate(items or [], 1):
        partes = [it.get("descripcion") or "Sin descripción"]
        if it.get("marca"):
            partes.append(f"Marca: {it['marca']}")
        if it.get("numero_parte"):
            partes.append(f"N° parte: {it['numero_parte']}")
        if it.get("codigo"):
            partes.append(f"SKU: {it['codigo']}")
        cantidad = " ".join(x for x in (it.get("cantidad"), it.get("unidad")) if x)
        if cantidad:
            partes.append(f"Cantidad: {cantidad}")
        lineas.append(html.escape(f"{i}. " + " | ".join(partes)))
    return os.getenv("NOTAS_SALTO_LINEA", "<br>").join(lineas)


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

    avisos = []
    if cliente_nombre == "Por Definir":
        avisos.append(f"cliente '{empresa}' no encontrado en Creator: se asignó 'Por Definir'")
    if not cierre:
        cierre = (ahora + timedelta(days=3)).replace(hour=12, minute=0, second=0, microsecond=0)
        avisos.append("el correo no indica fecha de cierre: se puso una provisoria (+3 días)")

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

    lugar, lugar_defecto = elegir_lugar(analisis.get("lugar_entrega"))
    if lugar_defecto:
        avisos.append(f"lugar de entrega '{analisis.get('lugar_entrega') or 'no indicado'}' no está en la lista: "
                      f"se puso '{lugar}'")

    asignado = os.getenv("LICITACION_ASIGNADO", "Luis Hurtado")
    plataforma = analisis.get("plataforma") or ""
    portal = _portal(plataforma, m.get("remitente", ""))

    datos = {
        "Propietario_de_negocio": asignado,
        "Asignado_a": asignado,
        "Portal": portal,
        "Nombre_de_Trato": f"{id_proceso} - {empresa or 'Comprador por definir'}"[:250],
        "Clientes": cliente_id,
        "Contactos_CRM": contacto_crm(portal),
        "fecha_limite_oferta": _texto_fecha(cierre),
        "Fase": "Pendiente por cotizar",
        "Probabilidad": 10,
        "Importe": 1,
        "Fuente_de_Posible_cliente": "Portales",
        "Lugar_de_entrega": lugar,
        "Notas": notas_productos(analisis.get("items"))[:5000],
        "Listado_de_productos": productos,
    }

    # Numero de Licitacion: si falla, la licitación se crea igual y queda el aviso en el log
    try:
        lookup, valor = numero_licitacion(
            id_proceso, portal,
            (analisis.get("nombre_proceso"), m.get("subject"), id_proceso),
        )
        if lookup:
            datos[lookup] = valor
        else:
            avisos.append(f"Numero de Licitacion sin asignar: {valor}")
    except Exception as e:
        avisos.append(f"Numero de Licitacion sin asignar: {e}")

    status, resp = _creator("POST", f"form/{os.getenv('CREATOR_FORM_LICITACION', 'Licitaci_n')}",
                            json={"data": datos})
    if status in (200, 201) and resp.get("code") == 3000:
        lic_id = (resp.get("data") or {}).get("ID")
        log(f"licitación creada en Creator: {datos['Nombre_de_Trato']} (ID {lic_id}, cliente {cliente_nombre})")
        for aviso in avisos:
            log(f"⚠ {id_proceso}: {aviso}")
        return {"creada": True, "id": lic_id, "cliente": cliente_nombre, "avisos": avisos}
    raise RuntimeError(f"Creator {status}: {str(resp)[:400]}")