
import os
import requests



def obtener_historial_retell(
    agent_id,
    limite_por_pagina=50,
    max_paginas=5,
    inicio_ms=None,
    fin_ms=None,
):

    """
    Recupera llamadas de Retell con paginacion.

    Solo consulta Retell.
    No crea ni modifica registros en Zoho CRM.
    """

    if not isinstance(agent_id, str) or not agent_id.strip():
        raise ValueError("Agent ID invalido")

    if (
        type(limite_por_pagina) is not int
        or not 1 <= limite_por_pagina <= 100
    ):
        raise ValueError("Limite por pagina invalido")

    if (
        type(max_paginas) is not int
        or not 1 <= max_paginas <= 10
    ):
        raise ValueError("Numero de paginas invalido")


    # El rango de fechas es opcional, pero debe
    # estar completo si se utiliza.
    usar_fechas = (
        inicio_ms is not None
        or fin_ms is not None
    )

    if usar_fechas:
        if (
            type(inicio_ms) is not int
            or type(fin_ms) is not int
            or inicio_ms <= 0
            or fin_ms <= inicio_ms
        ):
            raise ValueError(
                "Rango de fechas invalido"
            )


    api_key = os.getenv("RETELL_API_KEY")

    if not api_key:
        raise RuntimeError("Falta RETELL_API_KEY")

    llamadas = []
    paginacion = None
    cursores_usados = set()

    for numero_pagina in range(1, max_paginas + 1):


        parametros = {
            "limit": limite_por_pagina,
            "sort_order": "descending",
            "filter_criteria": {
                "agent": [
                    {"agent_id": agent_id}
                ]
            },
        }


        # Aplicar fechas solo cuando se soliciten.
        if usar_fechas:
            parametros["filter_criteria"][
                "start_timestamp"
            ] = {
                "type": "range",
                "op": "bt",
                "value": [inicio_ms, fin_ms],
            }



        if paginacion:
            parametros["pagination_key"] = paginacion

        respuesta = requests.post(
            "https://api.retellai.com/v3/list-calls",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=parametros,
            timeout=20,
        )

        respuesta.raise_for_status()
        contenido = respuesta.json()

        if not isinstance(contenido, dict):
            raise RuntimeError("Respuesta Retell invalida")

        items = contenido.get("items")
        has_more = contenido.get("has_more")

        if not isinstance(items, list):
            raise RuntimeError("Lista de llamadas invalida")

        if not isinstance(has_more, bool):
            raise RuntimeError("Indicador de paginacion invalido")

        if not all(isinstance(item, dict) for item in items):
            raise RuntimeError("Registro de llamada invalido")

        for llamada in items:
            if llamada.get("agent_id") == agent_id:
                llamadas.append(llamada)

        if not has_more:
            return {
                "llamadas": llamadas,
                "paginas": numero_pagina,
                "completa": True,
            }

        siguiente = contenido.get("pagination_key")

        if (
            not isinstance(siguiente, str)
            or not siguiente.strip()
            or siguiente in cursores_usados
        ):
            raise RuntimeError(
                "Paginacion incompleta o repetida"
            )

        cursores_usados.add(siguiente)
        paginacion = siguiente

    return {
        "llamadas": llamadas,
        "paginas": max_paginas,
        "completa": False,
    }



