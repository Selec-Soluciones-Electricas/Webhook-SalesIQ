"""
Crea la Licitación en Zoho Creator a partir de un correo ya analizado.

Reglas (definidas con el equipo):
  - Solo invitaciones / solicitudes de cotización, del rubro de SELEC y vigentes.
  - Nombre de Trato y control de duplicados por tipo (ver "NOMBRE DE TRATO POR TIPO"):
      Codelco / Wherex / Senegocia -> "LIC-<número de licitación>" (ej. LIC-6001102591, LIC-4674)
      Industrias (Komatsu, ENAMI, TGN, Corrupac) -> lo que solicitan, breve (ej. "Cables y terminales"),
      sin Numero de Licitacion.
  - Cuenta: Codelco -> siempre el cliente CODELCO (CREATOR_CLIENTE_CODELCO).
  - Contacto: Codelco -> el comprador del "De:" del correo; Senegocia/Wherex -> "Cliente <portal>";
    Industrias -> la persona que firma. Si no se encuentra: "Por Definir".
  - Cliente: el que coincida en Creator; si no, el cliente "Por Definir".
  - Contacto CRM: portales → el contacto del portal si está configurado (ej. Wherex → "Cliente Wherex").
    Clientes directos (Komatsu, ENAMI, ...) → la persona que firma el correo: se busca por correo en
    CRM y, si no existe, se crea (CREAR_CONTACTOS_CRM=off lo evita). Si no, el contacto "Por Definir".
  - Cliente: el de Creator más parecido al nombre de la empresa (no el primero que coincida).
  - Numero de Licitacion: Wherex/Senegocia → número del ID de proceso (LIC-4674 → 4674).
    Codelco (SAP Ariba) → número del evento (6001102591_SA01_... → 6001102591), no el Doc.
    Si no existe en el formulario de números, se crea.
  - Notas: los productos solicitados, uno por línea, y al final el link que abre el proceso
    en la plataforma (el botón "Más detalles aquí" / "Click Here" del correo).
  - Propietario: LICITACION_PROPIETARIO (ej. "Agente IA").  Asignado a: por tipo de portal, con
    cupo diario de 60 productos por persona (ver "ASIGNACIÓN POR TIPO"); sin
    ASIGNACION_POR_TIPO=on queda LICITACION_ASIGNADO.  Cantidad: 1.  Productos: GENERICO.
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
  CORREO_ADJUNTAR_EML  remitentes cuyo correo se adjunta como .eml en el campo "Archivos" de la
      Licitación (por defecto global.komatsu,enami.cl,corrupac.cl,tgn.cl). Vacío = no adjunta.
  CREATOR_CAMPO_ARCHIVOS=Archivos   EML_MAX_MB=5
      Si el correo pesa más de EML_MAX_MB, se adjunta una versión sin los adjuntos; si aun así
      pesa más, no se adjunta. En ningún caso se deja de crear la licitación.
      Requiere el scope ZohoCreator.report.CREATE en el token de Creator. La subida usa
      skip_workflow=["form_workflow"]: sin eso, el "Al validar" de Licitación la rechaza.
  LICITACION_ASIGNADO=Luis Hurtado      (campo "Asignado a": quien trabaja la licitación)
  LICITACION_PROPIETARIO=Agente IA      (opcional, campo "Propietario de negocio": el alias del agente,
      para medir sus licitaciones. Tiene que existir como opción en Creator. Sin la variable,
      el propietario es el mismo que LICITACION_ASIGNADO)
  ASIGNACION_POR_TIPO=on  ASIGNACION_INICIALES  ASIGNACION_MAX=60  ASIGNACION_REGLAS (ver abajo)
  LUGAR_ENTREGA_DEFECTO=Santiago
  GEN_ID=4710567000001934003
"""

import html
import os
import re
import time
import unicodedata
from datetime import datetime, timedelta
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from urllib.parse import quote


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
    """
    ID de la licitación que ya tiene este ID de proceso en el Nombre de Trato, o None.

    El reporte Licitaci_n_Report no devuelve el campo Nombre_de_Trato por la API,
    así que la coincidencia exacta se resuelve en el criterio: el ID seguido de un
    espacio o un guion ("LIC-4681 - Walmart..."), para no confundir LIC-4681 con LIC-46810.

    Si Creator responde con error, se lanza la excepción: es mejor no crear (y avisar)
    que crear una licitación duplicada por no haber podido revisar.
    """
    id_esc = _esc(id_proceso)
    criterio = (f'(Nombre_de_Trato.contains("{id_esc} ") || Nombre_de_Trato.contains("{id_esc}-")'
                f' || Nombre_de_Trato == "{id_esc}")')
    status, datos = _creator("GET", f"report/{os.getenv('CREATOR_REPORT_LICITACION', 'Licitaci_n_Report')}",
                             params={"criteria": criterio})
    if datos.get("code") in (3100, 9280):  # "No records found": no hay coincidencias
        return None
    if status != 200 or datos.get("code") not in (None, 3000):
        raise RuntimeError(f"no se pudo revisar duplicados en Creator ({status}): {str(datos)[:300]}")
    for f in datos.get("data") or []:
        nombre = f.get("Nombre_de_Trato")
        # Si el reporte llegara a incluir el campo, se valida además el ID completo
        if nombre is None or re.search(rf"(^|\s){re.escape(id_proceso)}(\s|$|-)", nombre):
            return f.get("ID")
    return None


