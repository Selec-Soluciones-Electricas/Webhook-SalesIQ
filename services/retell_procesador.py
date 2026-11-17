
import os

from services.retell_historial import (
    obtener_historial_retell,
)
from services.retell_recuperacion import (
    clasificar_llamada_recuperacion,
)
from services.retell_cotizaciones import (
    registrar_cotizacion_retell,
)


def dividir_cotizaciones_en_lotes(
    candidatas,
    tamano_lote=30,
):
    """
    Divide las cotizaciones candidatas en lotes.

    Mantiene el orden original de las llamadas.

    No consulta Retell ni Zoho CRM.
    No crea ni modifica registros.
    No depende de la hora ni de un turno.
    """

    if not isinstance(candidatas, list):
        raise TypeError(
            "candidatas debe ser una lista"
        )

    if (
        isinstance(tamano_lote, bool)
        or not isinstance(tamano_lote, int)
        or tamano_lote < 1
    ):
        raise ValueError(
            "tamano_lote debe ser un entero positivo"
        )

    lotes = []

    for inicio in range(
        0,
        len(candidatas),
        tamano_lote,
    ):
        fin = inicio + tamano_lote

        lotes.append(
            candidatas[inicio:fin]
        )

    return {
        "lotes": lotes,
        "total_lotes": len(lotes),
        "total_candidatas": len(candidatas),
        "tamano_lote": tamano_lote,
    }


def seleccionar_pendientes_por_lotes(
    candidatas,
    limite_llamadas,
    consultar_call_id,
    tamano_lote=30,
    max_consultas_total=90,
):
    """
    Recorre las cotizaciones por lotes y selecciona
    solamente las que no aparecen en Zoho CRM.

    No crea ni modifica registros.

    Ante un error de consulta, descarta la seleccion
    parcial para evitar procesamientos inciertos.
    """

    if (
        isinstance(limite_llamadas, bool)
        or not isinstance(limite_llamadas, int)
        or limite_llamadas < 1
    ):
        raise ValueError("limite_llamadas invalido")

    if (
        isinstance(max_consultas_total, bool)
        or not isinstance(max_consultas_total, int)
        or max_consultas_total < 1
    ):
        raise ValueError("max_consultas_total invalido")

    if not callable(consultar_call_id):
        raise TypeError("consultar_call_id debe ser callable")

    division = dividir_cotizaciones_en_lotes(
        candidatas,
        tamano_lote=tamano_lote,
    )

    seleccionadas = []
    ya_registradas = 0
    consultas_total = 0
    lotes_revisados = 0

    for lote in division["lotes"]:

        # Detenerse cuando no queden cupos o consultas
        if len(seleccionadas) >= limite_llamadas:
            break

        if consultas_total >= max_consultas_total:
            break

        consultas_disponibles = (
            max_consultas_total - consultas_total
        )

        limite_lote = min(
            len(lote),
            consultas_disponibles,
        )

        cupos_disponibles = (
            limite_llamadas - len(seleccionadas)
        )

        resultado = seleccionar_cotizaciones_no_registradas(
            lote,
            limite_llamadas=cupos_disponibles,
            consultar_call_id=consultar_call_id,
            limite_consultas=limite_lote,
        )

        lotes_revisados += 1

        consultas_total += resultado["consultas_zoho"]

        ya_registradas += resultado["ya_registradas"]

        # Fallo de Zoho: no utilizar seleccion parcial
        if resultado["error_consulta"]:
            return {
                "estado": "error_consulta",
                "seleccionadas": [],
                "ya_registradas": ya_registradas,
                "consultas_zoho": consultas_total,
                "lotes_revisados": lotes_revisados,
                "total_lotes": division["total_lotes"],
                "barrido_completo": False,
            }

        seleccionadas.extend(
            resultado["seleccionadas"]
        )

    barrido_completo = (
        consultas_total == len(candidatas)
    )

    if barrido_completo:
        estado = "completo"

    elif len(seleccionadas) >= limite_llamadas:
        estado = "limite_llamadas"

    else:
        estado = "limite_consultas"

    return {
        "estado": estado,
        "seleccionadas": seleccionadas,
        "ya_registradas": ya_registradas,
        "consultas_zoho": consultas_total,
        "lotes_revisados": lotes_revisados,
        "total_lotes": division["total_lotes"],
        "barrido_completo": barrido_completo,
    }


