
import hashlib


def preparar_borrador_caso_consulta(clasificacion):
    """
    Prepara un Caso de consulta general de Sofia.

    No consulta ni modifica Zoho CRM.
    No envia notificaciones.
    """

    if not isinstance(clasificacion, dict):
        raise ValueError("Clasificacion invalida")

    if clasificacion.get("estado") != "candidata_caso":
        raise ValueError("La llamada no es una consulta valida")

    call_id = clasificacion.get("call_id")

    if (
        not isinstance(call_id, str)
        or not call_id.strip()
        or len(call_id) > 128
        or any(c in call_id for c in "\r\n")
    ):
        raise ValueError("Call ID invalido")

    call_id = call_id.strip()


    # Identificar el tipo de Caso.
    tipo = clasificacion.get("tipo_solicitud", "consulta")

    if tipo not in ("consulta", "postventa"):
        raise ValueError("Tipo de solicitud no autorizado")


    # Identificador determinista para buscar
    # posteriormente el Caso en Zoho CRM.
    huella = hashlib.sha256(
        call_id.encode("utf-8")
    ).hexdigest()[:24].upper()

    asunto = f"SOFIA_{tipo.upper()}_{huella}"

    interlocutor = (
        clasificacion.get("tipo_interlocutor")
        or "no_identificado"
    )

    prioridad = clasificacion.get("prioridad_caso")

    resultado = (
        clasificacion.get("resultado_atencion")
        or "no_identificado"
    )

    resumen = (
        clasificacion.get("resumen")
        or "Sin resumen disponible"
    )


    # Datos de contacto obtenidos desde Retell.
    contacto = clasificacion.get("contacto")

    if not isinstance(contacto, dict):
        contacto = {}

    campos_contacto = (
        ("Nombre", "nombre_cliente"),
        ("Correo", "email_cliente"),
        ("Telefono", "telefono_cliente"),
        ("Empresa", "empresa"),
        ("RUT", "rut_cliente"),
        ("Motivo de contacto", "motivo_contacto"),
        ("Numero de factura", "numero_factura"),
        ("Numero de OC", "numero_oc"),
        ("Problema reportado", "descripcion_problema"),
    )

    lineas_contacto = []

    for etiqueta, clave in campos_contacto:
        valor = contacto.get(clave)

        if isinstance(valor, str) and valor.strip():
            lineas_contacto.append(
                f"{etiqueta}: {valor.strip()}"
            )

    seccion_contacto = (
        "Datos del cliente:\n"
        + "\n".join(lineas_contacto)
        + "\n\n"
        if lineas_contacto
        else ""
    )

    descripcion = (
        "Solicitud telefonica atendida por Sofia.\n\n"
        f"Call ID: {call_id}\n"
        f"Tipo de solicitud: {tipo}\n"
        f"Tipo de interlocutor: {interlocutor}\n"
        f"Prioridad detectada: {prioridad or 'Sin clasificar'}\n"
        f"Resultado de atencion: {resultado}\n\n"
        f"Resumen de la llamada:\n{resumen}\n\n"
        f"{seccion_contacto}"
        "Registro preparado automaticamente. "
        "No implica que se haya enviado una notificacion."
    )


    campos = {
        "Subject": asunto,
        "Status": "New",
        "Case_Origin": "Teléfono",
        "ID_de_llamada_Retell": call_id,
        "Description": descripcion,
    }


    # No inventar una prioridad cuando Retell
    # no haya podido determinarla.
    if prioridad in ("Alto", "Medio", "Bajo"):
        campos["Priority"] = prioridad

    return {
        "modulo": "Cases",
        "call_id": call_id,
        "tipo_solicitud": tipo,
        "asunto_control": asunto,
        "campos_propuestos": campos,
        "escritura_realizada": False,
    }


