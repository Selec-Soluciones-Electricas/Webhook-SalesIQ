"""Busqueda interna de solicitudes. GET de tablas; sin conexion al importar."""
import csv
import io
import json
import re

from .buscar_solicitud import normalizar

WORKSPACE = '2611904000000269050'
VISTAS = {'Clientes': '2611904000000269101', 'Negocios': '2611904000000269102',
          'Cotizaciones': '2611904000000269129', 'Usuarios': '2611904000000269098'}
COLUMNAS = {
    'Clientes': ['Id', 'Nombre de Cuenta'],
    'Negocios': ['Id', 'Nombre de Cuenta', 'Nombre de Trato', 'Número Licitación',
                 'Fase', 'Asignado a', 'Hora de creación', 'Fecha limite oferta'],
    'Cotizaciones': ['Id', 'Nombre de Trato', 'Nombre de Cuenta', 'Numero Cotización'],
    'Usuarios': ['Id', 'Nombre completo', 'Estado'],
}
FILTROS = {'Clientes': 'Nombre de Cuenta', 'Negocios': 'Nombre de Cuenta',
           'Cotizaciones': 'Nombre de Trato', 'Usuarios': 'Id'}
MAX_BYTES = 2 * 1024 * 1024
MAX_FILAS = 5000


class FalloLectura(Exception):
    def __init__(self, estado):
        self.estado = estado


def id_valido(valor):
    return isinstance(valor, str) and re.fullmatch(r'[0-9]{1,64}', valor) is not None


def empresa_permitida(valor):
    # Lista cerrada: no se interpolan comillas, barras ni expresiones del usuario.
    return (isinstance(valor, str) and bool(valor.strip()) and len(valor) <= 200
            and all(c.isalnum() or c in ' .,&()-' for c in valor))


def referencia_permitida(valor):
    return isinstance(valor, str) and len(valor) <= 200 and all(c.isprintable() for c in valor)


def resultado(estado, datos=None, **extra):
    return dict(estado=estado, datos_internos=datos, fuente='Zoho Analytics',
                identidad_verificada=False, autorizado_para_divulgar=False,
                recepcion_correo_confirmada=False, envio_cotizacion_confirmado=False,
                ultima_sincronizacion_verificada=False, **extra)


def crear_lector(cliente, token, org_id):
    if not id_valido(org_id):
        raise ValueError('Organizacion invalida')

    def leer(tabla, valor):
        if tabla not in VISTAS or not (empresa_permitida(valor) if tabla == 'Clientes' else id_valido(valor)):
            raise FalloLectura('consulta_no_permitida')
        config = {'responseFormat': 'csv', 'includeHeader': True,
                  'selectedColumns': COLUMNAS[tabla],
                  'criteria': f'"{tabla}"."{FILTROS[tabla]}"=\'{valor}\''}
        url = f'https://analyticsapi.zoho.com/restapi/v2/workspaces/{WORKSPACE}/views/{VISTAS[tabla]}/data'
        with cliente.get(url, headers={'Authorization': 'Zoho-oauthtoken ' + token,
                                     'ZANALYTICS-ORGID': org_id},
                         params={'CONFIG': json.dumps(config)}, stream=True,
                         allow_redirects=False, timeout=20) as respuesta:
            print(f'HTTP {tabla}:', respuesta.status_code)
            if respuesta.status_code != 200:
                raise FalloLectura('error_acceso' if respuesta.status_code in (401, 403) else 'error_servicio')
            contenido = bytearray()
            for bloque in respuesta.iter_content(chunk_size=8192):
                contenido.extend(bloque)
                if len(contenido) > MAX_BYTES:
                    raise FalloLectura('respuesta_demasiado_grande')
        try:
            lector = csv.DictReader(io.StringIO(contenido.decode('utf-8-sig')), strict=True)
            if (lector.fieldnames is None or len(lector.fieldnames) != len(set(lector.fieldnames))
                    or set(lector.fieldnames) != set(COLUMNAS[tabla])):
                raise FalloLectura('respuesta_invalida')
            filas = []
            for fila in lector:
                if None in fila or any(v is None for v in fila.values()):
                    raise FalloLectura('respuesta_invalida')
                filas.append(fila)
                if len(filas) > MAX_FILAS:
                    raise FalloLectura('demasiados_registros')
            return filas
        except (UnicodeError, csv.Error):
            raise FalloLectura('respuesta_invalida') from None
    return leer


