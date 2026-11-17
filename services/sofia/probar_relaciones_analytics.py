"""Ejecutor manual para las cuatro tablas autorizadas de Analytics."""
import sys
sys.dont_write_bytecode = True
import argparse
import csv
import io
import json
import os
from pathlib import Path

from .consulta_analytics import COLUMNAS, CAMPO_NUMERO, FalloConsulta, id_valido, consultar_cotizacion_analytics
from .probar_cotizacion_analytics import CLAVES, codigo_error

WORKSPACE = "2611904000000269050"
VISTAS = {"Cotizaciones": "2611904000000269129", "Negocios": "2611904000000269102",
          "Clientes": "2611904000000269101", "Usuarios": "2611904000000269098"}


def autenticar(cliente, valores):
    try:
        r = cliente.post("https://accounts.zoho.com/oauth/v2/token",
                         data={"grant_type": "refresh_token", "client_id": valores[CLAVES[0]],
                               "client_secret": valores[CLAVES[1]], "refresh_token": valores[CLAVES[2]]},
                         timeout=15, allow_redirects=False)
        print("HTTP autenticacion:", r.status_code)
        if r.status_code != 200:
            print("Codigo:", codigo_error(r))
            return None
        cuerpo = r.json()
        token = cuerpo.get("access_token") if isinstance(cuerpo, dict) else None
        return token if isinstance(token, str) and token.strip() else None
    except Exception:
        return None


def crear_lector(cliente, token, org_id):
    if not id_valido(org_id):
        raise ValueError("Organizacion invalida")

    def leer(tabla, campo, valor, columnas):
        if (tabla not in VISTAS or not id_valido(valor) or columnas != COLUMNAS[tabla]
                or campo != (CAMPO_NUMERO if tabla == "Cotizaciones" else "Id")):
            raise FalloConsulta("consulta_no_permitida")
        config = {"responseFormat": "csv", "includeHeader": True,
                  "criteria": f'"{tabla}"."{campo}"=\'{valor}\'', "selectedColumns": columnas}
        url = f"https://analyticsapi.zoho.com/restapi/v2/workspaces/{WORKSPACE}/views/{VISTAS[tabla]}/data"
        with cliente.get(url, headers={"Authorization": "Zoho-oauthtoken " + token, "ZANALYTICS-ORGID": org_id},
                         params={"CONFIG": json.dumps(config)}, timeout=20, allow_redirects=False, stream=True) as r:
            print(f"HTTP {tabla}:", r.status_code)
            if r.status_code != 200:
                print("Codigo:", codigo_error(r))
                raise FalloConsulta("error_acceso" if r.status_code in (401, 403) else "error_servicio")
            contenido = bytearray()
            for bloque in r.iter_content(chunk_size=8192):
                contenido.extend(bloque)
                if len(contenido) > 262144:
                    raise FalloConsulta("respuesta_demasiado_grande")
        try:
            texto = bytes(contenido).decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(texto), strict=True)
            if (reader.fieldnames is None or len(set(reader.fieldnames)) != len(reader.fieldnames)
                    or any(c not in reader.fieldnames for c in columnas)):
                raise FalloConsulta("respuesta_invalida")
            filas = list(reader)
            if any(None in fila for fila in filas):
                raise FalloConsulta("respuesta_invalida")
            return filas
        except (UnicodeError, csv.Error):
            raise FalloConsulta("respuesta_invalida") from None
    return leer


def main():
    parser = argparse.ArgumentParser(description="Consulta interna de Analytics; no escribe registros")
    parser.add_argument("--numero", default="26608")
    args = parser.parse_args()
    numero = args.numero.strip()
    if not id_valido(numero):
        print("[DETENIDO] Numero invalido; no se realizo ninguna conexion")
        return 1
    print("=== SOFIA: CONSULTA COMPLETA EN ANALYTICS ===")
    print("Numero solicitado:", numero)
    try:
        from dotenv import dotenv_values
        import requests
        ruta = Path.home() / "OneDrive/Desktop/Webhook-SalesIQ/.env"
        if not ruta.is_file():
            print("[DETENIDO] No se encontro la configuracion local")
            return 1
        archivo = dotenv_values(ruta)
        valores = {k: os.environ.get(k, archivo.get(k)) for k in CLAVES}
        if not all(isinstance(v, str) and v.strip() for v in valores.values()) or not id_valido(valores["ANALYTICS_ORG_ID"]):
            print("[DETENIDO] Configuracion incompleta o invalida")
            return 1
    except Exception:
        print("[DETENIDO] No se pudo cargar la configuracion o dependencias")
        return 1
    token = autenticar(requests, valores)
    if not token:
        print("[DETENIDO] Autenticacion no disponible; no cambies permisos")
        return 1
    resultado = consultar_cotizacion_analytics(numero, crear_lector(requests, token, valores["ANALYTICS_ORG_ID"]))
    print("\nEstado de consulta:", resultado["estado"])
    datos = resultado["datos_internos"]
    if datos:
        for etiqueta, campo in [("Estado registrado", "estado_registrado"), ("Cliente", "cliente"),
                                ("Ejecutivo provisional", "ejecutivo_provisional"),
                                ("Estado del usuario asignado", "usuario_asignado_estado"),
                                ("Cuenta de negocio coincide", "cuenta_negocio_coincide")]:
            valor = datos[campo]
            print(f"{etiqueta}:", "No disponible" if valor is None else valor)
    for aviso in resultado["avisos"]:
        print("Aviso:", aviso)
    print("Identidad verificada: NO | Autorizado para divulgar: NO")
    print("Ultima sincronizacion: no verificada por esta prueba; frecuencia observada: cada hora.")
    print("Esta consulta no confirma recepcion o envio de correos.")
    print("VERIFICACION FINALIZADA")
    return 0 if resultado["estado"] == "encontrada" else 1


if __name__ == "__main__":
    raise SystemExit(main())