def obtener_historial_sofia_por_periodos(
    agent_id,
    inicio_ms,
    fin_ms,
    ventana_ms=86400000,
    max_ventanas=31,
):
    """
    Recupera llamadas por periodos y elimina duplicados.

    Solo consulta Retell.
    No modifica Zoho CRM ni otros sistemas.
    """

    if not isinstance(agent_id, str) or not agent_id.strip():
        raise ValueError("Agent ID invalido")

    if (
        type(inicio_ms) is not int
        or type(fin_ms) is not int
        or inicio_ms <= 0
        or fin_ms <= inicio_ms
    ):
        raise ValueError("Rango temporal invalido")

    if (
        type(ventana_ms) is not int
        or ventana_ms < 1
    ):
        raise ValueError("Ventana temporal invalida")

    if (
        type(max_ventanas) is not int
        or not 1 <= max_ventanas <= 366
    ):
        raise ValueError("Limite de ventanas invalido")

    cantidad_ventanas = (
        fin_ms - inicio_ms + ventana_ms - 1
    ) // ventana_ms

    if cantidad_ventanas > max_ventanas:
        raise ValueError(
            "El rango supera el limite de ventanas"
        )


    # Recuperar una ventana y subdividirla si
    # Retell informa que el historial esta incompleto.
    consultas_ventanas = 0
    subdivisiones = 0

    def recuperar_ventana(inicio, fin, nivel=0):
        nonlocal consultas_ventanas, subdivisiones

        # Limite para evitar consultas excesivas.
        if consultas_ventanas >= 100:
            raise RuntimeError(
                "Limite de consultas Retell alcanzado"
            )

        consultas_ventanas += 1

        resultado = obtener_historial_retell(
            agent_id,
            limite_por_pagina=50,
            max_paginas=5,
            inicio_ms=inicio,
            fin_ms=fin,
        )

        if not isinstance(resultado, dict):
            raise RuntimeError(
                "Respuesta de ventana invalida"
            )

        llamadas = resultado.get("llamadas")
        paginas = resultado.get("paginas")
        completa = resultado.get("completa")

        if (
            not isinstance(llamadas, list)
            or type(paginas) is not int
            or paginas < 1
            or type(completa) is not bool
        ):
            raise RuntimeError(
                "Datos de ventana invalidos"
            )

        if completa:
            return resultado

        # No continuar si la ventana es demasiado
        # pequena o supera el limite de divisiones.
        if nivel >= 18 or fin - inicio <= 1:
            raise RuntimeError(
                "Ventana saturada no divisible"
            )

        mitad = inicio + (fin - inicio) // 2

        subdivisiones += 1

        izquierda = recuperar_ventana(
            inicio,
            mitad,
            nivel + 1,
        )

        derecha = recuperar_ventana(
            mitad,
            fin,
            nivel + 1,
        )

        # Los limites pueden incluir la misma llamada.
        # La funcion principal eliminara duplicados.
        return {
            "llamadas": (
                izquierda["llamadas"]
                + derecha["llamadas"]
            ),
            "paginas": (
                paginas
                + izquierda["paginas"]
                + derecha["paginas"]
            ),
            "completa": True,
        }


    llamadas_por_id = {}
    duplicados = 0
    paginas_totales = 0
    ventanas_revisadas = 0

    inicio_actual = inicio_ms

    while inicio_actual < fin_ms:

        fin_actual = min(
            inicio_actual + ventana_ms,
            fin_ms,
        )

        historial = recuperar_ventana(
            inicio_actual,
            fin_actual,
        )

        # No aceptar un resultado parcial.
        if historial.get("completa") is not True:
            raise RuntimeError(
                "Ventana con historial incompleto"
            )

        llamadas = historial.get("llamadas")

        if not isinstance(llamadas, list):
            raise RuntimeError(
                "Lista de llamadas invalida"
            )

        paginas = historial.get("paginas")

        if type(paginas) is not int or paginas < 1:
            raise RuntimeError(
                "Numero de paginas invalido"
            )

        # Validar toda la respuesta de esta ventana.
        for llamada in llamadas:

            if not isinstance(llamada, dict):
                raise RuntimeError(
                    "Registro de llamada invalido"
                )

            call_id = llamada.get("call_id")
            agente = llamada.get("agent_id")
            timestamp = llamada.get("start_timestamp")

            if (
                not isinstance(call_id, str)
                or not call_id.strip()
            ):
                raise RuntimeError(
                    "Call ID invalido"
                )

            if agente != agent_id:
                raise RuntimeError(
                    "Llamada de otro agente"
                )

            if type(timestamp) is not int:
                raise RuntimeError(
                    "Timestamp de llamada invalido"
                )

            if not inicio_actual <= timestamp <= fin_actual:
                raise RuntimeError(
                    "Llamada fuera del periodo"
                )

            # Un mismo Call ID debe mantener su fecha.
            anterior = llamadas_por_id.get(call_id)

            if anterior is not None:

                if (
                    anterior.get("start_timestamp")
                    != timestamp
                ):
                    raise RuntimeError(
                        "Call ID con fechas inconsistentes"
                    )

                duplicados += 1

            # Conservar una sola version por Call ID.
            llamadas_por_id[call_id] = llamada

        paginas_totales += paginas
        ventanas_revisadas += 1
        inicio_actual = fin_actual

    # Recuperar el mismo orden descendente de Retell.
    llamadas_unicas = sorted(
        llamadas_por_id.values(),
        key=lambda llamada: (
            llamada["start_timestamp"],
            llamada["call_id"],
        ),
        reverse=True,
    )

    return {
        "llamadas": llamadas_unicas,
        "paginas": paginas_totales,
        "completa": True,
        "ventanas": ventanas_revisadas,
        "duplicados_eliminados": duplicados,
        "consultas_ventanas": consultas_ventanas,
        "subdivisiones": subdivisiones,
    }
