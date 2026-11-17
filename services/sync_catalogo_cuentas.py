
"""Sincronizacion segura del catalogo de cuentas SELEC."""

import os
import re
import json
from pathlib import Path

import requests
from dotenv import load_dotenv

WORKSPACE_ID = "2611904000000269050"
VIEW_ID = "2611904000006657043"

BASE_ANALYTICS = (
    "https://analyticsapi.zoho.com/restapi/v2"
)


def obtener_cuentas_crm():
    from services.zoho_service import (
        get_access_token,
        CRM_BASE,
    )

    token = get_access_token()

    if not token:
        raise RuntimeError("Autenticacion CRM fallida")

    cuentas = {}
    paginas = 0

    for pagina in range(1, 101):
        respuesta = requests.get(
            CRM_BASE.rstrip("/") + "/Accounts",
            headers={
                "Authorization": "Zoho-oauthtoken " + token
            },
            params={
                "fields": "id,Account_Name",
                "per_page": 200,
                "page": pagina,
            },
            timeout=30,
        )

        if respuesta.status_code == 204:
            return cuentas, paginas

        if respuesta.status_code != 200:
            raise RuntimeError(
                "Error al consultar cuentas CRM"
            )

        cuerpo = respuesta.json()
        registros = cuerpo.get("data", [])

        if not isinstance(registros, list):
            raise RuntimeError(
                "Respuesta CRM inesperada"
            )

        for registro in registros:
            identificador = str(
                registro.get("id") or ""
            ).strip()

            nombre = str(
                registro.get("Account_Name") or ""
            ).strip()

            if (
                not re.fullmatch(
                    r"[0-9]{10,25}", identificador
                )
                or not nombre
            ):
                continue

            if (
                identificador in cuentas
                and cuentas[identificador] != nombre
            ):
                raise RuntimeError(
                    "Conflicto en ID Cuenta CRM"
                )

            cuentas[identificador] = nombre

        paginas += 1

        if cuerpo.get("info", {}).get(
            "more_records"
        ) is False:
            return cuentas, paginas

    raise RuntimeError(
        "Paginacion CRM incompleta"
    )


def obtener_cuentas_analytics():
    from SELEC_metricas_guardado_seguro import (
        abrir_sesion,
    )

    sesion = abrir_sesion()

    try:
        url = (
            f"{BASE_ANALYTICS}/workspaces/"
            f"{WORKSPACE_ID}/views/{VIEW_ID}/data"
        )

        config = {
            "responseFormat": "json",
            "keyValueFormat": True,
            "selectedColumns": [
                "ID Cuenta",
                "Nombre de Cuenta",
            ],
        }

        respuesta = sesion.get(
            url,
            params={
                "CONFIG": json.dumps(config)
            },
            timeout=40,
        )

        if respuesta.status_code != 200:
            raise RuntimeError(
                "Error al consultar catalogo Analytics"
            )

        cuerpo = respuesta.json()
        registros = cuerpo.get("data")

        if (
            cuerpo.get("status") not in
            (None, "success")
            or not isinstance(registros, list)
        ):
            raise RuntimeError(
                "Respuesta Analytics inesperada"
            )

        cuentas = {}

        for fila in registros:
            identificador = str(
                fila.get("ID Cuenta") or ""
            ).strip()

            nombre = str(
                fila.get("Nombre de Cuenta") or ""
            ).strip()

            if identificador in cuentas:
                raise RuntimeError(
                    "ID Cuenta duplicado en Analytics"
                )

            cuentas[identificador] = nombre

        return cuentas

    finally:
        sesion.close()


def preparar_sincronizacion():
    crm, paginas = obtener_cuentas_crm()
    analytics = obtener_cuentas_analytics()

    if not crm or not analytics:
        raise RuntimeError(
            "Catalogo vacio; sincronizacion cancelada"
        )

    nuevas = {
        identificador: nombre
        for identificador, nombre in crm.items()
        if identificador not in analytics
    }

    modificadas = {
        identificador: nombre
        for identificador, nombre in crm.items()
        if identificador in analytics
        and analytics[identificador] != nombre
    }

    iguales = sum(
        1 for identificador, nombre in crm.items()
        if analytics.get(identificador) == nombre
    )

    return {
        "paginas_crm": paginas,
        "cuentas_crm": len(crm),
        "cuentas_analytics": len(analytics),
        "nuevas": nuevas,
        "modificadas": modificadas,
        "sin_cambios": iguales,
    }



