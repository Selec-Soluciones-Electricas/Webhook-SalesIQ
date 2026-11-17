"""Configurar solo al atender una funcion Sofia; nunca bloquear el arranque general."""
import os
from .probar_relaciones_analytics import CLAVES
from .consulta_solicitud_analytics import WORKSPACE, id_valido
from .integracion import crear_procesador
from .consultas import crear_consultas, crear_contexto_aviso

CLAVES_SOFIA = (*CLAVES, 'ANALYTICS_WORKSPACE_ID', 'RETELL_API_KEY',
                'RETELL_SOFIA_AGENT_ID', 'SOFIA_TOOL_SECRET')


def configurar(valores=None):
    config = {k: os.environ.get(k) for k in CLAVES_SOFIA} if valores is None else dict(valores)
    if (not all(isinstance(config.get(k), str) and config[k].strip() for k in CLAVES_SOFIA)
            or not id_valido(config['ANALYTICS_ORG_ID'])
            or config['ANALYTICS_WORKSPACE_ID'].strip() != WORKSPACE
            or len(config['SOFIA_TOOL_SECRET'].strip()) < 32):
        raise ValueError('Configuracion Sofia incompleta')
    import requests
    from retell.lib.webhook_auth import verify
    cotizaciones, solicitudes = crear_consultas(requests, config)
    return crear_procesador(config['SOFIA_TOOL_SECRET'].strip(), config['RETELL_API_KEY'],
        config['RETELL_SOFIA_AGENT_ID'].strip(), verify, cotizaciones, solicitudes,
        crear_contexto_aviso(requests, config))
