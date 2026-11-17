
def dividir_periodo_recuperacion(inicio_ms, fin_ms):
    """
    Divide un periodo de Retell en dos intervalos.

    No consulta APIs ni modifica registros.
    Los intervalos son contiguos y conservan
    exactamente los extremos originales.
    """

    if (
        type(inicio_ms) is not int
        or type(fin_ms) is not int
        or inicio_ms <= 0
        or fin_ms <= inicio_ms
    ):
        raise ValueError("Periodo invalido")

    if fin_ms - inicio_ms < 2:
        raise ValueError(
            "Periodo demasiado pequeno para dividir"
        )

    mitad_ms = inicio_ms + (
        (fin_ms - inicio_ms) // 2
    )

    return [
        {
            "inicio_ms": inicio_ms,
            "fin_ms": mitad_ms,
        },
        {
            "inicio_ms": mitad_ms,
            "fin_ms": fin_ms,
        },
    ]


def consolidar_consultas_ventanas(resultados):
    """
    Consolida consultas recuperadas desde varios periodos.

    Elimina Call ID duplicados y bloquea resultados
    incompletos o contradictorios.

    No consulta APIs ni modifica registros.
    """

    if not isinstance(resultados, list):
        raise ValueError("Resultados invalidos")

    consultas_unicas = []
    consultas_por_id = {}
    duplicados = 0

    for resultado in resultados:

        if not isinstance(resultado, dict):
            raise ValueError("Resultado de ventana invalido")

        if resultado.get("estado") != "simulacion":
            raise ValueError("Ventana no confirmada")

        if resultado.get("historial_completo") is not True:
            raise ValueError("Historial incompleto")

        consultas = resultado.get("consultas_detectadas")
        total = resultado.get("total_consultas_detectadas")

        if not isinstance(consultas, list):
            raise ValueError("Consultas invalidas")

        if type(total) is not int or total != len(consultas):
            raise ValueError("Conteo de consultas inconsistente")

        for consulta in consultas:

            if not isinstance(consulta, dict):
                raise ValueError("Consulta invalida")

            call_id = consulta.get("call_id")

            if (
                not isinstance(call_id, str)
                or not call_id.strip()
                or call_id != call_id.strip()
            ):
                raise ValueError("Call ID invalido")

            if call_id in consultas_por_id:

                if consultas_por_id[call_id] != consulta:
                    raise ValueError(
                        "Call ID con datos contradictorios"
                    )

                duplicados += 1
                continue

            consultas_por_id[call_id] = consulta
            consultas_unicas.append(consulta)

    return {
        "estado": "consolidado",
        "ventanas_revisadas": len(resultados),
        "total_consultas_detectadas": len(consultas_unicas),
        "duplicados_eliminados": duplicados,
        "consultas_detectadas": consultas_unicas,
    }


def planificar_subdivision_recuperacion(
    inicio_ms,
    fin_ms,
    total_consultas,
    max_consultas=30,
):
    """
    Determina si un periodo necesita subdividirse.

    No ejecuta consultas ni procesa Casos.
    Cada intervalo propuesto debera evaluarse
    antes de una futura ejecucion independiente.
    """

    if (
        type(inicio_ms) is not int
        or type(fin_ms) is not int
        or inicio_ms <= 0
        or fin_ms <= inicio_ms
    ):
        raise ValueError("Periodo invalido")

    if (
        type(total_consultas) is not int
        or total_consultas < 0
    ):
        raise ValueError("Total de consultas invalido")

    if (
        type(max_consultas) is not int
        or not 1 <= max_consultas <= 30
    ):
        raise ValueError("Limite global invalido")

    if total_consultas <= max_consultas:
        return {
            "estado": "dentro_del_limite",
            "total_consultas": total_consultas,
            "ventanas": [{
                "inicio_ms": inicio_ms,
                "fin_ms": fin_ms,
            }],
        }

    if fin_ms - inicio_ms < 2:
        return {
            "estado": "periodo_no_divisible",
            "total_consultas": total_consultas,
            "ventanas": [],
        }

    ventanas = dividir_periodo_recuperacion(
        inicio_ms,
        fin_ms,
    )

    return {
        "estado": "subdivision_requerida",
        "total_consultas": total_consultas,
        "ventanas": ventanas,
    }


def planificar_ventanas_historicas(
    inicio_ms,
    fin_ms,
    max_dias=30,
):
    """
    Organiza un historial extenso en ventanas
    de hasta max_dias.

    Reutiliza el divisor existente.
    No consulta APIs ni modifica registros.
    """

    if (
        type(inicio_ms) is not int
        or type(fin_ms) is not int
        or inicio_ms <= 0
        or fin_ms <= inicio_ms
    ):
        raise ValueError("Periodo historico invalido")

    if (
        type(max_dias) is not int
        or not 1 <= max_dias <= 30
    ):
        raise ValueError("Limite de dias invalido")

    max_ms = max_dias * 86400000

    pendientes = [(inicio_ms, fin_ms)]
    ventanas = []

    while pendientes:
        desde, hasta = pendientes.pop()

        if hasta - desde <= max_ms:
            ventanas.append({
                "inicio_ms": desde,
                "fin_ms": hasta,
            })
            continue

        partes = dividir_periodo_recuperacion(
            desde,
            hasta,
        )

        # Procesar primero el periodo mas antiguo.
        pendientes.append((
            partes[1]["inicio_ms"],
            partes[1]["fin_ms"],
        ))

        pendientes.append((
            partes[0]["inicio_ms"],
            partes[0]["fin_ms"],
        ))

    return ventanas



def seleccionar_ventana_historica_rotativa(
    inicio_ms,
    fin_ms,
    dia_utc,
):
    """
    Selecciona una ventana historica mediante
    rondas completas, sin almacenamiento adicional.

    Cada ronda recorre los periodos existentes
    cuando comienza. Los nuevos quedan para
    la siguiente ronda.

    No consulta APIs ni modifica registros.
    """

    if (
        type(inicio_ms) is not int
        or type(fin_ms) is not int
        or inicio_ms <= 0
        or fin_ms <= inicio_ms
    ):
        raise ValueError("Periodo historico invalido")

    if type(dia_utc) is not int or dia_utc < 0:
        raise ValueError("Dia UTC invalido")

    dia_ms = 86400000
    ventana_ms = 30 * dia_ms

    dia_inicial = inicio_ms // dia_ms
    dia_relativo = dia_utc - dia_inicial

    if dia_relativo < 0:
        raise ValueError("Dia anterior al inicio historico")

    total_ventanas = (
        fin_ms - inicio_ms + ventana_ms - 1
    ) // ventana_ms

    # Identificar la ronda correspondiente al dia.
    inicio_ronda = 0

    while True:
        # Cantidad de ventanas que existian al
        # comenzar esta ronda.
        ventanas_ronda = 1 + inicio_ronda // 30

        if dia_relativo < inicio_ronda + ventanas_ronda:
            indice = dia_relativo - inicio_ronda
            break

        inicio_ronda += ventanas_ronda

    # No seleccionar periodos posteriores al
    # limite temporal solicitado.
    if indice >= total_ventanas:
        raise ValueError(
            "Ventana seleccionada fuera del historial"
        )

    desde = inicio_ms + indice * ventana_ms
    hasta = min(desde + ventana_ms, fin_ms)

    return {
        "estado": "ventana_seleccionada",
        "inicio_ms": desde,
        "fin_ms": hasta,
        "indice_ventana": indice + 1,
        "total_ventanas": total_ventanas,
    }