def planificar_creacion_caso_consulta(borrador, busqueda):
    """
    Decide si una consulta de Sofia puede preparar
    la creacion de un Caso en Zoho CRM.

    No consulta, crea ni modifica registros.
    """

    bloqueado = {
        "estado": "bloqueado",
        "motivo": "datos_invalidos",
        "escritura_realizada": False,
    }

    if not isinstance(borrador, dict):
        return bloqueado

    if not isinstance(busqueda, dict):
        return bloqueado

    asunto = borrador.get("asunto_control")
    campos = borrador.get("campos_propuestos")
    call_id = borrador.get("call_id")

    if (
        borrador.get("modulo") != "Cases"
        or not isinstance(asunto, str)
        or not asunto.startswith((
            "SOFIA_CONSULTA_",
            "SOFIA_POSTVENTA_",
        ))
        or not isinstance(call_id, str)
        or not call_id.strip()
        or not isinstance(campos, dict)
        or campos.get("Subject") != asunto
        or not isinstance(campos.get("Description"), str)
    ):
        return bloqueado

    estado = busqueda.get("estado")

    # Nunca modificar un Caso existente.
    if estado == "encontrado":
        registro_id = busqueda.get("registro_id")

        if not isinstance(registro_id, str) or not registro_id:
            return bloqueado

        return {
            "estado": "ya_registrado",
            "call_id": call_id,
            "registro_id": registro_id,
            "escritura_realizada": False,
        }

    # Preparar una creacion, pero no ejecutarla.
    if (
        estado == "no_encontrado"
        and busqueda.get("registro_id") is None
    ):
        return {
            "estado": "creacion_pendiente",
            "call_id": call_id,
            "asunto_control": asunto,
            "campos_propuestos": campos.copy(),
            "requiere_validacion_crm": True,
            "escritura_realizada": False,
        }

    # Ante errores o estados desconocidos, bloquear.
    return {
        "estado": "bloqueado",
        "motivo": "busqueda_no_confirmada",
        "call_id": call_id,
        "escritura_realizada": False,
    }


def verificar_y_planificar_caso_consulta(
    clasificacion,
    consultar_caso,
):
    """
    Prepara un Caso, verifica su existencia
    y decide si debe crearse.

    La funcion consultar_caso se recibe como parametro
    para permitir simulaciones sin conexiones reales.

    No crea ni modifica registros en Zoho CRM.
    """

    bloqueado = {
        "estado": "bloqueado",
        "motivo": "verificacion_no_completada",
        "escritura_realizada": False,
    }

    if not callable(consultar_caso):
        return bloqueado

    try:
        borrador = preparar_borrador_caso_consulta(
            clasificacion
        )
    except (ValueError, TypeError, KeyError):
        return bloqueado

    try:
        busqueda = consultar_caso(
            "Cases",
            borrador["asunto_control"],
        )
    except Exception:
        busqueda = {
            "estado": "error",
            "registro_id": None,
        }

    return planificar_creacion_caso_consulta(
        borrador,
        busqueda,
    )


def preparar_solicitud_creacion_caso_consulta(decision):
    """
    Construye una solicitud de insercion para Zoho CRM.

    No realiza conexiones HTTP.
    No crea ni actualiza Casos.
    """

    if not isinstance(decision, dict):
        raise ValueError("Decision invalida")

    if (
        decision.get("estado") != "creacion_pendiente"
        or decision.get("requiere_validacion_crm") is not True
        or decision.get("escritura_realizada") is not False
    ):
        raise ValueError("Creacion no autorizada para preparar")

    call_id = decision.get("call_id")
    campos = decision.get("campos_propuestos")

    if (
        not isinstance(call_id, str)
        or not call_id.strip()
        or len(call_id) > 128
        or any(c in call_id for c in "\r\n")
        or not isinstance(campos, dict)
    ):
        raise ValueError("Datos del Caso invalidos")

    huella = hashlib.sha256(
        call_id.encode("utf-8")
    ).hexdigest()[:24].upper()

    asuntos_validos = {
        f"SOFIA_CONSULTA_{huella}",
        f"SOFIA_POSTVENTA_{huella}",
    }

    if (
        decision.get("asunto_control") not in asuntos_validos
        or campos.get("Subject") not in asuntos_validos
        or campos.get("ID_de_llamada_Retell") != call_id
        or campos.get("Status") != "New"
        or campos.get("Case_Origin") != "Tel\u00e9fono"
        or not isinstance(campos.get("Description"), str)
        or not campos["Description"].strip()
    ):
        raise ValueError("Campos del Caso inconsistentes")

    permitidos = {
        "Subject",
        "Status",
        "Case_Origin",
        "ID_de_llamada_Retell",
        "Description",
        "Priority",
    }

    if not set(campos).issubset(permitidos):
        raise ValueError("Campos no autorizados")

    if (
        "Priority" in campos
        and campos["Priority"] not in ("Alto", "Medio", "Bajo")
    ):
        raise ValueError("Prioridad invalida")

    return {
        "modulo": "Cases",
        "operacion": "insert",
        "metodo": "POST",
        "ruta": "/crm/v8/Cases",
        "payload": {
            "data": [campos.copy()],
            "trigger": [],
        },
        "escritura_realizada": False,
    }


