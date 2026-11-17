"""SELEC: persistencia controlada de intentos WhatsApp en una tabla AISLADA.

Uso:
    python -B SELEC_metricas_guardado_seguro.py --dry-run
    python -B SELEC_metricas_guardado_seguro.py --write-one --confirm-view-id 2611904000006539040

Por defecto NO escribe nada. La modalidad write-one es para un primer ensayo
supervisado: como máximo intenta insertar UNA fila, con comprobación por Attempt ID
antes y después. No es un upsert atómico; NO ejecutar simultáneamente ni programar
hasta asegurar una estrategia de bloqueo/constraint y probar la recuperación.

No clasifica intentos como incompletos o errores, ni modifica negocios CRM,
ni cambia tablas o gráficos históricos.
"""

import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

from services.analytics_service import get_analytics_access_token

WORKSPACE_ID = "2611904000000269050"
VIEW_ID = "2611904000006539040"
BASE_URL = (
    "https://analyticsapi.zoho.com/restapi/v2"
    f"/workspaces/{WORKSPACE_ID}/views/{VIEW_ID}"
)
COLUMNAS = {
    "Attempt ID",
    "Conversation ID",
    "Fecha",
    "Estado",
    "ID Negocio",
    "Origen",
    "Categoria torta",
    "Detalle resultado",
    "Fecha actualizacion",
}
FORMATO_FECHA = "dd-MMM-yyyy HH:mm:ss"


def validar_registro(fila):
    if not isinstance(fila, dict) or set(fila) != COLUMNAS:
        raise RuntimeError("Registro con columnas inesperadas")
    attempt_id = str(fila["Attempt ID"] or "").strip()
    cid = str(fila["Conversation ID"] or "").strip()
    if not re.fullmatch(r"[0-9]{4,30}", cid):
        raise RuntimeError("Conversation ID sin formato esperado")
    if not re.fullmatch(r"SIQ-[0-9]{4,30}-[A-Za-z0-9_-]{1,128}", attempt_id):
        raise RuntimeError("Attempt ID sin formato esperado")
    if not attempt_id.startswith(f"SIQ-{cid}-"):
        raise RuntimeError("Attempt ID no corresponde a Conversation ID")
    if fila["Estado"] != "INICIADA" or fila["Origen"] != "whatsapp":
        raise RuntimeError("Estado u origen inesperado")
    if fila["ID Negocio"] or fila["Categoria torta"]:
        raise RuntimeError("No se aceptan resultados comerciales inferidos")
    for campo in ("Fecha", "Fecha actualizacion"):
        valor = str(fila[campo] or "")
        if not re.fullmatch(r"\d{2}-[A-Z][a-z]{2}-\d{4} \d{2}:\d{2}:\d{2}", valor):
            raise RuntimeError(f"Fecha incompatible en {campo}")
        # Meses en ingles generados por seguimiento_cotizaciones.
        datetime.strptime(valor, "%d-%b-%Y %H:%M:%S")
    return attempt_id


def abrir_sesion():
    # En local carga .env; en Render utiliza las variables configuradas.
    load_dotenv(dotenv_path=".env")
    org_id = os.getenv("ANALYTICS_ORG_ID")
    token = get_analytics_access_token()
    if not token or not org_id:
        raise RuntimeError("No hay acceso autorizado a Analytics")
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Zoho-oauthtoken {token}",
        "ZANALYTICS-ORGID": org_id,
    })
    return s


def consultar_intento(sesion, attempt_id):
    # Los identificadores ya fueron validados; aun asi escapamos la comilla.
    seguro = attempt_id.replace("'", "''")
    config = {
        "responseFormat": "json",
        "selectedColumns": ["Attempt ID", "Estado", "Origen", "ID Negocio"],
        "criteria": f'"Attempt ID"=\'{seguro}\'',
        "keyValueFormat": True,
    }
    resp = sesion.get(BASE_URL + "/data", params={"CONFIG": json.dumps(config)}, timeout=25)
    if resp.status_code != 200:
        raise RuntimeError(f"Lectura Analytics HTTP {resp.status_code}")
    try:
        cuerpo = resp.json()
    except ValueError as exc:
        raise RuntimeError("Analytics no devolvio JSON") from exc
    if not isinstance(cuerpo, dict) or cuerpo.get("status") not in (None, "success"):
        raise RuntimeError("Analytics reporto error durante lectura")
    filas = cuerpo.get("data")
    if not isinstance(filas, list):
        raise RuntimeError("Analytics no devolvio lista de filas")
    for fila in filas:
        if not isinstance(fila, dict) or str(fila.get("Attempt ID") or "").strip() != attempt_id:
            raise RuntimeError("Analytics devolvio una fila inesperada")
    if len(filas) > 1:
        raise RuntimeError("Ya hay registros duplicados para el mismo Attempt ID")
    return filas


