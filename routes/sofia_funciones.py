"""Rutas adicionales dentro del webhook existente; no alteran configuracion global."""
import json
from flask import Blueprint, request, jsonify
from services.sofia.configuracion import configurar
from services.sofia.integracion import sin_duplicados

sofia_funciones_bp = Blueprint('sofia_funciones', __name__)
RUTAS = {'/sofia/consultar-cotizacion': 'consultar_cotizacion',
         '/sofia/consultar-solicitud': 'consultar_solicitud',
         '/sofia/preparar-aviso': 'preparar_aviso_comercial'}


def responder(estado, codigo, **datos):
    respuesta = jsonify(estado=estado, **datos)
    respuesta.headers['Cache-Control'] = 'no-store'
    return respuesta, codigo


@sofia_funciones_bp.get('/sofia/estado')
def estado_sofia():
    # Acredita ruta instalada; no valida credenciales ni consulta proveedores.
    return responder('rutas_instaladas', 200)


def ejecutar():
    if request.mimetype != 'application/json':
        return responder('formato_invalido', 415)
    if request.headers.get('Transfer-Encoding'):
        return responder('formato_invalido', 400)
    longitud = request.content_length
    if longitud is None or longitud <= 0:
        return responder('cuerpo_incompleto', 400)
    if longitud > 65536:
        return responder('tamano_no_permitido', 413)
    try:
        raw = request.stream.read(65537)
        if len(raw) != longitud:
            return responder('cuerpo_incompleto', 400)
        datos = json.loads(raw, object_pairs_hook=sin_duplicados)
        if not isinstance(datos, dict) or datos.get('name') != RUTAS[request.path]:
            return responder('funcion_o_ruta_invalida', 400)
    except Exception:
        return responder('solicitud_invalida', 400)
    try:
        procesar = configurar()
    except Exception:
        return responder('sofia_no_configurada', 503)
    try:
        codigo, resultado = procesar(raw, request.headers.get('Authorization'),
                                    request.headers.get('X-Retell-Signature', ''))
        respuesta = jsonify(resultado)
        respuesta.headers['Cache-Control'] = 'no-store'
        return respuesta, codigo
    except Exception:
        return responder('consulta_no_disponible', 502)


for indice, ruta in enumerate(RUTAS):
    sofia_funciones_bp.add_url_rule(ruta, endpoint='funcion_' + str(indice), view_func=ejecutar, methods=['POST'])