def interpretar_respuesta_creacion_caso_consulta(
    codigo_http,
    datos,
):
    """
    Interpreta una respuesta de insercion de Zoho CRM.

    No ejecuta solicitudes HTTP.
    No crea ni modifica Casos.
    """

    incierto = {
        "estado": "resultado_incierto",
        "registro_id": None,
    }

    if type(codigo_http) is not int:
        return incierto

    if not isinstance(datos, dict):
        return incierto

    registros = datos.get("data")

    # Zoho puede devolver errores directamente
    # o dentro de una lista data.
    if isinstance(registros, list) and len(registros) == 1:
        registro = registros[0]
    elif "code" in datos:
        registro = datos
    else:
        return incierto

    if not isinstance(registro, dict):
        return incierto

    codigo = registro.get("code")
    estado = registro.get("status")
    detalles = registro.get("details")

    # Confirmar creacion solo con HTTP exitoso,
    # respuesta SUCCESS e identificador valido.
    if (
        200 <= codigo_http < 300
        and codigo == "SUCCESS"
        and estado == "success"
        and isinstance(detalles, dict)
    ):
        registro_id = detalles.get("id")

        if isinstance(registro_id, str) and registro_id.strip():
            return {
                "estado": "creado",
                "registro_id": registro_id,
            }

        return incierto

    # El campo unico impidio otro registro
    # con el mismo identificador de llamada.
    if codigo == "DUPLICATE_DATA" and estado == "error":
        campo = (
            detalles.get("api_name")
            if isinstance(detalles, dict)
            else None
        )

        if campo == "ID_de_llamada_Retell":
            return {
                "estado": "duplicado_detectado",
                "registro_id": None,
            }

        return {
            "estado": "bloqueado",
            "motivo": "duplicado_en_otro_campo",
            "registro_id": None,
        }

    if codigo_http >= 500:
        return incierto

    return {
        "estado": "bloqueado",
        "motivo": "respuesta_no_aceptada",
        "registro_id": None,
    }


def buscar_caso_consulta_por_call_id(call_id, *, conexion=None):
    """Busca un Caso por su ID de llamada Retell.

    Solo lectura. Nunca crea ni modifica registros.
    """

    error = {
        "estado": "error",
        "registro_id": None,
    }

    if (
        not isinstance(call_id, str)
        or not 3 <= len(call_id) <= 128
        or any(
            caracter not in (
                "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                "abcdefghijklmnopqrstuvwxyz"
                "0123456789_-"
            )
            for caracter in call_id
        )
    ):
        return error


    try:
        if conexion is None:
            from services import zoho_service

            token = zoho_service.get_access_token()

            if not token:
                return error

            base = zoho_service.CRM_BASE.split("/crm/")[0]
            http_get = zoho_service.requests.get

        else:
            if not isinstance(conexion, dict):
                return error

            base = conexion.get("base")
            obtener_token = conexion.get("obtener_token")
            http_get = conexion.get("http_get")

            if (
                base != "https://sandbox.zohoapis.com"
                or not callable(obtener_token)
                or not callable(http_get)
            ):
                return error

            token = obtener_token()

            if not isinstance(token, str) or not token.strip():
                return error

            respuesta = http_get(
            f"{base}/crm/v8/Cases/search",
            headers={
                "Authorization": f"Zoho-oauthtoken {token}"
            },
            params={
                "criteria": (
                    "(ID_de_llamada_Retell:equals:"
                    f"{call_id})"
                ),
                "fields": "ID_de_llamada_Retell,Subject",
                "per_page": 200,
            },
            timeout=15,
        )

        if respuesta.status_code == 204:
            return {
                "estado": "no_encontrado",
                "registro_id": None,
            }

        if respuesta.status_code != 200:
            return error

        datos = respuesta.json()
        registros = datos.get("data")
        info = datos.get("info")

        if (
            not isinstance(registros, list)
            or not isinstance(info, dict)
            or info.get("more_records") is not False
        ):
            return error

        coincidencias = [
            registro
            for registro in registros
            if (
                isinstance(registro, dict)
                and registro.get("ID_de_llamada_Retell")
                == call_id
            )
        ]

        if len(coincidencias) != 1:
            return error

        registro_id = coincidencias[0].get("id")

        if not isinstance(registro_id, str):
            return error

        if not registro_id.strip():
            return error

        return {
            "estado": "encontrado",
            "registro_id": registro_id,
        }

    except Exception:
        return error