def obtener_ventana_rotativa(
    candidatas,
    limite_consultas=30,
    turno=None,
):
    """
    Divide las llamadas candidatas en ventanas.

    Cada ventana contiene como maximo limite_consultas
    llamadas.

    Si no se indica turno, utiliza la hora UTC actual.
    No necesita una base de datos ni guardar estado.
    """

    from datetime import datetime, timezone

    if limite_consultas < 1:
        raise ValueError(
            "limite_consultas debe ser mayor que cero"
        )

    if turno is None:
        turno = int(
            datetime.now(timezone.utc).timestamp() // 3600
        )

    if not isinstance(turno, int) or turno < 0:
        raise ValueError(
            "turno debe ser un entero no negativo"
        )

    total_llamadas = len(candidatas)

    if total_llamadas == 0:
        return {
            "llamadas": [],
            "ventana_actual": 0,
            "total_ventanas": 0,
            "otras_ventanas": 0,
        }

    total_ventanas = (
        total_llamadas + limite_consultas - 1
    ) // limite_consultas

    indice_ventana = turno % total_ventanas

    inicio = indice_ventana * limite_consultas
    fin = min(
        inicio + limite_consultas,
        total_llamadas,
    )

    ventana = candidatas[inicio:fin]

    return {
        "llamadas": ventana,
        "ventana_actual": indice_ventana + 1,
        "total_ventanas": total_ventanas,
        "otras_ventanas": total_llamadas - len(ventana),
    }


def seleccionar_cotizaciones_no_registradas(
    candidatas,
    limite_llamadas,
    consultar_call_id,
    limite_consultas=30,
):
    """
    Selecciona cotizaciones que no aparecen en Zoho.

    Las cotizaciones ya registradas no ocupan cupos.

    Si una consulta falla, detiene la seleccion
    para evitar decisiones con datos inciertos.

    consultar_call_id es la funcion encargada de
    buscar el negocio por su Retell_Call_ID.
    """

    if limite_llamadas < 1 or limite_consultas < 1:
        raise ValueError(
            "Los limites deben ser mayores que cero"
        )

    seleccionadas = []
    ya_registradas = 0
    consultas = 0
    error_consulta = False

    for llamada in candidatas:

        if len(seleccionadas) >= limite_llamadas:
            break

        if consultas >= limite_consultas:
            break

        call_id = llamada.get("call_id")

        if not call_id:
            error_consulta = True
            break

        consultas += 1

        try:
            resultado = consultar_call_id(call_id)
        except Exception:
            error_consulta = True
            break

        if not isinstance(resultado, dict):
            error_consulta = True
            break

        estado = resultado.get("estado")

        if estado == "encontrado":

            if not resultado.get("negocio_id"):
                error_consulta = True
                break

            ya_registradas += 1
            continue

        if estado == "no_encontrado":
            seleccionadas.append(llamada)
            continue

        # Error o respuesta desconocida de Zoho.
        error_consulta = True
        break

    return {
        "seleccionadas": seleccionadas,
        "ya_registradas": ya_registradas,
        "consultas_zoho": consultas,
        "error_consulta": error_consulta,

        "limite_consultas_alcanzado": (
            consultas >= limite_consultas
            and len(seleccionadas) < limite_llamadas
            and consultas < len(candidatas)
        ),
    }