def diagnostico_busqueda(id_proceso):
    """Resultado de la búsqueda de duplicados para un ID de proceso (para revisar el control)."""
    reporte = os.getenv('CREATOR_REPORT_LICITACION', 'Licitaci_n_Report')
    try:
        encontrado = licitacion_existente(id_proceso)
        return {"reporte": reporte, "id_proceso": id_proceso,
                "existe": bool(encontrado), "id_licitacion": encontrado}
    except Exception as e:
        return {"reporte": reporte, "id_proceso": id_proceso, "error": str(e)[:400]}


def _parecido(a, b):
    """0 a 1: 1 si son iguales; si uno contiene al otro, largo del menor / largo del mayor."""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return min(len(a), len(b)) / max(len(a), len(b))
    return 0.0


def buscar_cliente(empresa):
    """
    Cliente de Creator más parecido al nombre de la empresa compradora.
    Antes se tomaba el primero que contuviera el nombre: "Komatsu Cummins Chile Ltda."
    quedaba como "KOMATSU CHILE S.A" aunque existiera "Komatsu Cummins". Ahora se comparan
    todos los candidatos y gana el más parecido (igual > más largo en común).
    """
    clave = _normalizar(empresa)
    palabras = [w for w in re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ0-9]{3,}", empresa or "")
                if not re.fullmatch(SUFIJOS, w.lower())]
    if clave and palabras:
        candidatos = {}
        for palabra in palabras[:2]:  # las 2 primeras palabras: "Komatsu", "Cummins"
            status, datos = _creator("GET", f"report/{os.getenv('CREATOR_REPORT_CLIENTES', 'Clientes_Report')}",
                                     params={"criteria": f'(Nombre_de_Cuenta.contains("{_esc(palabra)}"))'})
            if status == 200:
                for f in datos.get("data") or []:
                    candidatos[f["ID"]] = f.get("Nombre_de_Cuenta") or ""
        puntajes = sorted(((_parecido(clave, _normalizar(n)), n, i) for i, n in candidatos.items()), reverse=True)
        if puntajes and puntajes[0][0] > 0:
            mejor = puntajes[0]
            if len(puntajes) > 1:
                log(f"cliente '{empresa}': " + ", ".join(f"{n} ({p:.2f})" for p, n, _ in puntajes[:4]))
            return mejor[2], mejor[1]
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


def _crm(metodo, ruta, **kwargs):
    """Llamada a Zoho CRM con las credenciales del proyecto (ZOHO_CLIENT_ID / ZOHO_REFRESH_TOKEN)."""
    from services.zoho_service import get_access_token
    token = get_access_token()
    if not token:
        raise RuntimeError("sin token de Zoho CRM")
    resp = _pedir(metodo, f"https://www.zohoapis.com/crm/v8/{ruta}",
                  headers={"Authorization": f"Zoho-oauthtoken {token}"}, **kwargs)
    if resp.status_code == 204:
        return 204, {}
    try:
        return resp.status_code, resp.json()
    except ValueError:
        return resp.status_code, {"raw": resp.text[:200]}


def _cuenta_crm(empresa):
    """ID de la cuenta de CRM más parecida al nombre de la empresa, o None."""
    clave = _normalizar(empresa)
    palabra = next((w for w in re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ0-9]{3,}", empresa or "")
                    if not re.fullmatch(SUFIJOS, w.lower())), "")
    if not palabra:
        return None
    status, datos = _crm("GET", "Accounts/search", params={"word": palabra, "per_page": 50})
    puntajes = sorted(((_parecido(clave, _normalizar(a.get("Account_Name"))), a["id"])
                       for a in (datos.get("data") or []) if a.get("id")), reverse=True) if status == 200 else []
    return puntajes[0][1] if puntajes and puntajes[0][0] > 0 else None


