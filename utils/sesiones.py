"""
Sesiones del chat en memoria, con expiración y tope de cantidad.

Antes eran un dict sin límite: cada visitante nuevo (o cada bot que llamara al
webhook con IDs inventados) sumaba una entrada que nunca se borraba, hasta
llenar la RAM. Ahora:
  - una sesión sin actividad por SESION_TTL_HORAS (12 por defecto) se elimina;
  - si se supera SESION_MAXIMO (5000 por defecto), se eliminan las más antiguas.

Ojo: siguen en memoria. Un reinicio o deploy borra las conversaciones en curso,
y el servidor debe correr con 1 solo worker de gunicorn.
"""

import os
import threading
import time


class SesionesConExpiracion(dict):

    def __init__(self):
        super().__init__()
        self.ttl = float(os.getenv("SESION_TTL_HORAS", "12")) * 3600
        self.maximo = int(os.getenv("SESION_MAXIMO", "5000"))
        self._ultimo_uso: dict = {}
        self._ultima_limpieza = 0.0
        self._candado = threading.RLock()

    def setdefault(self, clave, valor=None):
        with self._candado:
            self._limpiar()
            self._ultimo_uso[clave] = time.time()
            return super().setdefault(clave, valor)

    def __getitem__(self, clave):
        with self._candado:
            self._ultimo_uso[clave] = time.time()
            return super().__getitem__(clave)

    def __setitem__(self, clave, valor):
        with self._candado:
            self._ultimo_uso[clave] = time.time()
            super().__setitem__(clave, valor)

    def __delitem__(self, clave):
        with self._candado:
            self._ultimo_uso.pop(clave, None)
            super().__delitem__(clave)

    def pop(self, clave, *defecto):
        with self._candado:
            self._ultimo_uso.pop(clave, None)
            return super().pop(clave, *defecto)

    def _limpiar(self):
        ahora = time.time()
        # Recorrer todo cada vez sería caro: se limpia como máximo una vez por minuto,
        # salvo que se haya alcanzado el tope.
        if ahora - self._ultima_limpieza < 60 and len(self) < self.maximo:
            return
        self._ultima_limpieza = ahora

        for clave in [k for k, t in self._ultimo_uso.items() if ahora - t > self.ttl]:
            self.pop(clave, None)

        if len(self) >= self.maximo:
            sobrantes = len(self) - self.maximo + 1
            for clave, _ in sorted(self._ultimo_uso.items(), key=lambda kv: kv[1])[:sobrantes]:
                self.pop(clave, None)