def procesar_pendientes_sofia(
    agent_id,
    max_paginas=5,
    limite_llamadas=10,
    simulacion=True,
    turno=None,
    usar_busqueda_multiple=False,
    inicio_ms=None,
    fin_ms=None,
):



    """
    Recupera y procesa cotizaciones telefonicas de Sofia.

    Por defecto solo simula el procesamiento.

    Para permitir escrituras se necesitan ambas condiciones:
    - simulacion=False
    - RETELL_CRM_WRITES_ENABLED=true
    """

    agente_autorizado = (
        os.getenv("RETELL_SOFIA_AGENT_ID") or ""
    ).strip()

    if not agente_autorizado or agent_id != agente_autorizado:
        return {
            "estado": "agente_no_autorizado",
            "resultados": [],
        }

    modo_real = simulacion is False

    escritura_habilitada = (
        os.getenv("RETELL_CRM_WRITES_ENABLED", "false")
        .strip()
        .lower()
        == "true"
    )

    if modo_real and not escritura_habilitada:
        return {
            "estado": "registro_desactivado",
            "resultados": [],
        }

    if limite_llamadas < 1:
        raise ValueError(
            "limite_llamadas debe ser mayor que cero"
        )


    # Verificar que las fechas se indiquen juntas.
    if (inicio_ms is None) != (fin_ms is None):
        raise ValueError(
            "Debe indicar inicio_ms y fin_ms"
        )

    # Seleccionar el metodo de recuperacion.
    if inicio_ms is not None:

        from services.retell_historial import (
            obtener_historial_sofia_por_periodos,
        )

        # Recuperacion por periodos.
        historial = obtener_historial_sofia_por_periodos(
            agent_id,
            inicio_ms=inicio_ms,
            fin_ms=fin_ms,
            ventana_ms=86400000,
            max_ventanas=31,
        )

    else:

        # Recuperacion habitual.
        # Mantener compatibilidad con el sistema actual.
        historial = obtener_historial_retell(
            agent_id,
            limite_por_pagina=50,
            max_paginas=max_paginas,
        )


    llamadas = historial["llamadas"]

    # Evitar procesar un historial truncado.
    if not historial["completa"]:
        return {
            "estado": "historial_incompleto",
            "llamadas_revisadas": len(llamadas),
            "paginas": historial["paginas"],
            "resultados": [],
        }


    candidatas = []
    revisiones_detectadas = []
    postventas_detectadas = []
    consultas_detectadas = []
    consultas_en_revision = []

    # Revisar primero las llamadas mas antiguas.
    for llamada in reversed(llamadas):

        clasificacion = clasificar_llamada_recuperacion(
            llamada,
            agente_autorizado,
        )

        estado = clasificacion.get("estado")

        if estado == "candidata":
            candidatas.append(llamada)

        elif estado == "revision":

            faltantes = clasificacion.get("faltantes")

            if not isinstance(faltantes, list):
                faltantes = []

            revisiones_detectadas.append({
                "call_id": (
                    llamada.get("call_id")
                    if isinstance(llamada, dict)
                    else None
                ),
                "motivo": clasificacion.get(
                    "motivo",
                    "sin_motivo",
                ),
                "faltantes": faltantes.copy(),
            })


        elif (
            estado == "otra_solicitud"
            and clasificacion.get("tipo") == "postventa"
        ):
            from services.retell_postventas import (
                clasificar_postventa_sofia,
            )

            postventa = clasificar_postventa_sofia(
                llamada,
                agente_autorizado,
            )

            if (
                isinstance(postventa, dict)
                and postventa.get("estado") == "candidata_caso"
            ):
                postventas_detectadas.append({
                    **postventa,
                    "tipo": "postventa",
                })

            else:
                # No descartar postventas incompletas.
                # Deben quedar pendientes de revision.
                revisiones_detectadas.append({
                    "call_id": llamada.get("call_id"),
                    "motivo": (
                        postventa.get(
                            "motivo",
                            "postventa_no_confirmada",
                        )
                        if isinstance(postventa, dict)
                        else "respuesta_invalida"
                    ),
                    "faltantes": [],
                })


        elif (
            estado == "otra_solicitud"
            and clasificacion.get("tipo") == "consulta"
        ):
            from services.retell_consultas import (
                clasificar_consulta_sofia,
            )

            consulta = clasificar_consulta_sofia(
                llamada,
                agente_autorizado,
            )

            if (
                isinstance(consulta, dict)
                and consulta.get("estado") == "candidata_caso"
            ):
                consultas_detectadas.append(consulta)

            else:
                # No descartar silenciosamente una consulta
                # que no pudo confirmarse como candidata.
                consultas_en_revision.append({
                    "call_id": (
                        llamada.get("call_id")
                        if isinstance(llamada, dict)
                        else None
                    ),
                    "estado_clasificacion": (
                        consulta.get("estado", "sin_estado")
                        if isinstance(consulta, dict)
                        else "respuesta_invalida"
                    ),
                    "motivo": (
                        consulta.get("motivo", "sin_motivo")
                        if isinstance(consulta, dict)
                        else "respuesta_invalida"
                    ),
                })





    # Seleccionar llamadas segun el modo de ejecucion
    if simulacion:

        # En simulacion no se consulta Zoho CRM
        seleccionadas = candidatas[:limite_llamadas]

        resumen_seleccion = {
            "ya_registradas": 0,
            "consultas_zoho": 0,
            "error_consulta": False,
            "limite_consultas_alcanzado": False,
        }

    else:


        # Seleccionar el metodo de busqueda.
        # El metodo individual sigue siendo el predeterminado.

        if usar_busqueda_multiple:

            from services.retell_duplicados import (
                buscar_negocios_por_call_ids,
            )

            # Metodo experimental: no validado todavia
            # con coincidencias positivas reales.
            resumen_multiple = (
                seleccionar_pendientes_busqueda_multiple(
                    candidatas,
                    limite_llamadas=limite_llamadas,
                    consultar_lote=buscar_negocios_por_call_ids,
                    tamano_lote=30,
                    max_lotes=10,
                )
            )

            # Adaptar los campos al formato que ya
            # utiliza el procesador principal.
            resumen_barrido = {
                **resumen_multiple,
                "lotes_revisados": (
                    resumen_multiple["consultas_api"]
                ),
                "consultas_zoho": (
                    resumen_multiple["consultas_api"]
                ),
            }

        else:

            from services.retell_duplicados import (
                buscar_negocio_por_call_id,
            )

            # Metodo individual ya probado.
            resumen_barrido = seleccionar_pendientes_por_lotes(
                candidatas,
                limite_llamadas=limite_llamadas,
                consultar_call_id=buscar_negocio_por_call_id,
                tamano_lote=30,
                max_consultas_total=90,
            )


        print(
            "[RETELL] Resultado del barrido:",
            resumen_barrido["estado"],
            "| Lotes:",
            resumen_barrido["lotes_revisados"],
            "de",
            resumen_barrido["total_lotes"],
            "| Consultas:",
            resumen_barrido["consultas_zoho"],
        )

        # Evitar procesar selecciones inciertas o incompletas

        if resumen_barrido["estado"] in {
            "error_consulta",
            "limite_consultas",
            "limite_lotes",
        }:

            print(
                "[RETELL] Barrido detenido por seguridad:",
                resumen_barrido["estado"],
            )

            return {
                "estado": "seleccion_no_confirmada",
                "motivo": resumen_barrido["estado"],
                "llamadas_revisadas": len(llamadas),
                "paginas": historial["paginas"],
                "historial_completo": historial["completa"],
                "candidatas": len(candidatas),
                "seleccionadas": 0,
                "ya_registradas": (
                    resumen_barrido["ya_registradas"]
                ),
                "consultas_zoho": (
                    resumen_barrido["consultas_zoho"]
                ),
                "lotes_revisados": (
                    resumen_barrido["lotes_revisados"]
                ),
                "barrido_completo": (
                    resumen_barrido["barrido_completo"]
                ),
                "resultados": [],

                "total_revisiones_detectadas": len(
                    revisiones_detectadas
                ),
                "revisiones_detectadas": revisiones_detectadas,

                "total_postventas_detectadas": len(
                    postventas_detectadas
                ),
                "postventas_detectadas": postventas_detectadas,

            }

        seleccionadas = resumen_barrido["seleccionadas"]

        # Mantener compatibilidad con el resumen final
        resumen_seleccion = {
            "ya_registradas": resumen_barrido["ya_registradas"],
            "consultas_zoho": resumen_barrido["consultas_zoho"],
        }



    resultados = []

    for llamada in seleccionadas:

        call_id = llamada.get("call_id")

        if simulacion:
            resultados.append({
                "call_id": call_id,
                "estado": "simulada",
            })
            continue

        try:
            registro = registrar_cotizacion_retell(
                llamada
            )

            resultados.append({
                "call_id": call_id,
                "estado": registro.get(
                    "estado",
                    "desconocido",
                ),
            })

        except Exception as error:
            print(
                "[RETELL] Error procesando llamada:",
                call_id,
                "|",
                type(error).__name__,
            )

            resultados.append({
                "call_id": call_id,
                "estado": "error_procesamiento",
            })


    # Clasificar el resultado de todas las cotizaciones
    estados_correctos = {
        "creado",
        "duplicado",
    }

    estados_pendientes = {
        "pendiente_verificacion",
        "pendiente_empresa",
        "pendiente_contacto",
        "error_consulta",
    }

    resumen_registros = {
        "correctos": 0,
        "pendientes": 0,
        "revision": 0,
        "errores": 0,
        "simulados": 0,
    }

    for item in resultados:
        estado = item.get("estado")

        if estado == "simulada":
            resumen_registros["simulados"] += 1

        elif estado in estados_correctos:
            resumen_registros["correctos"] += 1

        elif estado in estados_pendientes:
            resumen_registros["pendientes"] += 1

        elif estado == "revision":
            resumen_registros["revision"] += 1

        else:
            # Excepciones y estados desconocidos
            resumen_registros["errores"] += 1

    # Determinar el estado general de la ejecucion
    if simulacion:
        estado_general = "simulacion"

    elif resumen_registros["errores"] > 0:
        estado_general = "procesamiento_con_errores"

    elif resumen_registros["pendientes"] > 0:
        estado_general = "procesamiento_con_pendientes"


    elif (
        resumen_registros["revision"] > 0
        or len(revisiones_detectadas) > 0
    ):
        estado_general = "procesamiento_con_revision"


    else:
        estado_general = "procesamiento_ejecutado"


    return {
        "estado": estado_general,
        "llamadas_revisadas": len(llamadas),
        "paginas": historial["paginas"],
        "historial_completo": historial["completa"],
        "candidatas": len(candidatas),
        "seleccionadas": len(seleccionadas),

        "pendientes_fuera_de_limite": max(
            0,
            len(candidatas)
            - len(seleccionadas)
            - resumen_seleccion["ya_registradas"],
        ),
        "ya_registradas": (
            resumen_seleccion["ya_registradas"]
        ),
        "consultas_zoho": (
            resumen_seleccion["consultas_zoho"]
        ),
        "resumen_registros": resumen_registros,

        "total_revisiones_detectadas": len(
            revisiones_detectadas
        ),
        "revisiones_detectadas": revisiones_detectadas,

        "total_postventas_detectadas": len(
            postventas_detectadas
        ),
        "postventas_detectadas": postventas_detectadas,

        "total_consultas_detectadas": len(
            consultas_detectadas
        ),
        "consultas_detectadas": consultas_detectadas,

        "resultados": resultados,

        "total_consultas_en_revision": len(
            consultas_en_revision
        ),
        "consultas_en_revision": consultas_en_revision,


    }