def contacto_comprador(analisis, remitente, empresa):
    """
    Contacto de CRM de la persona que firma el correo (clientes directos: Komatsu, ENAMI, ...).
    Lo busca por correo en CRM; si no existe, lo crea (con su cuenta si se encuentra).
    Devuelve (id, nombre) o (None, motivo).
    """
    correo = (analisis.get("contacto_correo") or remitente or "").strip().lower()
    if not re.fullmatch(r"[\w.+-]+@[\w-]+(\.[\w-]+)+", correo):
        return None, "sin correo del comprador"
    nombre = " ".join((analisis.get("contacto_nombre") or "").split())
    if not nombre:  # v.gonzalez@... -> "V Gonzalez"
        nombre = " ".join(p.capitalize() for p in re.split(r"[._-]+", correo.split("@")[0]) if p)

    status, datos = _crm("GET", "Contacts/search", params={"email": correo})
    if status == 200 and (datos.get("data") or []):
        c = datos["data"][0]
        return c["id"], (c.get("Full_Name") or nombre)
    if status not in (200, 204):
        return None, f"no se pudo buscar el contacto en CRM ({status}): {str(datos)[:150]}"
    if os.getenv("CREAR_CONTACTOS_CRM", "on").lower() == "off":
        return None, f"el contacto {correo} no existe en CRM"

    # Nombres chilenos: los 2 últimos son apellidos ("Vanessa Esther | Gonzalez Leon")
    partes = nombre.split()
    corte = len(partes) - 2 if len(partes) >= 4 else 1  # 3 palabras: "Vanessa | Gonzalez Leon"
    registro = {
        "First_Name": " ".join(partes[:corte])[:40] if len(partes) > 1 else "",
        "Last_Name": (" ".join(partes[corte:]) if len(partes) > 1 else (partes[0] if partes else correo.split("@")[0]))[:80],
        "Email": correo,
        "Description": "Creado por el agente de correos (licitaciones).",
    }
    telefono = str(analisis.get("contacto_telefono") or "").strip()
    if telefono and "000000" not in re.sub(r"\D", "", telefono):  # firmas con "+56 2 0000 0000"
        registro["Phone"] = telefono[:30]
    if analisis.get("contacto_cargo"):
        registro["Title"] = str(analisis["contacto_cargo"])[:100]
    try:
        cuenta = _cuenta_crm(empresa)
        if cuenta:
            registro["Account_Name"] = {"id": cuenta}
    except Exception as e:
        log(f"no se pudo buscar la cuenta '{empresa}' en CRM: {e}")
    status, resp = _crm("POST", "Contacts", json={"data": [registro]})
    fila = (resp.get("data") or [{}])[0] if isinstance(resp.get("data"), list) else {}
    if status in (200, 201) and fila.get("code") == "SUCCESS":
        log(f"contacto creado en CRM: {nombre} <{correo}>")
        return fila["details"]["id"], nombre
    return None, f"no se pudo crear el contacto {correo} en CRM ({status}): {str(resp)[:150]}"


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


def notas_productos(items, link=""):
    """
    Productos solicitados, uno por línea, y al final el link del proceso.
    El campo Notas es texto enriquecido: salto = <br>, link = <a>.
    """
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
    salto = os.getenv("NOTAS_SALTO_LINEA", "<br>")
    texto = salto.join(lineas)
    if link:
        # Creator descarta el href si trae caracteres como "*" (ej. el hash de Senegocia):
        # en el href van codificados (%2A); el texto visible queda igual.
        href = html.escape(quote(link, safe=":/?#[]@!$&'()+,;=%-._~"), quote=True)
        texto += f'{salto}{salto}Link del proceso: <a href="{href}" target="_blank">{html.escape(link)}</a>'
    return texto


# =========================================================
# CORREO ORIGINAL ADJUNTO (.eml) PARA CLIENTES DIRECTOS
# =========================================================

EML_DEFECTO = "global.komatsu,enami.cl,corrupac.cl,tgn.cl"


def adjunta_eml(remitente: str) -> bool:
    """¿Este remitente está en CORREO_ADJUNTAR_EML (Komatsu, ENAMI, Corrupac, TGN)?"""
    dominio = (remitente or "").lower().split("@")[-1]
    for regla in os.getenv("CORREO_ADJUNTAR_EML", EML_DEFECTO).lower().split(","):
        regla = regla.strip().lstrip("@")
        if regla and ("@" in regla and remitente.lower() == regla
                      or dominio == regla or dominio.endswith("." + regla)):
            return True
    return False