def buscar_casos_consulta_por_call_ids(call_ids, *, conexion=None):
    """
    Busca hasta 10 Call ID de Sofia en una sola
    consulta de lectura a Zoho CRM.

    No crea ni modifica Casos.
    Los errores bloquean todo el lote.
    """

    error = {
        "estado": "error",
        "resultados": {},
    }

    if (
        not isinstance(call_ids, list)
        or not 1 <= len(call_ids) <= 10
    ):
        return error

    permitidos = (
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "abcdefghijklmnopqrstuvwxyz"
        "0123456789_-"
    )

    for call_id in call_ids:
        if (
            not isinstance(call_id, str)
            or not 3 <= len(call_id) <= 128
            or any(c not in permitidos for c in call_id)
        ):
            return error

    if len(call_ids) != len(set(call_ids)):
        return error


    if not isinstance(conexion, dict):
        return error

    base = conexion.get("base")
    obtener_token = conexion.get("obtener_token")
    http_get = conexion.get("http_get")

    if (
        base != "https://sandbox.zohoapis.com"
        or not callable(obtener_token)
        or not callable(http_get)
    ):
        return error

    try:
        token = obtener_token()

        if not isinstance(token, str) or not token.strip():
            return error


        criterio = (
            "(ID_de_llamada_Retell:in:"
            + ",".join(call_ids)
            + ")"
        )

        respuesta = http_get(
            f"{base}/crm/v8/Cases/search",
            headers={
                "Authorization": f"Zoho-oauthtoken {token}",
            },
            params={
                "criteria": criterio,
                "fields": "ID_de_llamada_Retell,Subject",
                "per_page": 200,
                "approved": "both",
            },
            timeout=15,
        )

        resultados = {
            call_id: {
                "estado": "no_encontrado",
                "registro_id": None,
            }
            for call_id in call_ids
        }

        if respuesta.status_code == 204:
            return {
                "estado": "ok",
                "resultados": resultados,
            }

        if respuesta.status_code != 200:
            return error

        datos = respuesta.json()

        if not isinstance(datos, dict):
            return error

        registros = datos.get("data")
        info = datos.get("info")

        if (
            not isinstance(registros, list)
            or not isinstance(info, dict)
            or info.get("more_records") is not False
        ):
            return error

        ids_solicitados = set(call_ids)
        ids_encontrados = set()

        for registro in registros:
            if not isinstance(registro, dict):
                return error

            call_id = registro.get(
                "ID_de_llamada_Retell"
            )

            if not isinstance(call_id, str):
                return error

            # Zoho puede devolver coincidencias
            # aproximadas. Exigir igualdad exacta.
            if call_id not in ids_solicitados:
                continue

            registro_id = registro.get("id")

            if (
                not isinstance(registro_id, str)
                or not registro_id.strip()
                or call_id in ids_encontrados
            ):
                return error

            ids_encontrados.add(call_id)

            resultados[call_id] = {
                "estado": "encontrado",
                "registro_id": registro_id,
            }

        return {
            "estado": "ok",
            "resultados": resultados,
        }

    except Exception:
        return error


