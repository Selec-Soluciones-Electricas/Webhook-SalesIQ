"""Cotizaciones Retell -> Zoho Sandbox, aisladas del escritor de produccion.

La llamada externa siempre es el procesador Retell en simulacion. Este
modulo recibe exclusivamente candidatas ya clasificadas de ese procesador.
Las escrituras exigen habilitacion separada, owner, fecha y fecha minima.
"""

import os
import re
from datetime import date, timedelta

from services.sofia.cotizaciones_sandbox import (
    preparar_borrador_cotizacion_sandbox,
)
from services.sofia.registro_cotizaciones_sandbox import (
    registrar_cotizacion_sandbox,
)


def procesar_cotizaciones_cron_sandbox(
    llamadas,
    agent_id,
    *,
    conexion=None,
    http_post=None,
):
    """Procesa a lo sumo unas pocas cotizaciones por ejecucion.

    No devuelve datos personales, identificadores Retell ni tokens.
    Una respuesta incierta detiene todo el lote para revision humana.
    """
    resumen = {
        "estado": "simulacion",
        "detectadas": 0,
        "listas": 0,
        "revision": 0,
        "anteriores_al_inicio": 0,
        "fuera_de_lista": 0,
        "creadas": 0,
        "ya_registradas": 0,
        "bloqueadas": 0,
        "pendientes": 0,
        "escrituras_crm": False,
    }
    if not isinstance(llamadas, list) or not agent_id:
        return {**resumen, "estado": "bloqueado", "bloqueadas": 1}

    # Desactivado por defecto incluso en Render.
    activar = (
        os.getenv("SOFIA_SANDBOX_DEALS_WRITES_ENABLED", "false")
        .strip().lower() == "true"
    )
    elegibles = []
    vistos = set()
    for llamada in llamadas:
        resumen["detectadas"] += 1
        if not isinstance(llamada, dict) or llamada.get("agent_id") != agent_id:
            resumen["revision"] += 1
            continue
        call_id = llamada.get("call_id")
        if not isinstance(call_id, str) or call_id in vistos:
            resumen["revision"] += 1
            continue
        vistos.add(call_id)
        borrador = preparar_borrador_cotizacion_sandbox(llamada)
        if borrador.get("estado") != "borrador_preparado":
            resumen["revision"] += 1
            continue
        resumen["listas"] += 1
        elegibles.append((llamada, borrador))

    resumen["pendientes"] = len(elegibles)
    if not activar:
        return resumen

    # No permitir que el flag de Casos ni el del CRM viejo habiliten esto.
    propietario = os.getenv("SOFIA_SANDBOX_DEALS_OWNER_ID", "").strip()
    minimo_texto = os.getenv("SOFIA_SANDBOX_DEALS_CUTOFF_MS", "").strip()
    dias_texto = os.getenv("SOFIA_SANDBOX_DEALS_CLOSE_DAYS", "").strip()
    maximo_texto = os.getenv("SOFIA_SANDBOX_DEALS_MAX_PER_RUN", "1").strip()
    permitidos_texto = os.getenv("SOFIA_SANDBOX_DEALS_ALLOWED_CALL_IDS", "").strip()
    permitidos = set(filter(None, (x.strip() for x in permitidos_texto.split(","))))

    # Sin lista explicita, nunca crear cotizaciones.
    # Proteccion: modo manual exige lista; modo automatico exige lista vacia.
    # En ambos casos aun se requiere habilitar escrituras y pasar el corte.
    modo = os.getenv("SOFIA_SANDBOX_DEALS_MODE", "manual").strip().lower()
    if modo not in ("manual", "automatico"):
        return {**resumen, "estado": "bloqueado", "bloqueadas": 1}
    if modo == "manual" and not permitidos:
        return {**resumen, "estado": "bloqueado", "bloqueadas": 1}
    if modo == "automatico" and permitidos:
        return {**resumen, "estado": "bloqueado", "bloqueadas": 1}

    if (
        not re.fullmatch(r"[0-9]{10,20}", propietario)
        or not re.fullmatch(r"[0-9]{13}", minimo_texto)
        or not re.fullmatch(r"[0-9]{1,3}", dias_texto)
        or not re.fullmatch(r"[0-9]{1,2}", maximo_texto)
    ):
        return {**resumen, "estado": "bloqueado", "bloqueadas": 1}

    minimo = int(minimo_texto)
    dias = int(dias_texto)
    maximo = int(maximo_texto)
    if not (1 <= dias <= 180 and 1 <= maximo <= 10):
        return {**resumen, "estado": "bloqueado", "bloqueadas": 1}

    if not elegibles:
        return {**resumen, "estado": "sandbox_habilitado"}

    # Ningun token ni dato CRM se solicita en modo simulacion.
    if (
        not isinstance(conexion, dict)
        or conexion.get("base") != "https://sandbox.zohoapis.com"
        or not callable(conexion.get("obtener_token"))
        or not callable(conexion.get("http_get"))
        or not callable(http_post)
    ):
        return {**resumen, "estado": "bloqueado", "bloqueadas": 1}

    # Se obtiene un unico token, ya verificado como Sandbox por crm_sandbox.
    # Ademas, se confirma el propietario ANTES de crear la primera Cuenta.
    try:
        token = conexion["obtener_token"]()
        conexion = dict(conexion)
        conexion["obtener_token"] = lambda: token
        validacion = conexion["http_get"](
            "https://sandbox.zohoapis.com/crm/v8/users/" + propietario,
            headers={"Authorization": "Zoho-oauthtoken " + token},
            timeout=20,
            allow_redirects=False,
        )
        usuarios = validacion.json().get("users") if validacion.status_code == 200 else None
        if (
            not isinstance(usuarios, list) or len(usuarios) != 1
            or str(usuarios[0].get("id")) != propietario
            or str(usuarios[0].get("status", "")).lower() != "active"
        ):
            return {**resumen, "estado": "bloqueado", "bloqueadas": 1}
    except Exception:
        return {**resumen, "estado": "bloqueado", "bloqueadas": 1}

    # Filtrar llamadas antiguas/no autorizadas ANTES de obtener OAuth.
    pendientes_autorizadas = []
    for llamada, borrador in elegibles:
        inicio = llamada.get("start_timestamp")
        if type(inicio) is not int or inicio < minimo:
            resumen["anteriores_al_inicio"] += 1
            resumen["pendientes"] -= 1
            continue
        if modo == "manual" and borrador["call_id"] not in permitidos:
            resumen["fuera_de_lista"] += 1
            resumen["pendientes"] -= 1
            continue
        pendientes_autorizadas.append(borrador)

    if not pendientes_autorizadas:
        return {**resumen, "estado": "sandbox_habilitado"}

    fecha_cierre = (date.today() + timedelta(days=dias)).isoformat()
    for borrador in pendientes_autorizadas[:maximo]:
        try:
            decision = registrar_cotizacion_sandbox(
                borrador,
                conexion=conexion,
                http_post=http_post,
                owner_id=propietario,
                fecha_cierre=fecha_cierre,
                autorizar=True,
            )
        except Exception:
            decision = {"estado": "resultado_incierto"}

        estado = decision.get("estado") if isinstance(decision, dict) else None
        if estado == "creado":
            resumen["creadas"] += 1
            resumen["pendientes"] -= 1
        elif estado == "ya_registrado":
            resumen["ya_registradas"] += 1
            resumen["pendientes"] -= 1
        else:
            resumen["bloqueadas"] += 1
            resumen["estado"] = "parcial"
            break  # No continuar creando en caso de duda.

    resumen["escrituras_crm"] = resumen["creadas"] > 0
    if resumen["estado"] != "parcial":
        resumen["estado"] = "sandbox_habilitado"
    return resumen