def eml_sin_adjuntos(mime: bytes) -> bytes:
    """Versión liviana del correo: mismos encabezados y texto, sin los archivos adjuntos."""
    original = BytesParser(policy=policy.default).parsebytes(mime)
    nombres = [p.get_filename() or "sin nombre" for p in original.iter_attachments()]
    liviano = EmailMessage()
    for encabezado in ("From", "To", "Cc", "Date", "Subject", "Message-ID"):
        if original[encabezado]:
            liviano[encabezado] = str(original[encabezado])
    aviso = ("[Correo adjuntado sin sus archivos por superar el tamaño máximo. "
             f"Adjuntos originales: {', '.join(nombres) or 'ninguno'}]")
    texto = original.get_body(preferencelist=("plain",))
    html_cuerpo = original.get_body(preferencelist=("html",))
    liviano.set_content(aviso + "\n\n" + (texto.get_content() if texto else ""))
    if html_cuerpo:
        liviano.add_alternative(f"<p><i>{html.escape(aviso)}</i></p>" + html_cuerpo.get_content(), subtype="html")
    return liviano.as_bytes()


def _subir_archivo(lic_id, nombre: str, contenido: bytes, tipo: str):
    """Sube un archivo al campo "Archivos" de la Licitación. Devuelve (ok, detalle)."""
    url = (f"https://www.zohoapis.com/creator/v2.1/data/{os.getenv('CREATOR_OWNER', 'selecspa')}/"
           f"{os.getenv('CREATOR_APP', 'selec')}/report/{os.getenv('CREATOR_REPORT_LICITACION', 'Licitaci_n_Report')}/"
           f"{lic_id}/{os.getenv('CREATOR_CAMPO_ARCHIVOS', 'Archivos')}/upload")
    # skip_workflow: la validación "Al validar" del formulario Licitación también se aplica a la
    # subida de archivos y responde error 3700 (aunque el archivo igual queda guardado).
    # Se salta solo para esta subida.
    resp = _pedir("POST", url, intentos=1, headers={"Authorization": f"Zoho-oauthtoken {_access_token()}"},
                  params={"skip_workflow": '["form_workflow"]'},
                  files={"file": (nombre, contenido, tipo)})
    try:
        cuerpo = resp.json()
    except ValueError:
        cuerpo = {"raw": resp.text[:200]}
    return resp.status_code == 200 and cuerpo.get("code") == 3000, f"Creator {resp.status_code} {str(cuerpo)[:200]}"


def adjuntar_correo(m: dict, lic_id, id_proceso: str) -> str:
    """
    Descarga el correo (.eml) y lo sube al campo "Archivos" de la Licitación.
    Un solo intento: si Creator responde error, el archivo puede haber quedado guardado igual
    (pasaba con la validación del formulario), así que reintentar lo duplicaría.
    Devuelve un texto con el resultado; nunca lanza excepción (la licitación ya está creada).
    """
    from agente.correo import leer_mime

    maximo = float(os.getenv("EML_MAX_MB", "5")) * 1024 * 1024
    try:
        mime = leer_mime(m["buzon"], m["id"])
        nombre = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{id_proceso or 'correo'}").strip("_")[:80] + ".eml"
        if len(mime) > maximo:
            mime = eml_sin_adjuntos(mime)
            nombre = nombre[:-4] + "_sin_adjuntos.eml"
            if len(mime) > maximo:
                return f"correo .eml no adjuntado: pesa {len(mime) / 1048576:.1f} MB aun sin adjuntos"
        ok, detalle = _subir_archivo(lic_id, nombre, mime, "message/rfc822")
        if ok:
            return f"correo adjuntado como {nombre} ({len(mime) / 1048576:.2f} MB)"
        return f"correo .eml no adjuntado (revisar si quedó en Archivos): {detalle}"
    except Exception as e:
        return f"correo .eml no adjuntado: {type(e).__name__}: {str(e)[:200]}"


# =========================================================
# NOMBRE DE TRATO POR TIPO
# =========================================================

PORTALES_CON_NUMERO = ("Codelco", "Wherex", "Senegocia")
REF_NOTAS = "Ref. correo"


def resumen_productos(analisis, items):
    """Lo que solicitan, en pocas palabras (ej. "Cables y terminales"), para Industrias."""
    texto = " ".join((analisis.get("resumen_productos") or "").split()).strip(" .")
    if not texto:  # respaldo: las primeras palabras de los primeros productos
        texto = ", ".join(" ".join((it.get("descripcion") or "").split()[:3]) for it in items[:2]).strip(", ")
    texto = texto or "Solicitud de cotización"
    return (texto[0].upper() + texto[1:])[:120]


def nombre_trato(portal, id_proceso, analisis, items, m):
    """
    (nombre, claves para buscar duplicados).
      Codelco / Wherex / Senegocia: "LIC-<número de licitación>".
      Industrias: lo que solicitan (ej. "Cables y terminales").
    Las claves incluyen el formato anterior ("<ID> - Empresa") para no duplicar las ya creadas.
    """
    if portal in PORTALES_CON_NUMERO:
        numero = extraer_numero(id_proceso, portal, (analisis.get("nombre_proceso"), m.get("subject"), id_proceso))
        if numero:
            nombre = f"LIC-{numero}"
            return nombre, list(dict.fromkeys([nombre, id_proceso]))
        empresa = (analisis.get("empresa_compradora") or "").strip()
        return f"{id_proceso} - {empresa or 'Comprador por definir'}"[:250], [id_proceso]
    return resumen_productos(analisis, items), [id_proceso]


