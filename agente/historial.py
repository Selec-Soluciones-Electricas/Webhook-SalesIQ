"""
Historial de productos que SELEC ya ha vendido (tabla "Artículos facturados" de Zoho Analytics).

Se usa para que la decisión "¿es del rubro?" sea más flexible:
  1. Claude recibe la lista de tipos de producto vendidos (con un ejemplo de cada uno).
  2. Si Claude igual marca un correo como fuera del rubro, pero alguno de sus productos
     es de un tipo que ya se vendió, se considera del rubro de todas formas.

El "tipo" de un producto es su primera palabra significativa, sin tildes ni plural:
  "CONMUTADOR TELERGON"        -> conmutador
  "LINTERNA FRONTAL FLUKE"     -> linterna
  "Kit fuente 12V + cargador"  -> fuente   ("kit" no cuenta)

Variables de entorno (opcionales):
  ARTICULOS_FACTURADOS_VIEW_ID   ID de la tabla "Artículos facturados" (por defecto 2611904000000269134)
  ARTICULOS_COLUMNA_PRODUCTO     nombre exacto de la columna con el nombre del producto;
                                 si no está, se prueban los nombres habituales
  HISTORIAL_HORAS_CACHE          cada cuántas horas se vuelve a leer la tabla (por defecto 12)
  HISTORIAL_MAX_TIPOS            cuántos tipos se le muestran a Claude (por defecto 250)
  HISTORIAL_MIN_VENTAS           veces que se tiene que haber vendido un tipo para contar (por defecto 3);
                                 evita que una compra aislada (ej. una silla) abra todo un rubro
  HISTORIAL_EXCLUIR              tipos que nunca cuentan, separados por coma (se suman a los de abajo)
"""

import json
import os
import re
import time
import unicodedata
from collections import Counter

VISTA = os.getenv("ARTICULOS_FACTURADOS_VIEW_ID", "2611904000000269134")
COLUMNAS_CANDIDATAS = [
    "Product Display Value", "Product Display Name", "Product Display",
    "Product Name", "Nombre de producto", "Nombre del producto", "Producto",
]

# Palabras que no indican el tipo de producto (se saltan al buscar la primera palabra significativa)
NO_SIGNIFICATIVAS = {
    "de", "del", "la", "el", "los", "las", "para", "con", "sin", "por", "en", "y", "o", "a", "al",
    "tipo", "marca", "modelo", "set", "kit", "pack", "juego", "unidad", "unidades", "und", "un", "una",
    "mm", "cm", "mts", "mt", "metro", "metros", "nuevo", "nueva", "original", "generico", "generica",
    "envio", "flete", "fletes", "servicio", "servicios", "despacho", "otros", "varios", "producto",
    "articulo", "item", "sku", "codigo", "ref", "cotizacion", "repuesto", "repuestos", "pieza", "piezas",
    "material", "materiales", "insumo", "insumos", "accesorio", "accesorios", "equipo", "equipos",
    "soporte", "jgo", "parte", "partes", "elemento", "elementos", "conjunto", "suministro",
}

# Tipos que aunque aparezcan facturados no son del rubro (compras puntuales, mobiliario, etc.)
TIPOS_EXCLUIDOS = {
    "silla", "mesa", "escritorio", "mueble", "sillon", "estante", "repisa", "colchon", "cama",
    "alimento", "cafe", "agua", "bebida", "galleta", "papel", "cuaderno", "lapiz", "archivador",
    "uniforme", "polera", "pantalon", "chaqueta", "zapato", "zapatilla",
}
# Si el ítem es un servicio, no se compara con el historial
PATRON_SERVICIO = re.compile(
    r"\b(mantencion|mantenimiento|servicio|instalacion|reparacion|arriendo|capacitacion|asesoria|"
    r"calibracion|soporte tecnico|mano de obra)\b"
)

_cache = {"tipos": None, "ejemplos": {}, "columna": None, "filas": 0, "hasta": 0.0, "error": None}


def _normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9ñ ]", " ", t)


def _singular(palabra: str) -> str:
    if len(palabra) > 5 and palabra.endswith("es") and palabra[-3] in "rnldz":
        return palabra[:-2]          # conectores -> conector, interruptores -> interruptor
    if len(palabra) > 4 and palabra.endswith("s") and not palabra.endswith("ss"):
        return palabra[:-1]          # cables -> cable, brocas -> broca
    return palabra


def tipo_producto(texto: str) -> str | None:
    """Primera palabra significativa del nombre o descripción del producto."""
    for palabra in _normalizar(texto).split():
        if palabra.isalpha() and len(palabra) >= 3 and palabra not in NO_SIGNIFICATIVAS:
            return _singular(palabra)
    return None


# =========================================================
# CARGA DESDE ANALYTICS
# =========================================================

def _leer_columna(base: str, headers: dict, columna: str):
    from agente.correo import _pedir

    config = {"responseFormat": "json", "selectedColumns": [columna], "keyValueFormat": True}
    resp = _pedir("GET", f"{base}/data", headers=headers, params={"CONFIG": json.dumps(config)})
    if resp.status_code != 200:
        return None, f"{resp.status_code}: {resp.text[:200]}"
    return [fila.get(columna) for fila in (resp.json().get("data") or [])], None


