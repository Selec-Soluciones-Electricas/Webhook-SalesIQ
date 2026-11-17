"""Consulta interna por relaciones exactas. Sin red ni escritura propia."""
import re

CAMPO_NUMERO = "Numero Cotización"
COLUMNAS = {
    "Cotizaciones": ["Id", CAMPO_NUMERO, "Fase de Presupuesto", "Nombre de Cuenta", "Nombre de Trato"],
    "Negocios": ["Id", "Nombre de Cuenta", "Asignado a"],
    "Clientes": ["Id", "Nombre de Cuenta"],
    "Usuarios": ["Id", "Nombre completo", "Estado"],
}


class FalloConsulta(Exception):
    def __init__(self, estado):
        self.estado = estado


def id_valido(valor):
    return isinstance(valor, str) and re.fullmatch(r"[0-9]{1,64}", valor) is not None


def resultado(estado, datos=None, avisos=None):
    return {"estado": estado, "datos_internos": datos, "avisos": avisos or [],
            "identidad_verificada": False, "autorizado_para_divulgar": False,
            "ultima_sincronizacion_verificada": False}


def leer_unico(lector, tabla, campo, valor):
    if not id_valido(valor):
        raise FalloConsulta("identificador_invalido")
    filas = lector(tabla, campo, valor, list(COLUMNAS[tabla]))
    if not isinstance(filas, list):
        raise FalloConsulta("respuesta_invalida")
    for fila in filas:
        if not isinstance(fila, dict) or any(not isinstance(fila.get(c), str) for c in COLUMNAS[tabla]):
            raise FalloConsulta("respuesta_invalida")
        if fila[campo] != valor:
            raise FalloConsulta("filtro_no_confirmado")
    if not filas:
        return None
    if len(filas) != 1:
        raise FalloConsulta("coincidencia_ambigua")
    if not id_valido(filas[0]["Id"]):
        raise FalloConsulta("respuesta_invalida")
    return filas[0]


def consultar_cotizacion_analytics(numero, lector):
    if not isinstance(numero, str) or not id_valido(numero.strip()):
        return resultado("numero_invalido")
    if not callable(lector):
        return resultado("configuracion_invalida")
    numero = numero.strip()
    try:
        q = leer_unico(lector, "Cotizaciones", CAMPO_NUMERO, numero)
        if q is None:
            return resultado("no_encontrada_en_analytics", avisos=["no_descarta_registro_reciente_o_solicitud_pendiente"])
        datos = {"numero": numero, "estado_registrado": q["Fase de Presupuesto"] or None,
                 "cliente": None, "ejecutivo_provisional": None, "usuario_asignado_estado": None,
                 "cuenta_negocio_coincide": None, "fuente_ejecutivo": "Negocios.Asignado a -> Usuarios.Id"}
        if not q["Nombre de Trato"] or not q["Nombre de Cuenta"]:
            return resultado("datos_incompletos", datos, ["cotizacion_sin_cuenta_o_negocio"])
        d = leer_unico(lector, "Negocios", "Id", q["Nombre de Trato"])
        if d is None:
            return resultado("datos_incompletos", datos, ["negocio_no_disponible"])
        if not d["Nombre de Cuenta"]:
            return resultado("datos_incompletos", datos, ["cuenta_negocio_ausente"])
        if not id_valido(d["Nombre de Cuenta"]):
            raise FalloConsulta("identificador_invalido")
        if not id_valido(q["Nombre de Cuenta"]):
            raise FalloConsulta("identificador_invalido")
        datos["cuenta_negocio_coincide"] = d["Nombre de Cuenta"] == q["Nombre de Cuenta"]
        if not datos["cuenta_negocio_coincide"]:
            return resultado("revision_coherencia", datos, ["cuentas_distintas"])
        cuenta = leer_unico(lector, "Clientes", "Id", q["Nombre de Cuenta"])
        if cuenta is None or not cuenta["Nombre de Cuenta"].strip():
            return resultado("datos_incompletos", datos, ["cliente_no_disponible"])
        datos["cliente"] = cuenta["Nombre de Cuenta"]
        if not d["Asignado a"]:
            return resultado("datos_incompletos", datos, ["responsable_no_asignado"])
        usuario = leer_unico(lector, "Usuarios", "Id", d["Asignado a"])
        if usuario is None:
            return resultado("datos_incompletos", datos, ["usuario_no_disponible"])
        estado = usuario["Estado"].strip().lower()
        datos["usuario_asignado_estado"] = estado
        if estado != "active":
            return resultado("revision_responsable", datos, ["usuario_deshabilitado" if estado == "disabled" else "estado_usuario_no_confirmado"])
        if not usuario["Nombre completo"].strip():
            return resultado("datos_incompletos", datos, ["nombre_ejecutivo_ausente"])
        datos["ejecutivo_provisional"] = usuario["Nombre completo"]
        if not datos["estado_registrado"]:
            return resultado("datos_incompletos", datos, ["fase_ausente"])
        return resultado("encontrada", datos)
    except FalloConsulta as error:
        return resultado(error.estado)
    except Exception:
        # No filtrar cuerpos de respuesta, URLs ni credenciales en errores.
        return resultado("error_lectura")
