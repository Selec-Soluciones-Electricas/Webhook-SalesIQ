from .transporte import ClienteConPlazo
from .consulta_analytics import consultar_cotizacion_analytics
from .probar_relaciones_analytics import crear_lector as lector_cotizaciones, autenticar
from .consulta_solicitud_analytics import crear_lector as lector_solicitudes, consultar_solicitud
from .resolver_destinatario import leer_usuario, validar_usuario

def crear_consultas(requests, valores):
    def consultar(tipo, *args):
        with requests.Session() as sesion:
            cliente = ClienteConPlazo(sesion)
            token = autenticar(cliente, valores)
            if not token:
                return {'estado': 'error_acceso'}
            if tipo == 'cotizacion':
                return consultar_cotizacion_analytics(*args, lector_cotizaciones(cliente, token, valores['ANALYTICS_ORG_ID']))
            return consultar_solicitud(*args, lector_solicitudes(cliente, token, valores['ANALYTICS_ORG_ID']))
    return lambda numero: consultar('cotizacion', numero), lambda empresa, ref: consultar('solicitud', empresa, ref)


def crear_contexto_aviso(requests, valores):
    def preparar(args):
        numero = args.get('numero_cotizacion')
        if not numero and not (args.get('empresa') and args.get('referencia_solicitud')):
            return {'estado': 'sin_referencia_suficiente'}, {}
        with requests.Session() as sesion:
            cliente = ClienteConPlazo(sesion)
            token = autenticar(cliente, valores)
            if not token:
                return {'estado': 'error_acceso'}, {}
            org = valores['ANALYTICS_ORG_ID']
            destino = {}
            base = lector_cotizaciones(cliente, token, org) if numero else lector_solicitudes(cliente, token, org)
            def leer(tabla, *argumentos):
                nonlocal destino
                if tabla != 'Usuarios':
                    return base(tabla, *argumentos)
                identificador = argumentos[1] if numero else argumentos[0]
                filas = leer_usuario(cliente, token, org, identificador)
                destino = validar_usuario(filas, identificador)
                return filas
            if numero:
                res = consultar_cotizacion_analytics(numero, leer)
            else:
                res = consultar_solicitud(args['empresa'], args['referencia_solicitud'], leer)
            return res, destino
    return preparar