def seleccionar_pendientes_busqueda_multiple(
    candidatas,
    limite_llamadas,
    consultar_lote,
    tamano_lote=30,
    max_lotes=10,
):
    """
    Selecciona cotizaciones pendientes consultando
    varios Call ID en cada peticion a Zoho.

    No crea ni modifica registros.
    Ante errores descarta toda seleccion parcial.
    """

    if not isinstance(candidatas, list):
        raise TypeError("candidatas debe ser una lista")

    if (
        not isinstance(limite_llamadas, int)
        or isinstance(limite_llamadas, bool)
        or limite_llamadas < 1
    ):
        raise ValueError("limite_llamadas invalido")

    if (
        not isinstance(max_lotes, int)
        or isinstance(max_lotes, bool)
        or max_lotes < 1
    ):
        raise ValueError("max_lotes invalido")

    if (
        not isinstance(tamano_lote, int)
        or isinstance(tamano_lote, bool)
        or not 1 <= tamano_lote <= 30
    ):
        raise ValueError("tamano_lote invalido")

    if not callable(consultar_lote):
        raise TypeError("consultar_lote invalido")

    # Validar identificadores antes de consultar Zoho.
    ids = []

    for llamada in candidatas:
        if not isinstance(llamada, dict):
            raise ValueError("Llamada invalida")

        call_id = llamada.get("call_id")

        if (
            not isinstance(call_id, str)
            or not call_id
            or call_id != call_id.strip()
        ):
            raise ValueError("Call ID invalido")

        ids.append(call_id)

    if len(ids) != len(set(ids)):
        raise ValueError("Call ID duplicado en historial")

    division = dividir_cotizaciones_en_lotes(
        candidatas,
        tamano_lote=tamano_lote,
    )

    seleccionadas = []
    ya_registradas = 0
    llamadas_revisadas = 0
    consultas_api = 0

    def fallo():
        return {
            "estado": "error_consulta",
            "seleccionadas": [],
            "ya_registradas": ya_registradas,
            "llamadas_revisadas": llamadas_revisadas,
            "consultas_api": consultas_api,
            "total_lotes": division["total_lotes"],
            "barrido_completo": False,
        }

    for lote in division["lotes"][:max_lotes]:

        ids_lote = [
            llamada["call_id"]
            for llamada in lote
        ]

        consultas_api += 1

        try:
            respuesta = consultar_lote(ids_lote)
        except Exception:
            return fallo()

        if (
            not isinstance(respuesta, dict)
            or respuesta.get("estado") != "ok"
        ):
            return fallo()

        resultados = respuesta.get("resultados")

        if (
            not isinstance(resultados, dict)
            or set(resultados) != set(ids_lote)
        ):
            return fallo()

        # Validar el lote completo antes de seleccionarlo.
        for call_id in ids_lote:
            item = resultados.get(call_id)

            if not isinstance(item, dict):
                return fallo()

            estado = item.get("estado")

            if estado == "encontrado":
                if not item.get("negocio_id"):
                    return fallo()

            elif estado == "no_encontrado":
                if item.get("negocio_id") is not None:
                    return fallo()

            else:
                return fallo()

        # Solo utilizar resultados ya validados.
        llamadas_revisadas += len(lote)

        for llamada in lote:
            call_id = llamada["call_id"]
            estado = resultados[call_id]["estado"]

            if estado == "encontrado":
                ya_registradas += 1

            elif len(seleccionadas) < limite_llamadas:
                seleccionadas.append(llamada)

        if len(seleccionadas) >= limite_llamadas:
            break

    barrido_completo = (
        llamadas_revisadas == len(candidatas)
    )

    if barrido_completo:
        estado = "completo"
    elif len(seleccionadas) >= limite_llamadas:
        estado = "limite_llamadas"
    else:
        estado = "limite_lotes"

    return {
        "estado": estado,
        "seleccionadas": seleccionadas,
        "ya_registradas": ya_registradas,
        "llamadas_revisadas": llamadas_revisadas,
        "consultas_api": consultas_api,
        "total_lotes": division["total_lotes"],
        "barrido_completo": barrido_completo,
    }
