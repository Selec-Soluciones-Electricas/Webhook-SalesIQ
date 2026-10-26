
import re
import unicodedata
from decimal import Decimal, InvalidOperation


def _normalizar_etiqueta(texto):
    return "".join(
        letra
        for letra in unicodedata.normalize("NFKD", texto.lower().strip())
        if not unicodedata.combining(letra)
    )


def convertir_productos_retell(texto):
    """Convierte los productos extraidos por Retell al formato de Zoho."""

    if not isinstance(texto, str) or not texto.strip():
        raise ValueError("No se recibieron productos")

    campos = {
        "descripcion": "descripcion",
        "marca": "marca",
        "numero de parte": "numero_parte",
        "cantidad": "cantidad",
    }

    productos = []

    for linea in texto.splitlines():
        if not linea.strip():
            continue

        partes = [parte.strip() for parte in linea.split("|")]

        if len(partes) != 5 or not re.fullmatch(
            r"producto\s+\d+", partes[0], flags=re.IGNORECASE
        ):
            raise ValueError("Formato de productos no reconocido")

        producto = {}

        for parte in partes[1:]:
            etiqueta, separador, valor = parte.partition(":")
            clave = campos.get(_normalizar_etiqueta(etiqueta))

            if not separador or not clave or clave in producto or not valor.strip():
                raise ValueError("Producto con campos incompletos o repetidos")

            producto[clave] = valor.strip()

        if set(producto) != set(campos.values()):
            raise ValueError("Faltan campos obligatorios del producto")

        try:
            cantidad = Decimal(producto["cantidad"].replace(",", "."))
        except InvalidOperation as exc:
            raise ValueError("Cantidad no numerica") from exc

        if not cantidad.is_finite() or cantidad <= 0:
            raise ValueError("La cantidad debe ser mayor que cero")

        producto["cantidad"] = format(cantidad.normalize(), "f")
        productos.append(producto)

    if not productos:
        raise ValueError("No se recibieron productos")

    return productos
