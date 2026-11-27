"""Autorizacion compartida de llamadas en CRM produccion.

El modo automatico es opt-in, limitado a NUEVAS llamadas y solo a registros
marcados como prueba. El modo piloto por Call ID se conserva independiente.
Sin cutoff valido, sin marcador de prueba o con flags incompatibles: no escribir.
"""

import os
import re
from datetime import datetime, timezone

CALL_ID = re.compile(r"call_[A-Za-z0-9_-]{1,123}\Z")


def activo(nombre):
    return os.getenv(nombre, "false").strip().lower() == "true"


def automatico_habilitado():
    return activo("SOFIA_PROD_CRON_AUTO_ENABLED")


def configuracion_automatica():
    """Devuelve configuracion validada sin secretos; nunca modifica variables."""
    if not automatico_habilitado():
        return {"estado": "desactivado"}

    if activo("SOFIA_PROD_CRON_PILOT_ENABLED"):
        return {"estado": "bloqueado", "motivo": "piloto_y_automatico_incompatibles"}

    # Mientras NO exista el escritor de clientes reales, la modalidad
    # automatica solo puede crear registros con marca [PRUEBA SOFIA].
    if not activo("SOFIA_PROD_AUTO_TEST_ONLY"):
        return {"estado": "bloqueado", "motivo": "solo_pruebas_no_autorizado"}

    if activo("SOFIA_PROD_CASES_MAIL_REAL_RECIPIENTS_ENABLED"):
        return {"estado": "bloqueado", "motivo": "destinatarios_reales_no_autorizados"}

    cutoff = os.getenv("SOFIA_PROD_AUTO_START_MS", "").strip()
    maximo = os.getenv("SOFIA_PROD_AUTO_MAX_PER_RUN", "1").strip()
    if not re.fullmatch(r"[0-9]{13}", cutoff):
        return {"estado": "bloqueado", "motivo": "fecha_inicio_invalida"}
    if not re.fullmatch(r"[1-5]", maximo):
        return {"estado": "bloqueado", "motivo": "limite_invalido"}

    cutoff_ms = int(cutoff)
    ahora_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    # El corte permanece fijo tras la activacion; NO caduca con cada cron.
    # Exigir un inicio del proyecto y no permitir horas futuras arbitrarias.
    fecha_minima_segura = 1795737600000  # 2026-11-27 00:00:00 UTC
    if cutoff_ms < fecha_minima_segura or cutoff_ms > ahora_ms + 5 * 60 * 1000:
        return {"estado": "bloqueado", "motivo": "fecha_inicio_fuera_de_ventana"}

    return {"estado": "autorizado", "inicio_ms": cutoff_ms, "maximo": int(maximo)}


def llamada_autorizada(modulo, call_id, start_timestamp=None):
    """Autoriza una sola llamada del piloto o una llamada nueva del auto-test."""
    if modulo not in ("Cases", "Deals") or not isinstance(call_id, str):
        return False
    if CALL_ID.fullmatch(call_id) is None:
        return False

    if automatico_habilitado():
        config = configuracion_automatica()
        if config.get("estado") != "autorizado":
            return False
        if type(start_timestamp) is not int:
            return False
        ahora_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        return config["inicio_ms"] <= start_timestamp <= ahora_ms + 5 * 60 * 1000

    nombre = (
        "SOFIA_PROD_CASES_ALLOWED_CALL_ID" if modulo == "Cases"
        else "SOFIA_PROD_DEALS_ALLOWED_CALL_ID"
    )
    return call_id == os.getenv(nombre, "").strip()