def industria_existente(id_proceso):
    """Industrias: el nombre no lleva el ID, se busca la referencia que queda al final de las Notas."""
    criterio = f'(Notas.contains("{_esc(REF_NOTAS)}: {_esc(id_proceso)}"))'
    try:
        status, datos = _creator("GET", f"report/{os.getenv('CREATOR_REPORT_LICITACION', 'Licitaci_n_Report')}",
                                 params={"criteria": criterio})
    except Exception as e:
        log(f"no se pudo revisar duplicados de {id_proceso} por Notas: {e}")
        return None
    if status == 200 and datos.get("code") in (None, 3000):
        filas = datos.get("data") or []
        return filas[0].get("ID") if filas else None
    if datos.get("code") not in (3100, 9280):
        log(f"no se pudo revisar duplicados de {id_proceso} por Notas ({status}): {str(datos)[:200]}")
    return None


def cliente_codelco():
    """Codelco: la cuenta es siempre CODELCO (el cliente de Creator más parecido a ese nombre)."""
    return buscar_cliente(os.getenv("CREATOR_CLIENTE_CODELCO", "CODELCO"))


CORREOS_GENERICOS = re.compile(r"(ariba\.com|no-?reply|noreply|notificacion|notification|mailer)", re.I)


def contacto_codelco(analisis, m):
    """
    Codelco: el comprador que aparece en el "De:" del correo (o el que detecta el análisis).
      1. Por correo (si no es un correo genérico de Ariba): se busca en CRM y, si no está, se crea.
      2. Si solo hay nombre: se busca por nombre en CRM.
    Devuelve (id, nombre) o (None, motivo) -> "Por Definir".
    """
    datos = dict(analisis)
    correo = (analisis.get("contacto_correo") or "").strip().lower()
    if not correo or CORREOS_GENERICOS.search(correo):
        remitente = (m.get("remitente") or "").lower()
        correo = "" if CORREOS_GENERICOS.search(remitente) else remitente
    datos["contacto_correo"] = correo
    nombre = " ".join((analisis.get("contacto_nombre") or m.get("remitente_nombre") or "").split())
    # "Codelco - Juan Pérez" / "Juan Pérez via SAP Business Network" -> "Juan Pérez"
    nombre = re.sub(r"(?i)\b(via|vía)\b.*$|^\s*codelco\b[\s\-–:|]*|\bsap\b.*$", "", nombre).strip(" -–|:")
    datos["contacto_nombre"] = nombre

    if correo:
        return contacto_comprador(datos, correo, "CODELCO")
    if len(nombre.split()) >= 2:
        status, resp = _crm("GET", "Contacts/search", params={"word": nombre, "per_page": 10})
        clave = _normalizar(nombre)
        for c in (resp.get("data") or []) if status == 200 else []:
            if _normalizar(c.get("Full_Name")) == clave:
                return c["id"], c.get("Full_Name")
        return None, f"el comprador '{nombre}' no está en CRM y el correo no trae su dirección"
    return None, "el correo no trae el nombre ni el correo del comprador"


_contactos_portal = {}


def contacto_portal(portal):
    """
    Contacto genérico del portal ("Cliente Senegocia", "Cliente Wherex"):
    CRM_CONTACTO_<PORTAL>_ID o, si no está, se busca una vez en CRM por el nombre
    (CRM_CONTACTO_<PORTAL>_NOMBRE, por defecto "Cliente <Portal>"). Si no: "Por Definir".
    """
    clave = re.sub(r"[^A-Z0-9]", "_", (portal or "").upper())
    if os.getenv(f"CRM_CONTACTO_{clave}_ID"):
        return os.environ[f"CRM_CONTACTO_{clave}_ID"], "variable"
    if portal not in _contactos_portal:
        nombre = os.getenv(f"CRM_CONTACTO_{clave}_NOMBRE", f"Cliente {portal}")
        encontrado = None
        try:
            status, resp = _crm("GET", "Contacts/search", params={"word": nombre, "per_page": 20})
            for c in (resp.get("data") or []) if status == 200 else []:
                if _normalizar(c.get("Full_Name")) == _normalizar(nombre):
                    encontrado = c["id"]
                    break
        except Exception as e:
            log(f"no se pudo buscar el contacto '{nombre}' en CRM: {e}")
            return _env("CRM_CONTACTO_POR_DEFINIR_ID"), f"error buscando '{nombre}'"
        _contactos_portal[portal] = encontrado
        log(f"contacto del portal {portal}: " + (f"'{nombre}' ({encontrado})" if encontrado else
                                                  f"'{nombre}' no existe en CRM, se usa 'Por Definir'"))
    return (_contactos_portal[portal] or _env("CRM_CONTACTO_POR_DEFINIR_ID")), "crm"