def _cargar() -> None:
    from agente.correo import _analytics, log

    base, headers = _analytics(VISTA)
    candidatas = [os.environ["ARTICULOS_COLUMNA_PRODUCTO"]] if os.getenv("ARTICULOS_COLUMNA_PRODUCTO") \
        else COLUMNAS_CANDIDATAS
    nombres, ultimo_error = None, None
    for columna in candidatas:
        nombres, ultimo_error = _leer_columna(base, headers, columna)
        if nombres is not None:
            _cache["columna"] = columna
            break
    if nombres is None:
        raise RuntimeError(f"no se encontró la columna de producto en Artículos facturados ({ultimo_error})")

    tipos, ejemplos = Counter(), {}
    for nombre in nombres:
        tipo = tipo_producto(nombre or "")
        if tipo:
            tipos[tipo] += 1
            ejemplos.setdefault(tipo, (nombre or "").strip()[:80])
    _cache.update(tipos=tipos, ejemplos=ejemplos, filas=len(nombres), error=None,
                  hasta=time.time() + float(os.getenv("HISTORIAL_HORAS_CACHE", "12")) * 3600)
    log(f"historial de ventas: {len(nombres)} artículos, {len(tipos)} tipos de producto "
        f"(columna '{_cache['columna']}')")


def tipos_vendidos() -> Counter:
    """Tipos de producto vendidos -> cantidad de líneas facturadas. Se refresca cada 12 h."""
    if _cache["tipos"] is None or time.time() > _cache["hasta"]:
        try:
            _cargar()
        except Exception as e:
            from agente.correo import log
            _cache["error"] = str(e)[:300]
            _cache["hasta"] = time.time() + 1800  # reintenta en 30 min; mientras, usa lo que había
            log(f"no se pudo leer el historial de ventas: {e}")
            if _cache["tipos"] is None:
                _cache["tipos"] = Counter()
    return _cache["tipos"]


def tipos_validos() -> set[str]:
    """Tipos que cuentan como "ya vendidos": con al menos HISTORIAL_MIN_VENTAS ventas y no excluidos."""
    minimo = int(os.getenv("HISTORIAL_MIN_VENTAS", "3"))
    excluir = TIPOS_EXCLUIDOS | {t.strip().lower() for t in os.getenv("HISTORIAL_EXCLUIR", "").split(",") if t.strip()}
    return {t for t, n in tipos_vendidos().items() if n >= minimo and t not in excluir}


def tipo_si_coincide(texto: str) -> str | None:
    """Tipo del producto si ya se vendió (y no es un servicio); None si no."""
    if PATRON_SERVICIO.search(_normalizar(texto)):
        return None
    tipo = tipo_producto(texto)
    return tipo if tipo and tipo in tipos_validos() else None


# =========================================================
# USO EN EL ANÁLISIS
# =========================================================

def texto_para_prompt() -> str:
    """Bloque para el prompt de Claude con los tipos de producto más vendidos."""
    tipos = tipos_vendidos()
    validos = tipos_validos()
    if not validos:
        return ""
    maximo = int(os.getenv("HISTORIAL_MAX_TIPOS", "250"))
    lineas = [f"- {tipo} (ej. {_cache['ejemplos'].get(tipo, '')})"
              for tipo, _ in tipos.most_common() if tipo in validos][:maximo]
    return ("Historial de ventas de SELEC: tipos de producto que SELEC ya ha vendido y facturado "
            "(si un producto solicitado es de uno de estos tipos, o muy parecido, es del rubro):\n"
            + "\n".join(lineas))


def coincidencias(items: list[dict]) -> list[tuple[str, str]]:
    """(descripción del ítem, ejemplo vendido) para los ítems cuyo tipo ya se vendió."""
    encontrados = []
    for it in items or []:
        texto = it.get("descripcion") or it.get("marca_modelo") or ""
        tipo = tipo_si_coincide(texto)
        if tipo:
            encontrados.append((texto[:80], _cache["ejemplos"].get(tipo, tipo)))
    return encontrados


def aplicar_historial(analisis: dict) -> dict:
    """Si Claude lo marcó fuera del rubro pero hay un producto de un tipo ya vendido, pasa a del rubro."""
    if analisis.get("relevante_selec"):
        return analisis
    encontrados = coincidencias(analisis.get("items"))
    if encontrados:
        descripcion, ejemplo = encontrados[0]
        analisis["relevante_selec"] = True
        analisis["motivo_relevancia"] = (
            f"Del rubro por historial de ventas: '{descripcion}' es similar a '{ejemplo}', ya vendido por SELEC."
        )[:500]
        analisis["por_historial"] = True
    return analisis


def resumen() -> dict:
    """Estado del historial, para revisarlo desde /cron/correos/historial."""
    tipos = tipos_vendidos()
    return {
        "columna": _cache["columna"],
        "articulos_leidos": _cache["filas"],
        "tipos_distintos": len(tipos),
        "tipos_que_cuentan": len(tipos_validos()),
        "error": _cache["error"],
        "top_50": [f"{t} ({n}) ej. {_cache['ejemplos'].get(t, '')}" for t, n in tipos.most_common(50)],
    }