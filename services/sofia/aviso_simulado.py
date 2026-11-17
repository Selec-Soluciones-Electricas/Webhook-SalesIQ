"""Prepara un aviso en memoria. No importa servicios ni permite enviar o guardar."""


def texto(valor, limite=1000):
    if valor is None or valor == '':
        return None
    if not isinstance(valor, str) or len(valor) > limite or any(not c.isprintable() for c in valor):
        raise ValueError('campo_invalido')
    return valor.strip() or None


def preparar_aviso(declaracion, consulta=None):
    """La declaracion es lo dicho por el cliente; consulta es un resultado previo.

    No otorga identidad, no busca destinatarios y no promete seguimiento. La
    urgencia es texto declarado; no se convierte en prioridad o compromiso SLA.
    """
    if not isinstance(declaracion, dict):
        raise ValueError('declaracion_invalida')
    campos = ('empresa', 'referencia_solicitud', 'numero_cotizacion', 'motivo_contacto',
              'urgencia_declarada', 'nombre_cliente', 'email_cliente', 'telefono_cliente')
    cliente = {campo: texto(declaracion.get(campo)) for campo in campos}
    faltantes = []
    if not cliente['motivo_contacto']:
        faltantes.append('motivo_contacto')
    if not cliente['empresa']:
        faltantes.append('empresa')
    if not cliente['nombre_cliente']:
        faltantes.append('nombre_cliente')
    if not (cliente['email_cliente'] or cliente['telefono_cliente']):
        faltantes.append('medio_de_contacto')

    verificado = None
    avisos = []
    if consulta is not None:
        if not isinstance(consulta, dict):
            raise ValueError('consulta_invalida')
        estado = consulta.get('estado')
        datos = consulta.get('datos_internos')
        # No usar datos parciales devueltos junto con un error o ambiguedad.
        if estado in ('solicitud_localizada_en_analytics', 'encontrada') and isinstance(datos, dict):
            es_solicitud = estado == 'solicitud_localizada_en_analytics'
            empresa = texto(datos.get('empresa' if es_solicitud else 'cliente'))
            referencia = texto(datos.get('referencia' if es_solicitud else 'numero'))
            campo = 'referencia_solicitud' if es_solicitud else 'numero_cotizacion'
            misma_empresa = empresa and cliente['empresa'] and empresa.casefold() == cliente['empresa'].casefold()
            misma_referencia = referencia and referencia == cliente[campo]
            if misma_empresa and misma_referencia:
                verificado = {
                    'empresa': empresa,
                    campo: referencia,
                    'estado_registrado': texto(datos.get('estado_registrado')),
                    'ejecutivo_provisional': texto(datos.get('ejecutivo_provisional')),
                    'fuente': 'resultado de consulta anterior; sin nueva lectura',
                    'ultima_sincronizacion_verificada': False,
                }
            else:
                avisos.append('consulta_no_corresponde_a_la_declaracion')
        else:
            avisos.append('consulta_no_resuelta')
    if not verificado or not verificado['ejecutivo_provisional']:
        faltantes.append('ejecutivo_por_resolver')
    # El destinatario requiere resolver y validar una direccion real en otra etapa.
    # Ninguna entrada del LLM puede habilitar un envio o asignar permisos.
    return {
        'estado': 'aviso_simulado_preparado',
        'modo': 'simulacion_en_memoria',
        'declarado_por_cliente': cliente,
        'consulta_previa': verificado,
        'datos_por_completar': faltantes,
        'avisos': avisos,
        'destinatario_email': None,
        'destinatario_confirmado': False,
        'correo_enviado': False,
        'aviso_guardado': False,
        'seguimiento_iniciado': False,
        'identidad_verificada': False,
        'autorizado_para_divulgar': False,
        'prioridad_comercial_confirmada': False,
        'fecha_respuesta_prometida': None,
        'mensaje_para_sofia': 'Se preparo solamente un aviso simulado para revision interna. '
            'No se envio ni se guardo. No digas que el ejecutivo fue notificado o que respondera en un plazo. '
            'Los datos de contacto son declarados, no verificados.',
    }