# =========================================================
# ASIGNACIÓN POR TIPO (Portal) CON CUPO DIARIO DE 60 PRODUCTOS
# =========================================================
#
# Regla definida con el equipo (pizarra). Cada licitación va COMPLETA a una sola persona:
#   Codelco    -> MR hasta 60 productos en el día; luego rotando por licitación: PC, JP, JG;
#                 si todos llegan a 60: CS
#   Wherex     -> JG; luego PC, JP; si todos llegan a 60: CS
#   Senegocia  -> PC; luego JP, JG, MR
#   Industrias -> MR; luego JG, JP, PC   (Komatsu, TGN, Corrupac, ENAMI)
#
# - El cupo es por persona y por día (hora Chile), sumando TODOS los portales: a las 00:00
#   todos parten de 0. Ej.: 41 en Wherex + 19 en Senegocia = 60, ya no recibe más ese día.
# - Una persona recibe licitaciones mientras lleve menos de 60 productos ese día.
#   La licitación que la hace pasar de 60 igual se le asigna completa (ej. lleva 50 y llega
#   una de 20: queda con 70) y desde ahí ya no recibe más ese día.
# - "Rotando por licitación": entre los que tienen cupo, la recibe el que lleva menos
#   licitaciones hoy (empate: el orden de la regla), así queda PC, JP, JG, PC...
# - Solo cuentan las licitaciones que creó el agente (Propietario = LICITACION_PROPIETARIO).
#
# Variables:
#   ASIGNACION_POR_TIPO=on   activa la regla (sin ella, todo va a LICITACION_ASIGNADO)
#   ASIGNACION_INICIALES     quién es cada inicial, ej. "MR=Maria Rengifo,PC=Patricio Cifuentes,..."
#                            (para pruebas: "MR=Maikel Meriño,PC=Deivys Almario,JP=Elian Barra,...")
#   ASIGNACION_MAX=60        productos por persona y por día (todos los portales)
#   ASIGNACION_REGLAS        (opcional) JSON para cambiar la regla sin tocar el código

INICIALES_DEFECTO = ("MR=Maria Rengifo,PC=Patricio Cifuentes,JP=Juan Puerta,"
                     "JG=Joaquin Gonzalez,CS=Carolina Salazar")
REGLAS_DEFECTO = {
    "Codelco": {"primero": "MR", "resto": ["PC", "JP", "JG"], "respaldo": ["CS"]},
    "Wherex": {"primero": "JG", "resto": ["PC", "JP"], "respaldo": ["CS"]},
    "Senegocia": {"primero": "PC", "resto": ["JP", "JG", "MR"], "respaldo": []},
    "Industrias": {"primero": "MR", "resto": ["JG", "JP", "PC"], "respaldo": []},
}

# Respaldo en memoria por si Creator no responde: {fecha: {persona: {...}}}
_carga_memoria = {}


def _iniciales():
    texto = os.getenv("ASIGNACION_INICIALES") or INICIALES_DEFECTO
    return {k.strip().upper(): v.strip() for k, v in
            (par.split("=", 1) for par in texto.split(",") if "=" in par)}


def _reglas():
    if os.getenv("ASIGNACION_REGLAS"):
        import json
        try:
            return json.loads(os.environ["ASIGNACION_REGLAS"])
        except ValueError:
            log("ASIGNACION_REGLAS no es un JSON válido: se usa la regla por defecto")
    return REGLAS_DEFECTO


def _valor(campo):
    """Creator devuelve a veces el texto y a veces {"display_value": ...}."""
    if isinstance(campo, dict):
        return campo.get("display_value") or campo.get("zc_display_value") or ""
    return campo or ""


