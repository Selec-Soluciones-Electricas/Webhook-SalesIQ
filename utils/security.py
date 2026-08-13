import re



# Función para enmascarar valores sensibles, mostrando solo los primeros y últimos caracteres según lo especificado, y reemplazando el resto con asteriscos. Esto es útil para proteger la privacidad de los datos del cliente en los logs o en cualquier salida que pueda ser visible, manteniendo solo una referencia útil para identificación.
def mask_value(value: str, show_start: int = 2, show_end: int = 2) -> str:
    if value is None:
        return ""
    raw = str(value).strip()
    if not raw:
        return ""
    if len(raw) <= (show_start + show_end):
        return "*" * len(raw)
    return f"{raw[:show_start]}{'*' * (len(raw) - (show_start + show_end))}{raw[-show_end:]}"
# Función específica para enmascarar correos electrónicos, mostrando solo el primer carácter del usuario y el dominio completo, para proteger la privacidad del cliente mientras se mantiene una referencia útil para identificación.
def mask_email(email: str) -> str:
    if not email:
        return ""
    email = str(email).strip()
    if "@" not in email:
        return mask_value(email)
    user, domain = email.split("@", 1)
    return f"{mask_value(user, 1, 1)}@{domain}"
# Función específica para enmascarar números de teléfono, limpiando el formato y aplicando el enmascaramiento adecuado, mostrando solo el último dígito y los primeros 4 caracteres, para proteger la privacidad del cliente mientras se mantiene una referencia útil para identificación.
def mask_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", str(phone or ""))
    if not digits:
        return ""
    return mask_value(digits, 0, 4)
# Función específica para enmascarar RUT, limpiando el formato y aplicando el enmascaramiento adecuado, mostrando solo los primeros 2 caracteres y el dígito verificador final, para proteger la privacidad del cliente mientras se mantiene una referencia útil para identificación.
def mask_rut(rut: str) -> str:
    cleaned = str(rut or "").strip()
    if not cleaned:
        return ""
    return mask_value(cleaned, 2, 1)
# Función para limpiar y enmascarar el payload recibido desde SalesIQ, asegurando que los datos sensibles del visitante estén protegidos antes de ser registrados en los logs o procesados por el sistema, manteniendo solo la información necesaria para identificar al visitante de forma segura.
def scrub_payload(payload: dict) -> dict:
    safe = dict(payload or {})
    visitor = dict(safe.get("visitor") or {})
    if visitor:
        if visitor.get("phone"):
            visitor["phone"] = mask_phone(visitor.get("phone"))
        if visitor.get("email"):
            visitor["email"] = mask_email(visitor.get("email"))
        if visitor.get("id"):
            visitor["id"] = mask_value(visitor.get("id"), 2, 2)
        if visitor.get("visitor_id"):
            visitor["visitor_id"] = mask_value(visitor.get("visitor_id"), 2, 2)
        if visitor.get("active_conversation_id"):
            visitor["active_conversation_id"] = mask_value(visitor.get("active_conversation_id"), 2, 2)
        safe["visitor"] = visitor
    return safe
    # Función auxiliar para formatear la información del owner de forma segura para los logs, mostrando el nombre y un ID parcialmente enmascarado, o indicando que no hay owner si el diccionario está vacío o no tiene la información esperada. Esto ayuda a mantener la privacidad de los datos sensibles en los logs mientras se sigue teniendo una referencia útil para identificar al owner asignado.
def safe_owner_for_log(owner: dict) -> str:
    if not owner:
        return "(sin owner)"
    return f"{owner.get('nombre', 'N/A')} ({mask_value(owner.get('id', ''), 2, 2)})"
