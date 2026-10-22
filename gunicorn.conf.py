"""
Configuración de gunicorn para producción (Render).
Render ejecuta:  gunicorn ServerHook:app
y gunicorn lee este archivo automáticamente desde la raíz del repo.
"""

import os

bind = f"0.0.0.0:{os.getenv('PORT', '10000')}"

# Las sesiones del chat viven en memoria: debe haber UN solo proceso.
# Los threads permiten atender varias peticiones al mismo tiempo.
workers = 1
threads = 8
timeout = 120

# Log de accesos SIN la query string (%(U)s es la ruta sin "?..."),
# para que tokens como ?token= no queden escritos en los logs.
accesslog = "-"
access_log_format = '%(h)s "%(m)s %(U)s" %(s)s %(b)s %(L)ss'