def carga_del_dia(portal=None):
    """
    Productos y licitaciones que el agente asignó HOY, por persona, sumando todos los portales
    (el parámetro portal se mantiene solo por compatibilidad):
    {"Maikel Meriño": {"productos": 45, "licitaciones": 2}, ...}, más la fuente usada.

    Se lee de Creator (sobrevive a reinicios y despliegues). Si Creator falla o el reporte
    no trae los campos necesarios, se usa lo que este proceso lleva contado en memoria.
    """
    hoy = datetime.now(CHILE_TZ)
    clave = hoy.date().isoformat()
    propietario = os.getenv("LICITACION_PROPIETARIO") or os.getenv("LICITACION_ASIGNADO", "Luis Hurtado")
    desde = f"{hoy.day:02d}-{MESES[hoy.month - 1]}-{hoy.year} 00:00:00"
    criterio = f'(Propietario_de_negocio == "{_esc(propietario)}" && Added_Time >= "{desde}")'
    try:
        status, datos = _creator("GET", f"report/{os.getenv('CREATOR_REPORT_LICITACION', 'Licitaci_n_Report')}",
                                 params={"criteria": criterio})
        if datos.get("code") in (3100, 9280):
            return {}, "creator"
        if status != 200 or datos.get("code") not in (None, 3000):
            raise RuntimeError(f"Creator {status}: {str(datos)[:200]}")
        carga = {}
        for f in datos.get("data") or []:
            if "Asignado_a" not in f or "Listado_de_productos" not in f:
                raise RuntimeError("el reporte no trae Asignado_a o Listado_de_productos")
            persona = _valor(f.get("Asignado_a"))
            c = carga.setdefault(persona, {"productos": 0, "licitaciones": 0})
            c["productos"] += len(f.get("Listado_de_productos") or [])
            c["licitaciones"] += 1
        return carga, "creator"
    except Exception as e:
        log(f"carga del día desde Creator falló, se usa la memoria: {str(e)[:200]}")
        return _carga_memoria.get(clave, {}), "memoria"


def _sumar_carga(portal, persona, productos):
    clave = datetime.now(CHILE_TZ).date().isoformat()
    for k in list(_carga_memoria):
        if k != clave:
            del _carga_memoria[k]  # días anteriores
    c = _carga_memoria.setdefault(clave, {}).setdefault(persona, {"productos": 0, "licitaciones": 0})
    c["productos"] += productos
    c["licitaciones"] += 1


