"""Diagnostico manual: autenticar y leer solo la cotizacion 26608 de Analytics."""
import sys
sys.dont_write_bytecode = True
import csv
import io
import json
import os
from pathlib import Path
import re

WORKSPACE = "2611904000000269050"
VISTA = "2611904000000269129"
NUMERO = "26608"
CAMPO_NUMERO = "Numero Cotizaci\u00f3n"
CAMPOS = ["Id", CAMPO_NUMERO, "Fase de Presupuesto", "Nombre de Cuenta", "Nombre de Trato"]
URL = f"https://analyticsapi.zoho.com/restapi/v2/workspaces/{WORKSPACE}/views/{VISTA}/data"
CLAVES = ("ANALYTICS_CLIENT_ID", "ANALYTICS_CLIENT_SECRET", "ANALYTICS_REFRESH_TOKEN", "ANALYTICS_ORG_ID")


def codigo_error(respuesta):
    try:
        cuerpo = respuesta.json()
        if not isinstance(cuerpo, dict):
            return "no_disponible"
        detalle = cuerpo.get("data")
        detalle = detalle if isinstance(detalle, dict) else {}
        codigo = cuerpo.get("errorCode", cuerpo.get("code", cuerpo.get("error", detalle.get("errorCode"))))
        if isinstance(codigo, (str, int)) and re.fullmatch(r"[A-Za-z0-9_]{1,80}", str(codigo)):
            return str(codigo)
    except Exception:
        pass
    return "no_disponible"


def interpretar_csv(contenido):
    try:
        texto = contenido.decode("utf-8-sig")
        lector = csv.DictReader(io.StringIO(texto), strict=True)
        if lector.fieldnames is None or any(c not in lector.fieldnames for c in CAMPOS):
            return {"estado": "respuesta_invalida"}
        filas = list(lector)
        if any(None in f or any(f.get(c) is None for c in CAMPOS) for f in filas):
            return {"estado": "respuesta_invalida"}
    except (UnicodeError, csv.Error):
        return {"estado": "respuesta_invalida"}
    if any(f[CAMPO_NUMERO] != NUMERO for f in filas):
        return {"estado": "filtro_no_confirmado"}
    if not filas:
        return {"estado": "no_encontrada"}
    if len(filas) != 1:
        return {"estado": "ambigua"}
    fila = filas[0]
    if not re.fullmatch(r"[0-9]{1,64}", fila["Id"]):
        return {"estado": "respuesta_invalida"}
    return {
        "estado": "encontrada", "coincidencias_exactas": 1,
        "estado_registrado": fila["Fase de Presupuesto"] or "Sin dato",
        "cuenta_con_id": bool(re.fullmatch(r"[0-9]{1,64}", fila["Nombre de Cuenta"])),
        "negocio_con_id": bool(re.fullmatch(r"[0-9]{1,64}", fila["Nombre de Trato"])),
    }


def verificar(cliente, valores):
    if not all(isinstance(valores.get(k), str) and valores[k].strip() for k in CLAVES):
        return {"estado": "configuracion_incompleta"}
    if not re.fullmatch(r"[0-9]{1,64}", valores["ANALYTICS_ORG_ID"]):
        return {"estado": "organizacion_invalida"}
    try:
        auth = cliente.post(
            "https://accounts.zoho.com/oauth/v2/token",
            data={"grant_type": "refresh_token", "client_id": valores[CLAVES[0]],
                  "client_secret": valores[CLAVES[1]], "refresh_token": valores[CLAVES[2]]},
            timeout=15, allow_redirects=False,
        )
        print("HTTP autenticacion:", auth.status_code)
        if auth.status_code != 200:
            return {"estado": "error_autenticacion", "codigo": codigo_error(auth)}
        cuerpo = auth.json()
        token = cuerpo.get("access_token") if isinstance(cuerpo, dict) else None
        if not isinstance(token, str) or not token.strip():
            return {"estado": "error_autenticacion", "codigo": codigo_error(auth)}
        configuracion = {
            "responseFormat": "csv", "includeHeader": True,
            "criteria": f'"Cotizaciones"."{CAMPO_NUMERO}"=\'{NUMERO}\'',
            "selectedColumns": CAMPOS,
        }
        with cliente.get(
            URL,
            headers={"Authorization": f"Zoho-oauthtoken {token}", "ZANALYTICS-ORGID": valores["ANALYTICS_ORG_ID"]},
            params={"CONFIG": json.dumps(configuracion)},
            timeout=20, allow_redirects=False, stream=True,
        ) as respuesta:
            print("HTTP lectura Analytics:", respuesta.status_code)
            if respuesta.status_code != 200:
                return {"estado": "error_lectura", "codigo": codigo_error(respuesta)}
            contenido = bytearray()
            for bloque in respuesta.iter_content(chunk_size=8192):
                contenido.extend(bloque)
                if len(contenido) > 262144:
                    return {"estado": "respuesta_demasiado_grande"}
            if bytes(contenido).lstrip().startswith(b"{"):
                return {"estado": "respuesta_no_csv"}
            return interpretar_csv(bytes(contenido))
    except Exception:
        return {"estado": "error_conexion_o_respuesta"}


def main():
    print("=== SOFIA: COTIZACION EN ANALYTICS ===")
    print("Numero solicitado:", NUMERO)
    try:
        from dotenv import dotenv_values
        import requests
        ruta = Path.home() / "OneDrive/Desktop/Webhook-SalesIQ/.env"
        if not ruta.is_file():
            print("[DETENIDO] No se encontro la configuracion local")
            return 1
        archivo = dotenv_values(ruta)
        valores = {k: os.environ.get(k, archivo.get(k)) for k in CLAVES}
    except Exception:
        print("[DETENIDO] No se pudo cargar la configuracion o las dependencias")
        return 1
    resultado = verificar(requests, valores)
    for clave, valor in resultado.items():
        print(f"{clave}: {valor}")
    print("Lectura de tabla; no confirma recepcion de correos ni identidad del llamante.")
    print("VERIFICACION FINALIZADA")
    return 0 if resultado["estado"] == "encontrada" else 1


if __name__ == "__main__":
    raise SystemExit(main())