def leer_validado(lector, tabla, valor):
    filas = lector(tabla, valor)
    if not isinstance(filas, list) or len(filas) > MAX_FILAS:
        raise FalloLectura('respuesta_invalida')
    ids = set()
    for fila in filas:
        if (not isinstance(fila, dict) or any(not isinstance(fila.get(c), str) for c in COLUMNAS[tabla])
                or not id_valido(fila['Id']) or fila['Id'] in ids):
            raise FalloLectura('respuesta_invalida')
        ids.add(fila['Id'])
        actual = fila[FILTROS[tabla]]
        coincide = normalizar(actual) == normalizar(valor) if tabla == 'Clientes' else actual == valor
        if not coincide:
            raise FalloLectura('filtro_no_confirmado')
    return filas


def consultar_solicitud(empresa, referencia, lector):
    if not empresa_permitida(empresa):
        return resultado('empresa_no_admitida_en_esta_prueba')
    if not referencia_permitida(referencia):
        return resultado('referencia_invalida')
    if not callable(lector):
        return resultado('configuracion_invalida')
    try:
        cuentas = leer_validado(lector, 'Clientes', empresa.strip())
        if not cuentas:
            return resultado('empresa_no_localizada_en_analytics')
        if len(cuentas) != 1:
            return resultado('empresa_ambigua')
        cuenta = cuentas[0]
        negocios = leer_validado(lector, 'Negocios', cuenta['Id'])
        ref = normalizar(referencia)
        if ref:
            negocios = [n for n in negocios if ref in {normalizar(n['Nombre de Trato']), normalizar(n['Número Licitación'])}]
        if not negocios:
            return resultado('solicitud_no_localizada_en_analytics')
        if len(negocios) != 1:
            return resultado('pedir_referencia', cantidad_coincidencias=len(negocios))
        negocio = negocios[0]
        if not negocio['Fase'].strip() or not negocio['Nombre de Trato'].strip():
            return resultado('datos_incompletos')
        cotizaciones = leer_validado(lector, 'Cotizaciones', negocio['Id'])
        if any(q['Nombre de Cuenta'] != cuenta['Id'] for q in cotizaciones):
            return resultado('cuentas_no_coinciden')
        if any(not q['Numero Cotización'].strip() for q in cotizaciones):
            return resultado('datos_incompletos')
        ejecutivo = None
        asignado = negocio['Asignado a']
        if asignado:
            if not id_valido(asignado):
                return resultado('datos_incompletos')
            usuarios = leer_validado(lector, 'Usuarios', asignado)
            if len(usuarios) != 1:
                return resultado('usuario_no_resuelto')
            usuario = usuarios[0]
            if normalizar(usuario['Estado']) == 'active':
                ejecutivo = usuario['Nombre completo'].strip() or None
        return resultado('solicitud_localizada_en_analytics', {
            'empresa': cuenta['Nombre de Cuenta'], 'referencia': negocio['Nombre de Trato'],
            'estado_registrado': negocio['Fase'], 'creacion_registrada': negocio['Hora de creación'] or None,
            'ejecutivo_provisional': ejecutivo,
            'cotizaciones_vinculadas': [q['Numero Cotización'] for q in cotizaciones],
            'fecha_limite_oferta_interna': negocio['Fecha limite oferta'] or None,
            'fecha_prometida_al_cliente': None,
        })
    except FalloLectura as error:
        return resultado(error.estado)
    except Exception:
        return resultado('error_lectura')
