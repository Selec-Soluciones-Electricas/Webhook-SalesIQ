
def preparar_seguimiento_humano(resultado):
    """
    Prepara las solicitudes que requieren
    seguimiento por parte del equipo de SELEC.

    No envia correos.
    No consulta ni modifica Zoho CRM.
    No realiza conexiones externas.
    """

    if not isinstance(resultado, dict):
        raise TypeError("Resultado invalido")

    pendientes = []

    fuentes = (
        ("postventas_detectadas", "postventa"),
        ("revisiones_detectadas", "revision"),
    )

    for clave, tipo in fuentes:
        solicitudes = resultado.get(clave, [])

        if not isinstance(solicitudes, list):
            raise ValueError(
                "Lista de solicitudes invalida"
            )

        for solicitud in solicitudes:
            if not isinstance(solicitud, dict):
                raise ValueError(
                    "Solicitud invalida"
                )

            call_id = solicitud.get("call_id")

            if (
                not isinstance(call_id, str)
                or not call_id.strip()
            ):
                raise ValueError(
                    "Call ID invalido"
                )

            pendiente = {
                "tipo": tipo,
                "call_id": call_id,
            }

            if tipo == "revision":
                pendiente["motivo"] = solicitud.get(
                    "motivo",
                    "sin_motivo",
                )

                faltantes = solicitud.get(
                    "faltantes", []
                )

                pendiente["faltantes"] = (
                    faltantes.copy()
                    if isinstance(faltantes, list)
                    else []
                )


            # Evitar duplicados dentro del mismo seguimiento.
            existente = next(
                (
                    item
                    for item in pendientes
                    if item["call_id"] == call_id
                ),
                None,
            )

            if existente is not None:
                if existente != pendiente:
                    raise ValueError(
                        "Call ID repetido con datos diferentes"
                    )
                continue

            pendientes.append(pendiente)


    return {
        "total_pendientes": len(pendientes),
        "total_postventas": sum(
            item["tipo"] == "postventa"
            for item in pendientes
        ),
        "total_revisiones": sum(
            item["tipo"] == "revision"
            for item in pendientes
        ),
        "pendientes": pendientes,
    }


def preparar_borradores_notificacion(seguimiento):
    """
    Genera borradores para solicitudes pendientes.

    No envia correos.
    No consulta Retell ni Zoho.
    No realiza conexiones externas.
    """

    if not isinstance(seguimiento, dict):
        raise TypeError("Seguimiento invalido")

    pendientes = seguimiento.get("pendientes")

    if not isinstance(pendientes, list):
        raise ValueError("Pendientes invalidos")

    borradores = []

    for pendiente in pendientes:
        if not isinstance(pendiente, dict):
            raise ValueError("Solicitud invalida")

        tipo = pendiente.get("tipo")
        call_id = pendiente.get("call_id")

        if tipo not in ("postventa", "revision"):
            raise ValueError("Tipo de solicitud invalido")

        if (
            not isinstance(call_id, str)
            or not call_id.strip()
            or any(c in call_id for c in "\r\n")
        ):
            raise ValueError("Call ID invalido")

        if tipo == "postventa":
            asunto = (
                "[SOFIA] Nueva solicitud de postventa"
            )

            mensaje = (
                "Se ha detectado una solicitud de postventa.\n\n"
                f"Identificador de llamada: {call_id}\n"
                "Tipo: Postventa\n\n"
                "Accion requerida:\n"
                "Revisar la llamada en Retell AI "
                "y gestionar la solicitud del cliente."
            )

        else:
            motivo = pendiente.get(
                "motivo", "sin_motivo"
            )

            if not isinstance(motivo, str):
                raise ValueError("Motivo invalido")

            faltantes = pendiente.get("faltantes", [])

            if not isinstance(faltantes, list):
                raise ValueError("Faltantes invalidos")

            asunto = (
                "[SOFIA] Llamada pendiente de revision"
            )

            mensaje = (
                "Se ha detectado una llamada "
                "que requiere revision humana.\n\n"
                f"Identificador de llamada: {call_id}\n"
                f"Motivo: {motivo}\n"
                f"Datos faltantes: {', '.join(map(str, faltantes)) or 'Ninguno'}\n\n"
                "Accion requerida:\n"
                "Revisar la llamada en Retell AI "
                "y determinar los pasos a seguir."
            )


        # Identificador estable para futuras comprobaciones
        # de notificaciones ya enviadas.
        id_notificacion = f"sofia:{tipo}:{call_id}"

        borradores.append({
            "id_notificacion": id_notificacion,
            "call_id": call_id,
            "tipo": tipo,
            "asunto": asunto,
            "mensaje": mensaje,
        })


    return {
        "total_borradores": len(borradores),
        "borradores": borradores,
    }

def seleccionar_notificaciones_pendientes(
    resultado_borradores,
    consultar_estado,
):
    """
    Selecciona las notificaciones que aun no
    han sido enviadas.

    La consulta se proporciona externamente.
    Ante errores, no autoriza notificaciones.
    """

    if not isinstance(resultado_borradores, dict):
        raise TypeError("Resultado de borradores invalido")

    borradores = resultado_borradores.get("borradores")

    if not isinstance(borradores, list):
        raise ValueError("Lista de borradores invalida")

    if not callable(consultar_estado):
        raise TypeError("Consulta de estado invalida")

    pendientes = []
    identificadores = set()
    ya_notificadas = 0

    def error_consulta():
        return {
            "estado": "error_consulta",
            "pendientes": [],
            "total_pendientes": 0,
            "ya_notificadas": 0,
        }

    for borrador in borradores:
        if not isinstance(borrador, dict):
            return error_consulta()

        identificador = borrador.get("id_notificacion")

        if (
            not isinstance(identificador, str)
            or not identificador.strip()
            or identificador in identificadores
        ):
            return error_consulta()

        identificadores.add(identificador)

        try:
            estado = consultar_estado(identificador)
        except Exception:
            return error_consulta()

        if type(estado) is not bool:
            return error_consulta()

        if estado:
            ya_notificadas += 1
        else:
            pendientes.append(borrador)

    return {
        "estado": "ok",
        "pendientes": pendientes,
        "total_pendientes": len(pendientes),
        "ya_notificadas": ya_notificadas,
    }