def verificar_caso_consulta_con_doble_control(
    clasificacion,
    consultar_asunto,
    consultar_call_id,
):
    """
    Verifica un Caso mediante Call ID y asunto.

    Solo prepara decisiones.
    No crea ni modifica registros en Zoho CRM.
    """

    bloqueado = {
        "estado": "bloqueado",
        "motivo": "verificacion_incompleta",
        "escritura_realizada": False,
    }

    if not callable(consultar_asunto):
        return bloqueado

    if not callable(consultar_call_id):
        return bloqueado

    try:
        borrador = preparar_borrador_caso_consulta(
            clasificacion
        )

        por_call_id = consultar_call_id(
            borrador["call_id"]
        )

        por_asunto = consultar_asunto(
            "Cases",
            borrador["asunto_control"],
        )

    except Exception:
        return bloqueado

    if (
        not isinstance(por_call_id, dict)
        or not isinstance(por_asunto, dict)
    ):
        return bloqueado

    estado_id = por_call_id.get("estado")
    estado_asunto = por_asunto.get("estado")

    validos = {"encontrado", "no_encontrado"}

    # Ante cualquier error o estado desconocido,
    # impedir la creacion.
    if estado_id not in validos:
        return bloqueado

    if estado_asunto not in validos:
        return bloqueado

    id_por_llamada = por_call_id.get("registro_id")
    id_por_asunto = por_asunto.get("registro_id")

    # Validar respuestas de las busquedas.
    if estado_id == "encontrado":
        if not isinstance(id_por_llamada, str) or not id_por_llamada:
            return bloqueado
    elif id_por_llamada is not None:
        return bloqueado

    if estado_asunto == "encontrado":
        if not isinstance(id_por_asunto, str) or not id_por_asunto:
            return bloqueado
    elif id_por_asunto is not None:
        return bloqueado

    # El Call ID es nuestro identificador principal.
    if estado_id == "encontrado":

        # Si ambas busquedas encuentran Casos distintos,
        # bloquear para revision.
        if (
            estado_asunto == "encontrado"
            and id_por_llamada != id_por_asunto
        ):
            return {
                **bloqueado,
                "motivo": "registros_inconsistentes",
            }

        return {
            "estado": "ya_registrado",
            "call_id": borrador["call_id"],
            "registro_id": id_por_llamada,
            "escritura_realizada": False,
        }

    # El asunto ya existe, pero el Call ID no.
    # No asumir que corresponde a la misma llamada.
    if estado_asunto == "encontrado":
        return {
            **bloqueado,
            "motivo": "asunto_existente_sin_call_id",
        }

    # Solo permitir preparar una creacion cuando
    # ambas busquedas confirman que no existe.
    return planificar_creacion_caso_consulta(
        borrador,
        {
            "estado": "no_encontrado",
            "registro_id": None,
        },
    )


def comprobar_autorizacion_creacion_caso(
    solicitud,
    *,
    simulacion=True,
    crm_writes_enabled=False,
    cases_writes_enabled=False,
    propietario_id=None,
):
    """
    Comprueba las condiciones para una futura
    creacion real de Casos de Sofia.

    No realiza solicitudes HTTP.
    No crea ni modifica registros.
    """

    def bloquear(motivo):
        return {
            "estado": "bloqueado",
            "motivo": motivo,
            "escritura_realizada": False,
        }

    if not isinstance(solicitud, dict):
        return bloquear("solicitud_invalida")

    if (
        solicitud.get("modulo") != "Cases"
        or solicitud.get("operacion") != "insert"
        or solicitud.get("metodo") != "POST"
        or solicitud.get("ruta") != "/crm/v8/Cases"
        or solicitud.get("escritura_realizada") is not False
    ):
        return bloquear("operacion_no_autorizada")

    payload = solicitud.get("payload")

    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("data"), list)
        or len(payload["data"]) != 1
    ):
        return bloquear("payload_invalido")

    campos = payload["data"][0]

    if (
        not isinstance(campos, dict)
        or not isinstance(
            campos.get("ID_de_llamada_Retell"), str
        )
        or not campos["ID_de_llamada_Retell"].strip()
    ):
        return bloquear("call_id_ausente")

    if simulacion is not False:
        return bloquear("modo_simulacion")

    if crm_writes_enabled is not True:
        return bloquear("escritura_crm_desactivada")

    if cases_writes_enabled is not True:
        return bloquear("escritura_casos_desactivada")

    if (
        not isinstance(propietario_id, str)
        or not propietario_id.isascii()
        or not propietario_id.isdecimal()
    ):
        return bloquear("propietario_no_definido")

    return {
        "estado": "condiciones_preliminares_cumplidas",
        "propietario_id": propietario_id,
        "escritura_realizada": False,
    }


