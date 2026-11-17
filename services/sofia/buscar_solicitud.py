"""Prototipo sin red: localizar un negocio por empresa y referencia en exportaciones.

No se conecta a Retell. Una coincidencia no acredita identidad, recepcion de correo,
envio de cotizacion ni una fecha comercial comprometida.
"""
import unicodedata


def normalizar(valor):
    if not isinstance(valor, str):
        return ''
    return ' '.join(unicodedata.normalize('NFKC', valor).split()).casefold()


def resultado(estado, **datos):
    return dict(estado=estado, fuente='exportaciones_locales', identidad_verificada=False,
                autorizado_para_divulgar=False, recepcion_correo_confirmada=False,
                envio_cotizacion_confirmado=False, fecha_comprometida_confirmada=False, **datos)


def indexar(filas, campos):
    indice = {}
    for fila in filas:
        if not isinstance(fila, dict) or any(not isinstance(fila.get(c), str) for c in campos):
            raise ValueError('Datos incompletos')
        identificador = fila['Id']
        if not identificador.isascii() or not identificador.isdigit() or identificador in indice:
            raise ValueError('Id invalido o repetido')
        indice[identificador] = fila
    return indice


def buscar_solicitud(empresa, referencia, clientes, negocios, cotizaciones, usuarios):
    nombre = normalizar(empresa)
    if not nombre or len(nombre) > 200:
        return resultado('pedir_empresa')
    if referencia is not None and (not isinstance(referencia, str) or len(referencia) > 200):
        return resultado('referencia_invalida')
    ref = normalizar(referencia)
    try:
        cuentas = indexar(clientes, ['Id', 'Nombre de Cuenta'])
        deals = indexar(negocios, ['Id', 'Nombre de Cuenta', 'Nombre de Trato', 'Fase'])
        quotes = indexar(cotizaciones, ['Id', 'Nombre de Trato', 'Numero Cotización'])
        users = indexar(usuarios, ['Id', 'Nombre completo', 'Estado'])
    except (ValueError, TypeError):
        return resultado('datos_de_copia_invalidos')
    coincidencias = [c for c in cuentas.values() if normalizar(c['Nombre de Cuenta']) == nombre]
    if not coincidencias:
        return resultado('empresa_no_localizada_en_copia')
    if len(coincidencias) != 1:
        return resultado('empresa_ambigua')
    cuenta = coincidencias[0]
    candidatos = [n for n in deals.values() if n['Nombre de Cuenta'] == cuenta['Id']]
    if ref:
        candidatos = [n for n in candidatos if ref in {
            normalizar(n['Nombre de Trato']), normalizar(n.get('Número Licitación'))}]
    if not candidatos:
        return resultado('solicitud_no_localizada_en_copia',
                         mensaje='No se localizo con esos datos en la copia. Esto no significa que el correo no haya llegado.')
    if len(candidatos) != 1:
        return resultado('pedir_referencia', cantidad_coincidencias=len(candidatos),
                         pregunta='¿Tienes una referencia o numero de solicitud para distinguirla?')
    negocio = candidatos[0]
    relacionadas = [q for q in quotes.values() if q['Nombre de Trato'] == negocio['Id']]
    if any(not q['Numero Cotización'].strip() for q in relacionadas):
        return resultado('datos_de_copia_invalidos')
    numeros = [q['Numero Cotización'] for q in relacionadas]
    asignado = users.get(negocio.get('Asignado a'))
    ejecutivo = None
    if asignado and normalizar(asignado['Estado']) == 'active' and asignado['Nombre completo'].strip():
        ejecutivo = asignado['Nombre completo']
    return resultado('solicitud_localizada_en_copia', datos_internos={
        'empresa': cuenta['Nombre de Cuenta'], 'referencia': negocio['Nombre de Trato'],
        'estado_registrado': negocio['Fase'], 'creacion_registrada': negocio.get('Hora de creación') or None,
        'ejecutivo_provisional': ejecutivo,
        'cotizaciones_vinculadas_en_copia': numeros,
        'fecha_limite_oferta_interna': negocio.get('Fecha limite oferta') or None,
        'fecha_prometida_al_cliente': None,
    }, mensaje='El negocio figura en la copia consultada. La fecha limite de oferta no se interpreta como promesa al cliente. La ausencia de cotizaciones vinculadas en esta copia no prueba que no se haya cotizado o enviado por otra via.')