def insertar_un_registro(sesion, registro):
    """POST solo con autorizacion explicita de CLI, nunca desde dry-run."""
    attempt_id = validar_registro(registro)
    if consultar_intento(sesion, attempt_id):
        return "YA_EXISTE"
    resp = sesion.post(
        BASE_URL + "/rows",
        params={"CONFIG": json.dumps({
            "columns": registro,
            "dateFormat": FORMATO_FECHA,
        })},
        timeout=25,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Insercion no confirmada HTTP {resp.status_code}; verificar en UI antes de reintentar")
    try:
        cuerpo = resp.json()
    except ValueError as exc:
        raise RuntimeError("Respuesta no JSON tras escritura; verificar antes de reintentar") from exc
    if not isinstance(cuerpo, dict) or cuerpo.get("status") != "success":
        raise RuntimeError("Analytics no confirmo la insercion; verificar antes de reintentar")
    data = cuerpo.get("data")
    if not isinstance(data, dict) or data.get("invalidColumns") not in ({}, None):
        raise RuntimeError("Analytics informo columnas invalidas; verificar antes de reintentar")
    filas = consultar_intento(sesion, attempt_id)
    if len(filas) != 1:
        raise RuntimeError("No se pudo verificar una unica fila; no reintentar a ciegas")
    if str(filas[0].get("Estado") or "") != "INICIADA":
        raise RuntimeError("Estado guardado inesperado; revisar en Analytics")
    return "CREADO"


def main():
    from SELEC_analytics_simulacion_whatsapp import ejecutar
    parser = argparse.ArgumentParser()
    opciones = parser.add_mutually_exclusive_group(required=True)
    opciones.add_argument("--dry-run", action="store_true", help="Solo consulta, cero escrituras")
    opciones.add_argument("--write-one", action="store_true", help="Inserta como maximo una fila")
    parser.add_argument("--confirm-view-id", default="")
    args = parser.parse_args()
    if args.write_one and args.confirm_view_id != VIEW_ID:
        raise SystemExit("ESCRITURA BLOQUEADA: requiere --confirm-view-id exacto")

    print("=== PASO 24 - PERSISTENCIA SEGURA ===")
    print("Destino: SELEC - Intentos WhatsApp Automaticos")
    print("Modo:", "SOLO LECTURA" if args.dry_run else "ESCRIBIR UNA FILA")
    registros = ejecutar()
    if not isinstance(registros, list):
        raise RuntimeError("El simulador no devolvio los registros")
    por_id = {}
    for registro in registros:
        attempt_id = validar_registro(registro)
        if attempt_id in por_id:
            raise RuntimeError("Intentos duplicados en la preparacion")
        por_id[attempt_id] = registro
    sesion = abrir_sesion()
    ya_existen, nuevos = 0, []
    for attempt_id in sorted(por_id):
        if consultar_intento(sesion, attempt_id):
            ya_existen += 1
        else:
            nuevos.append(por_id[attempt_id])
    print("Registros preparados:", len(por_id))
    print("Existentes en tabla nueva:", ya_existen)
    print("Pendientes de insertar:", len(nuevos))
    if args.dry_run:
        print("Escrituras realizadas: 0")
        print("=== PASO 24 DRY RUN OK ===")
        return
    if not nuevos:
        print("No se insertan filas: todos los intentos ya existen")
        return
    # Deliberadamente nunca se insertan todos en una sola prueba.
    resultado = insertar_un_registro(sesion, nuevos[0])
    print("Resultado de la unica fila:", resultado)
    print("Limite de escrituras ejecutado: maximo 1")
    print("=== PASO 24 WRITE ONE FINALIZADO ===")


if __name__ == "__main__":
    main()