def elegir_asignado(portal, carga=None):
    """
    A quién se asigna la próxima licitación de este portal (completa, sin dividir).
    Devuelve (persona, motivo).
    """
    defecto = os.getenv("LICITACION_ASIGNADO", "Luis Hurtado")
    if os.getenv("ASIGNACION_POR_TIPO", "off").lower() != "on":
        return defecto, "ASIGNACION_POR_TIPO desactivada"
    regla = _reglas().get(portal)
    if not regla:
        return defecto, f"sin regla para el portal {portal}"
    if carga is None:
        carga, _ = carga_del_dia(portal)

    nombres = _iniciales()
    def nombre(ini):
        return nombres.get(str(ini).upper(), ini)

    maximo = int(os.getenv("ASIGNACION_MAX", "60"))
    def productos(p):
        return (carga.get(p) or {}).get("productos", 0)
    def licitaciones(p):
        return (carga.get(p) or {}).get("licitaciones", 0)

    primero = nombre(regla["primero"])
    resto = list(dict.fromkeys(nombre(x) for x in regla.get("resto") or []))
    respaldo = list(dict.fromkeys(nombre(x) for x in regla.get("respaldo") or []))

    if productos(primero) < maximo:
        return primero, f"primero de {portal} ({productos(primero)}/{maximo} hoy en total)"

    def rotar(grupo):
        # El que lleva menos licitaciones hoy; empate -> orden de la regla
        return min(grupo, key=lambda p: (licitaciones(p), grupo.index(p)))

    con_cupo = [p for p in resto if productos(p) < maximo]
    if con_cupo:
        p = rotar(con_cupo)
        return p, f"{primero} completó {maximo}: rotación ({productos(p)}/{maximo} hoy en total)"
    con_cupo = [p for p in respaldo if productos(p) < maximo]
    if con_cupo:
        p = rotar(con_cupo)
        return p, f"todos completaron {maximo}: respaldo ({productos(p)}/{maximo} hoy en total)"
    # Todos llenos y sin respaldo con cupo: se sigue rotando entre los demás
    grupo = resto or [primero]
    p = rotar(grupo)
    return p, f"todos completaron {maximo}: se sigue rotando"


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

    empresa = (analisis.get("empresa_compradora") or "").strip()
    portal = _portal(analisis.get("plataforma") or "", m.get("remitente", ""))

    # Ítems que SELEC no cotiza (rodamientos, retenes, correas): no van a la licitación
    excluidos = set(analisis.get("items_excluidos") or [])
    items = [it for i, it in enumerate(analisis.get("items") or []) if i not in excluidos]

    # Nombre de Trato según el tipo, y control de duplicados con ese nombre
    nombre, claves = nombre_trato(portal, id_proceso, analisis, items, m)
    for clave in claves:
        existente = licitacion_existente(clave)
        if existente:
            return {"omitida": "ya existe", "id": existente}
    if portal == "Industrias":
        existente = industria_existente(id_proceso)
        if existente:
            return {"omitida": "ya existe", "id": existente}

    if portal == "Codelco":
        cliente_id, cliente_nombre = cliente_codelco()
    else:
        cliente_id, cliente_nombre = buscar_cliente(empresa)

    avisos = []
    if cliente_nombre == "Por Definir":
        avisos.append(f"cliente '{empresa}' no encontrado en Creator: se asignó 'Por Definir'")
    if not cierre:
        cierre = (ahora + timedelta(days=3)).replace(hour=12, minute=0, second=0, microsecond=0)
        avisos.append("el correo no indica fecha de cierre: se puso una provisoria (+3 días)")

    if excluidos:
        avisos.append(f"{len(excluidos)} ítem(s) no se incluyeron (rodamientos, retenes o correas)")

    productos = []
    for it in items:
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
    if not m.get("link_proceso"):
        avisos.append("no se encontró el link del proceso en el correo")
    if lugar_defecto:
        avisos.append(f"lugar de entrega '{analisis.get('lugar_entrega') or 'no indicado'}' no está en la lista: "
                      f"se puso '{lugar}'")

    # Asignado a: por tipo de portal, con cupo diario de 60 productos por persona
    asignado, motivo_asignado = elegir_asignado(portal)
    log(f"{id_proceso}: asignado a {asignado} ({len(productos)} productos; {motivo_asignado})")
    # Propietario: un alias del agente (ej. "Agente IA") para medir lo que crea el agente.
    # Sin la variable, queda la persona de LICITACION_ASIGNADO (comportamiento anterior).
    propietario = os.getenv("LICITACION_PROPIETARIO") or os.getenv("LICITACION_ASIGNADO", "Luis Hurtado")

    datos = {
        "Propietario_de_negocio": propietario,
        "Asignado_a": asignado,
        "Portal": portal,
        "Nombre_de_Trato": nombre[:250],
        "Clientes": cliente_id,
        "Contactos_CRM": _env("CRM_CONTACTO_POR_DEFINIR_ID"),  # se reemplaza abajo según el tipo
        "fecha_limite_oferta": _texto_fecha(cierre),
        "Fase": "Pendiente por cotizar",
        "Probabilidad": 10,
        "Importe": 1,
        "Fuente_de_Posible_cliente": "Portales",
        "Lugar_de_entrega": lugar,
        "Notas": notas_productos(items, m.get("link_proceso", "")),
        "Listado_de_productos": productos,
    }

    # Industrias: referencia del correo al final de las Notas (el nombre no lleva el ID)
    if portal == "Industrias":
        datos["Notas"] += f"{os.getenv('NOTAS_SALTO_LINEA', '<br>')}{REF_NOTAS}: {html.escape(id_proceso)}"

    # Contacto según el tipo
    if portal in ("Industrias", "Codelco"):
        try:
            if portal == "Codelco":
                contacto_id, contacto_nombre = contacto_codelco(analisis, m)
            else:  # la persona que firma el correo
                contacto_id, contacto_nombre = contacto_comprador(analisis, m.get("remitente", ""), empresa)
        except Exception as e:
            contacto_id, contacto_nombre = None, f"{type(e).__name__}: {str(e)[:150]}"
        if contacto_id:
            datos["Contactos_CRM"] = contacto_id
            log(f"{id_proceso}: contacto {contacto_nombre}")
        else:
            avisos.append(f"contacto 'Por Definir': {contacto_nombre}")
    else:  # Senegocia / Wherex: "Cliente Senegocia", "Cliente Wherex"
        datos["Contactos_CRM"], _ = contacto_portal(portal)

    # Numero de Licitacion (no aplica a Industrias): si falla, se crea igual y queda el aviso
    if portal != "Industrias":
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
        _sumar_carga(portal, asignado, len(productos))
        log(f"licitación creada en Creator: {datos['Nombre_de_Trato']} (ID {lic_id}, cliente {cliente_nombre}, "
            f"asignado {asignado}, {len(productos)} productos)")
        # Clientes directos (Komatsu, ENAMI, Corrupac, TGN): se adjunta el correo original (.eml)
        if lic_id and adjunta_eml(m.get("remitente", "")):
            resultado_eml = adjuntar_correo(m, lic_id, id_proceso)
            if resultado_eml.startswith("correo adjuntado"):
                log(f"{id_proceso}: {resultado_eml}")
            else:
                avisos.append(resultado_eml)
        for aviso in avisos:
            log(f"⚠ {id_proceso}: {aviso}")
        return {"creada": True, "id": lic_id, "cliente": cliente_nombre, "asignado": asignado,
                "avisos": avisos}
    raise RuntimeError(f"Creator {status}: {str(resp)[:400]}")