def preparar_importacion(plan):
    """Prepara solo las cuentas nuevas o modificadas."""

    import csv
    import io

    nuevas = plan["nuevas"]
    modificadas = plan["modificadas"]

    if set(nuevas) & set(modificadas):
        raise RuntimeError("Cuenta duplicada en cambios")

    cambios = {**nuevas, **modificadas}

    if not cambios:
        return None

    if len(cambios) > 100:
        raise RuntimeError(
            "Mas de 100 cambios; requiere revision"
        )

    salida = io.StringIO(newline="")
    escritor = csv.writer(
        salida, quoting=csv.QUOTE_ALL
    )

    escritor.writerow([
        "ID Cuenta",
        "Nombre de Cuenta",
    ])

    for identificador, nombre in sorted(cambios.items()):
        if (
            not re.fullmatch(r"[0-9]{10,25}", identificador)
            or not isinstance(nombre, str)
            or not nombre.strip()
        ):
            raise RuntimeError("Datos de cuenta invalidos")

        escritor.writerow([
            identificador,
            nombre,
        ])

    config = {
        "importType": "updateadd",
        "fileType": "csv",
        "autoIdentify": True,
        "onError": "abort",
        "matchingColumns": ["ID Cuenta"],
        "selectedColumns": [
            "ID Cuenta",
            "Nombre de Cuenta",
        ],
    }

    return {
        "config": config,
        "archivo": salida.getvalue().encode("utf-8-sig"),
        "cantidad": len(cambios),
    }


def aplicar_cambios(
    plan,
    sesion=None,
    permitir_escritura=False,
):
    """Sincroniza solo si existe autorizacion explicita."""

    paquete = preparar_importacion(plan)

    if paquete is None:
        return {"estado": "SIN_CAMBIOS", "cantidad": 0}

    if not permitir_escritura:
        return {
            "estado": "SIMULACION",
            "cantidad": paquete["cantidad"],
        }

    if os.getenv(
        "SELEC_CATALOGO_CUENTAS_ESCRITURA", "0"
    ) != "1":
        raise RuntimeError("Escritura no habilitada")

    if sesion is None:
        raise RuntimeError("Falta sesion Analytics")

    url = (
        f"{BASE_ANALYTICS}/workspaces/"
        f"{WORKSPACE_ID}/views/{VIEW_ID}/data"
    )

    respuesta = sesion.post(
        url,
        params={
            "CONFIG": json.dumps(
                paquete["config"],
                ensure_ascii=False,
            )
        },
        files={
            "FILE": (
                "cuentas.csv",
                paquete["archivo"],
                "text/csv",
            )
        },
        timeout=60,
    )

    if respuesta.status_code != 200:
        raise RuntimeError(
            "Importacion no confirmada"
        )

    cuerpo = respuesta.json()
    resumen = (
        cuerpo.get("data", {}).get("importSummary", {})
    )

    if (
        cuerpo.get("status") != "success"
        or resumen.get("importType", "").upper() != "UPDATEADD"
        or resumen.get("totalRowCount") != paquete["cantidad"]
        or resumen.get("successRowCount") != paquete["cantidad"]
        or resumen.get("warnings") != 0
        or cuerpo.get("data", {}).get("importErrors")
    ):
        raise RuntimeError(
            "Respuesta de importacion inesperada; revisar"
        )

    return {
        "estado": "ACTUALIZADO",
        "cantidad": paquete["cantidad"],
    }


if __name__ == "__main__":
    load_dotenv(Path(".env"))
    load_dotenv(
        Path("../Webhook-SalesIQ-metricas/.env")
    )

    print("=== COMPARACION CRM VS ANALYTICS ===")

    plan = preparar_sincronizacion()

    print("Paginas CRM:", plan["paginas_crm"])
    print("Cuentas CRM:", plan["cuentas_crm"])
    print(
        "Cuentas Analytics:",
        plan["cuentas_analytics"]
    )
    print("Cuentas nuevas:", len(plan["nuevas"]))
    print(
        "Nombres modificados:",
        len(plan["modificadas"])
    )
    print("Sin cambios:", plan["sin_cambios"])

    print("Modo: SOLO LECTURA")
    print("Escrituras CRM: 0")
    print("Escrituras Analytics: 0")
    print("RESULTADO GENERAL: OK")