def ejecutar_creacion_caso_consulta_controlada(
    solicitud,
    *,
    simulacion=True,
    propietario_id=None,
    http_post=None,
    obtener_token=None,
    crm_base=None,
):
    """
    Ejecuta una insercion de Caso solo si todas
    las protecciones estan habilitadas.

    No actualiza registros existentes.
    No realiza envios sin un cliente HTTP explicito.
    """

    import os

    def bloqueado(motivo):
        return {
            "estado": "bloqueado",
            "motivo": motivo,
            "envio_intentado": False,
            "creacion_confirmada": False,
        }

    escritura_general = (
        os.getenv("RETELL_CRM_WRITES_ENABLED", "false")
        .strip().lower() == "true"
    )

    escritura_casos = (
        os.getenv("RETELL_CASES_WRITES_ENABLED", "false")
        .strip().lower() == "true"
    )

    autorizacion = comprobar_autorizacion_creacion_caso(
        solicitud,
        simulacion=simulacion,
        crm_writes_enabled=escritura_general,
        cases_writes_enabled=escritura_casos,
        propietario_id=propietario_id,
    )

    if (
        autorizacion.get("estado")
        != "condiciones_preliminares_cumplidas"
    ):
        return bloqueado(
            autorizacion.get("motivo", "no_autorizado")
        )

    if not callable(http_post):
        return bloqueado("cliente_http_no_configurado")

    if not callable(obtener_token):
        return bloqueado("autenticacion_no_configurada")


    # Solo permitir escrituras en Zoho CRM Sandbox.
    # Nunca aceptar el dominio de produccion.
    sandbox_base_permitida = (
        "https://sandbox.zohoapis.com/crm/v8"
    )

    if (
        not isinstance(crm_base, str)
        or crm_base.rstrip("/") != sandbox_base_permitida
    ):
        return bloqueado("escritura_fuera_sandbox")


    # Validar nuevamente la integridad del Caso.
    campos = solicitud["payload"]["data"][0]

    call_id = campos["ID_de_llamada_Retell"]

    huella = hashlib.sha256(
        call_id.encode("utf-8")
    ).hexdigest()[:24].upper()

    asuntos_validos = {
        f"SOFIA_CONSULTA_{huella}",
        f"SOFIA_POSTVENTA_{huella}",
    }

    if (
        campos.get("Subject") not in asuntos_validos
        or campos.get("Status") != "New"
        or campos.get("Case_Origin") != "Tel\u00e9fono"
        or solicitud["payload"].get("trigger") != []
    ):
        return bloqueado("campos_inconsistentes")

    permitidos = {
        "Subject",
        "Status",
        "Case_Origin",
        "ID_de_llamada_Retell",
        "Description",
        "Priority",
    }

    if not set(campos).issubset(permitidos):
        return bloqueado("campos_no_autorizados")

    # No modificar el borrador original.
    campos_envio = campos.copy()

    # El propietario se agrega solo en el envio,
    # despues de superar las validaciones.
    campos_envio["Owner"] = {
        "id": propietario_id
    }

    cuerpo = {
        "data": [campos_envio],
        "trigger": [],
    }

    try:
        token = obtener_token()

        if not isinstance(token, str) or not token.strip():
            return bloqueado("token_no_disponible")

    except Exception:
        return bloqueado("error_autenticacion")

    # A partir de aqui podria existir un intento
    # de escritura: no reintentar automaticamente.
    try:
        respuesta = http_post(
            f"{crm_base.rstrip('/')}/Cases",
            headers={
                "Authorization": f"Zoho-oauthtoken {token}",
                "Content-Type": "application/json",
            },
            json=cuerpo,
            timeout=10,
        )

        resultado = interpretar_respuesta_creacion_caso_consulta(
            respuesta.status_code,
            respuesta.json(),
        )

        return {
            **resultado,
            "envio_intentado": True,
            "creacion_confirmada": (
                resultado.get("estado") == "creado"
            ),
        }

    except Exception:
        return {
            "estado": "resultado_incierto",
            "registro_id": None,
            "envio_intentado": True,
            "creacion_confirmada": False,
        }


