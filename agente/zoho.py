"""
Puente entre el agente IA y las funciones de Zoho que ya usa el bot.

ZOHO_MODO=prueba     -> no toca Zoho, solo imprime (para probar.py)
ZOHO_MODO=produccion -> usa las mismas funciones que los flujos 1 y 2
"""

import os
from datetime import date, timedelta

MODO_PRUEBA = os.getenv("ZOHO_MODO", "prueba").strip().lower() == "prueba"


# =========================================================
# COTIZACIÓN -> Account + Contact + Deal (mismo flujo que opción 1)
# =========================================================

def _detalle_productos(productos: list) -> str:
    lineas = []
    for i, p in enumerate(productos, 1):
        partes = [str(p.get("descripcion") or "").strip()]
        if p.get("numero_parte"):
            partes.append(f"N° parte: {p['numero_parte']}")
        if p.get("marca"):
            partes.append(f"Marca: {p['marca']}")
        partes.append(f"Cantidad: {p.get('cantidad')}")
        lineas.append(f"{i}. " + " | ".join(partes))
    return "\n".join(lineas)


def registrar_cotizacion(datos: dict, contexto: dict) -> str:
    productos = datos["productos"]
    detalle = _detalle_productos(productos)
    marcas = sorted({str(p["marca"]).strip() for p in productos if p.get("marca")})

    data = {
        "owner_asignado": contexto.get("owner_asignado"),
        "conversation_id": contexto.get("conversation_id"),
        "num_chat": contexto.get("num_chat"),
        "empresa": datos["empresa"],
        "rut": datos["rut"],
        "contacto": datos["contacto"],
        "correo": datos["correo"],
        "telefono": datos["telefono"],
        # crear_deal_en_zoho muestra num_parte como "Producto / descripción",
        # por eso va ahí el detalle completo (soporta varios productos)
        "num_parte": detalle,
        "marca": ", ".join(marcas) or "Por definir",
        "descripcion": detalle,
        "cantidad": productos[0]["cantidad"] if len(productos) == 1 else "Ver detalle",
        "direccion_entrega": datos["direccion_entrega"],
    }

    if MODO_PRUEBA:
        print(f"  [zoho prueba] registrar_cotizacion:\n{detalle}")
        return "PRUEBA-DEAL"

    from conversation.quotation import registrar_cotizacion_en_zoho
    from services.email_service import enviar_correo_owner

    owner, _resp, deal_id = registrar_cotizacion_en_zoho(data)
    if not deal_id:
        raise RuntimeError("Zoho no devolvió deal_id")

    enviar_correo_owner(owner, deal_id, f"Cotización - {data['empresa']}", data)
    return str(deal_id)


# =========================================================
# POSTVENTA -> Case + correo (mismo flujo que opción 2)
# =========================================================

def registrar_postventa(datos: dict) -> str:
    data = {
        "nombre": datos["nombre"],
        "rut": datos["rut"],
        "numero_factura": datos["numero_factura"],
        "detalle": datos["detalle"],
    }

    if MODO_PRUEBA:
        print(f"  [zoho prueba] registrar_postventa: {data}")
        return "PRUEBA-CASE"

    from utils.email_postventa import enviar_correo_postventa

    enviar_correo_postventa(data)  # crea el Case y envía el correo; lanza error si falla
    return "ok"


# =========================================================
# CONTACTO CON AGENTE -> Account + Contact + Tarea para el ejecutivo
# =========================================================

def registrar_contacto(datos: dict, contexto: dict) -> str:
    data = {
        "empresa": datos.get("empresa", ""),
        "rut": datos.get("rut", ""),
        "contacto": datos["contacto"],
        "correo": datos["correo"],
        "telefono": datos["telefono"],
    }

    descripcion = (
        "Cliente atendido por el agente IA de WhatsApp (opción 'Contactar con agente').\n\n"
        f"Motivo: {datos['motivo']}\n"
        f"Resumen: {datos['resumen']}\n\n"
        f"Empresa: {data['empresa']}\nRUT: {data['rut']}\n"
        f"Contacto: {data['contacto']}\nCorreo: {data['correo']}\nTeléfono: {data['telefono']}\n"
        f"Chat SalesIQ: {contexto.get('num_chat', '')}"
    )

    if MODO_PRUEBA:
        print(f"  [zoho prueba] registrar_contacto:\n{descripcion}")
        return "PRUEBA-TAREA"

    import requests
    from services.zoho_service import (
        CRM_BASE,
        get_access_token,
        normalizar_owner,
        obtener_o_crear_account,
        obtener_o_crear_contact,
    )

    owner = normalizar_owner(contexto.get("owner_asignado"))

    account_id = None
    if data["rut"] or data["empresa"]:
        account_id = obtener_o_crear_account(data, owner=owner)

    contact_id = obtener_o_crear_contact(data, account_id=account_id, owner=owner)
    if not contact_id:
        raise RuntimeError("No se pudo crear/encontrar el Contact")

    tarea = {
        "Subject": f"Contactar cliente (Agente IA) - {data['empresa'] or data['contacto']}",
        "Due_Date": (date.today() + timedelta(days=1)).isoformat(),
        "Status": "Not Started",
        "Priority": "High",
        "Description": descripcion,
        "Who_Id": {"id": str(contact_id)},
    }
    if account_id:
        tarea["What_Id"] = {"id": str(account_id)}
        tarea["$se_module"] = "Accounts"
    if owner.get("id"):
        tarea["Owner"] = {"id": owner["id"]}

    resp = requests.post(
        f"{CRM_BASE}/Tasks",
        headers={
            "Authorization": f"Zoho-oauthtoken {get_access_token()}",
            "Content-Type": "application/json",
        },
        json={"data": [tarea]},
        timeout=10,
    )
    print("[agente.registrar_contacto] Tasks:", resp.status_code, resp.text[:300])

    registros = (resp.json().get("data") or []) if resp.ok else []
    if not registros or registros[0].get("status") != "success":
        raise RuntimeError(f"Zoho no creó la tarea: {resp.text[:300]}")

    return str(registros[0]["details"]["id"])