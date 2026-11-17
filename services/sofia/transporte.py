import time

class RespuestaConPlazo:
    def __init__(self, respuesta, fin, reloj):
        self.respuesta, self.fin, self.reloj = respuesta, fin, reloj

    def __getattr__(self, nombre):
        return getattr(self.respuesta, nombre)

    def __enter__(self):
        self.respuesta.__enter__()
        return self

    def __exit__(self, *args):
        return self.respuesta.__exit__(*args)

    def iter_content(self, **kwargs):
        for bloque in self.respuesta.iter_content(**kwargs):
            if self.reloj() >= self.fin:
                raise TimeoutError('Tiempo agotado')
            yield bloque


class ClienteConPlazo:
    def __init__(self, cliente, reloj=time.monotonic):
        self.cliente, self.reloj = cliente, reloj
        self.fin = reloj() + 30

    def parametros(self, kwargs):
        restante = self.fin - self.reloj()
        if restante <= 0:
            raise TimeoutError('Tiempo agotado')
        kwargs['timeout'] = (min(3, restante), min(8, restante))
        kwargs['allow_redirects'] = False
        return kwargs

    def post(self, url, **kwargs):
        if url != 'https://accounts.zoho.com/oauth/v2/token':
            raise ValueError('POST no permitido')
        return self.cliente.post(url, **self.parametros(kwargs))

    def get(self, url, **kwargs):
        if not url.startswith('https://analyticsapi.zoho.com/restapi/v2/workspaces/'):
            raise ValueError('GET no permitido')
        r = self.cliente.get(url, **self.parametros(kwargs))
        return RespuestaConPlazo(r, self.fin, self.reloj)