def procesar_creacion_caso_consulta(
    clasificacion,
    *,
    consultar_asunto,
    consultar_call_id,
    simulacion=True,
    propietario_id=None,
    http_post=None,
    obtener_token=None,
    crm_base=None,
):
    """
    Coordina la verificacion y posible creacion
    de un Caso de consulta general de Sofia.

    Por defecto funciona en simulacion.
    No modifica Casos existentes.
    """

    def bloquear(motivo):
        return {
            "estado": "bloqueado",
            "motivo": motivo,
            "envio_intentado": False,
            "creacion_confirmada": False,
        }

    # 1. Verificar existencia mediante ambos controles.
    decision = verificar_caso_consulta_con_doble_control(
        clasificacion,
        consultar_asunto,
        consultar_call_id,
    )

    estado = decision.get("estado")

    # 2. Si ya existe o hay un error, no crear.
    if estado != "creacion_pendiente":
        return {
            **decision,
            "envio_intentado": False,
            "creacion_confirmada": False,
        }

    # 3. Preparar una insercion nueva.
    try:
        solicitud = preparar_solicitud_creacion_caso_consulta(
            decision
        )
    except Exception:
        return bloquear("solicitud_invalida")

    # 4. En simulacion nunca enviar solicitudes.
    if simulacion is not False:
        return {
            "estado": "creacion_simulada",
            "call_id": decision["call_id"],
            "envio_intentado": False,
            "creacion_confirmada": False,
        }


    # 5. Intentar la creacion con las protecciones
    # adicionales habilitadas.
    resultado_insercion = ejecutar_creacion_caso_consulta_controlada(
        solicitud,
        simulacion=False,
        propietario_id=propietario_id,
        http_post=http_post,
        obtener_token=obtener_token,
        crm_base=crm_base,
    )

    # 6. Ante un duplicado o un resultado incierto,
    # consultar nuevamente sin repetir la insercion.
    if not isinstance(resultado_insercion, dict):
        return {
            "estado": "resultado_incierto",
            "envio_intentado": True,
            "creacion_confirmada": False,
            "reintento_automatico": False,
        }

    if resultado_insercion.get("estado") in {
        "duplicado_detectado",
        "resultado_incierto",
    }:
        return verificar_caso_despues_de_insercion(
            clasificacion,
            resultado_insercion,
            consultar_asunto,
            consultar_call_id,
        )

    return resultado_insercion



def verificar_caso_despues_de_insercion(
    clasificacion,
    resultado_insercion,
    consultar_asunto,
    consultar_call_id,
):
    """
    Revisa una insercion duplicada o incierta.

    Solo utiliza las funciones de consulta recibidas.
    Nunca crea ni modifica Casos.
    Nunca autoriza reintentos automaticos.
    """

    no_confirmado = {
        "estado": "resultado_incierto",
        "motivo": "verificacion_posterior_no_confirmada",
        "envio_intentado": True,
        "creacion_confirmada": False,
        "reintento_automatico": False,
    }

    if not isinstance(resultado_insercion, dict):
        return no_confirmado

    if resultado_insercion.get("estado") not in {
        "duplicado_detectado",
        "resultado_incierto",
    }:
        return {
            **no_confirmado,
            "motivo": "estado_insercion_no_admitido",
        }

    try:
        decision = verificar_caso_consulta_con_doble_control(
            clasificacion,
            consultar_asunto,
            consultar_call_id,
        )
    except Exception:
        return no_confirmado

    if (
        not isinstance(decision, dict)
        or decision.get("estado") != "ya_registrado"
    ):
        return no_confirmado

    registro_id = decision.get("registro_id")

    if (
        not isinstance(registro_id, str)
        or not registro_id.strip()
    ):
        return no_confirmado

    return {
        "estado": "ya_registrado",
        "registro_id": registro_id,
        "envio_intentado": True,
        "creacion_confirmada": False,
        "verificacion_posterior": "confirmada",
        "reintento_automatico": False,
    }
