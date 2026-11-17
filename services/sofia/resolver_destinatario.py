"""Resolver correo del ejecutivo por Asignado a -> Usuarios.Id. Solo lectura."""
import sys
sys.dont_write_bytecode = True
import csv
import io
import json
import re
import os
from pathlib import Path
from .consulta_solicitud_analytics import (crear_lector, leer_validado, normalizar,
    empresa_permitida, referencia_permitida, id_valido, WORKSPACE, VISTAS)
from .probar_relaciones_analytics import autenticar, CLAVES
from .transporte import ClienteConPlazo

CAMPOS = ['Id', 'Nombre completo', 'Estado', 'Correo electrónico']


def validar_usuario(filas, identificador):
    if not isinstance(filas, list) or len(filas) != 1:
        return {'estado': 'usuario_no_resuelto'}
    u = filas[0]
    if (not isinstance(u, dict) or any(not isinstance(u.get(c), str) for c in CAMPOS)
            or u['Id'] != identificador):
        return {'estado': 'usuario_invalido'}
    if u['Estado'].strip().casefold() != 'active':
        return {'estado': 'usuario_inactivo'}
    correo = u['Correo electrónico'].strip()
    if (not re.fullmatch(r'[^\s@<>;,]+@[^\s@<>;,]+\.[^\s@<>;,]+', correo)
            or len(correo) > 254 or any(not c.isprintable() for c in correo)):
        return {'estado': 'correo_no_resuelto'}
    if not u['Nombre completo'].strip():
        return {'estado': 'usuario_invalido'}
    return {'estado': 'destinatario_resuelto', 'ejecutivo': u['Nombre completo'],
            'destinatario_email': correo, 'fuente': 'Negocios.Asignado a -> Usuarios.Id',
            'correo_enviado': False}


def leer_usuario(cliente, token, org_id, identificador):
    if not id_valido(identificador) or not id_valido(org_id):
        raise ValueError('Id invalido')
    config = {'responseFormat': 'csv', 'includeHeader': True, 'selectedColumns': CAMPOS,
              'criteria': f'"Usuarios"."Id"=\'{identificador}\''}
    url = f'https://analyticsapi.zoho.com/restapi/v2/workspaces/{WORKSPACE}/views/{VISTAS["Usuarios"]}/data'
    with cliente.get(url, headers={'Authorization': 'Zoho-oauthtoken ' + token, 'ZANALYTICS-ORGID': org_id},
                     params={'CONFIG': json.dumps(config)}, stream=True, allow_redirects=False, timeout=20) as r:
        print('HTTP Usuarios:', r.status_code)
        if r.status_code != 200:
            raise ValueError('Lectura no disponible')
        contenido = bytearray()
        for bloque in r.iter_content(chunk_size=8192):
            contenido.extend(bloque)
            if len(contenido) > 131072:
                raise ValueError('Respuesta excesiva')
    lector = csv.DictReader(io.StringIO(contenido.decode('utf-8-sig')), strict=True)
    if lector.fieldnames is None or len(lector.fieldnames) != len(set(lector.fieldnames)) or set(lector.fieldnames) != set(CAMPOS):
        raise ValueError('Columnas invalidas')
    filas = list(lector)
    if any(None in fila for fila in filas):
        raise ValueError('Respuesta invalida')
    return filas


def resolver(empresa, referencia, lector, obtener_usuario):
    if not empresa_permitida(empresa) or not referencia_permitida(referencia) or not referencia.strip():
        return {'estado': 'datos_invalidos'}
    cuentas = leer_validado(lector, 'Clientes', empresa.strip())
    if len(cuentas) != 1:
        return {'estado': 'empresa_no_resuelta'}
    negocios = leer_validado(lector, 'Negocios', cuentas[0]['Id'])
    candidatos = [n for n in negocios if normalizar(referencia) in
                  {normalizar(n['Nombre de Trato']), normalizar(n['Número Licitación'])}]
    if len(candidatos) != 1:
        return {'estado': 'solicitud_no_resuelta'}
    asignado = candidatos[0]['Asignado a']
    if not id_valido(asignado):
        return {'estado': 'ejecutivo_no_asignado'}
    return validar_usuario(obtener_usuario(asignado), asignado)


def main():
    # Caso ya validado por el usuario. No se envia ningun mensaje.
    print('=== SOFIA: RESOLVER DESTINATARIO DEL AVISO ===')
    print('Empresa: DUOC UC | Referencia: 1011522')
    try:
        import requests
        from dotenv import dotenv_values
        archivo = dotenv_values(Path.home() / 'OneDrive/Desktop/Webhook-SalesIQ/.env')
        claves = (*CLAVES, 'ANALYTICS_WORKSPACE_ID')
        valores = {k: os.environ.get(k, archivo.get(k)) for k in claves}
        if (not all(isinstance(v, str) and v.strip() for v in valores.values())
                or valores['ANALYTICS_WORKSPACE_ID'].strip() != WORKSPACE):
            raise ValueError('Configuracion invalida')
        with requests.Session() as sesion:
            cliente = ClienteConPlazo(sesion)
            token = autenticar(cliente, valores)
            if not token:
                raise ValueError('Autenticacion no disponible')
            org = valores['ANALYTICS_ORG_ID']
            res = resolver('DUOC UC', '1011522', crear_lector(cliente, token, org),
                           lambda identificador: leer_usuario(cliente, token, org, identificador))
        print('Estado:', res['estado'])
        if res['estado'] == 'destinatario_resuelto':
            print('Ejecutivo:', ''.join(c for c in res['ejecutivo'] if c.isprintable())[:160])
            print('Correo del ejecutivo: LOCALIZADO; no se muestra la direccion')
            print('Relacion validada por ID: SI | Usuario activo: SI')
        print('Correo enviado: NO | Registro modificado: NO')
        print('Ultima sincronizacion: NO VERIFICADA')
        print('VERIFICACION FINALIZADA')
        return 0 if res['estado'] == 'destinatario_resuelto' else 1
    except Exception:
        print('[DETENIDO] No se pudo resolver el destinatario. Comparte este aviso; no cambies permisos.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
