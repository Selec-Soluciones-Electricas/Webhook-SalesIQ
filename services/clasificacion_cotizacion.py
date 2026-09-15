"""
Clasificación del resultado de un chat de cotización a partir
de su transcripción completa.

Misma lógica validada en el script retag_historial.py (usado
para el etiquetado retroactivo de los chats históricos) — se
mantiene aquí como copia para el job de reconciliación en vivo,
ya que ambos son proyectos/ejecuciones independientes.

Si alguna vez cambias los mensajes de finalizar_cotizacion() en
conversation/quotation.py, actualiza también estas constantes.
"""

FRASE_EXITO = "Un ejecutivo de Selec se pondrá"
FRASE_ERROR = "ocurrió un inconveniente al registrarla"

# Texto del botón "Servicio postventa" del menú principal — si
# aparece en la transcripción como mensaje del propio visitante,
# indica que en algún momento entró a esa rama. No descalifica
# por sí solo (ver decidir_resultado): un chat puede haber
# tocado postventa y luego completado una cotización real.
FRASE_POSTVENTA = "Servicio postventa"


def decidir_resultado(texto_completo: str) -> str:
    """
    Devuelve uno de: "OK", "ERROR", "POSTVENTA", "SIN_DATOS".

    Orden de prioridad: primero se revisa si la cotización se
    completó (éxito o error) — esto manda incluso si el chat
    también tocó el menú de postventa en algún punto (ej. el
    visitante lo eligió por error y luego volvió). Solo si NO
    hay ninguna señal de cotización completada se revisa si fue
    puramente un chat de postventa (se excluye) o si quedó
    genuinamente incompleto.
    """

    texto_completo = texto_completo or ""

    if FRASE_ERROR in texto_completo:
        return "ERROR"

    if FRASE_EXITO in texto_completo:
        return "OK"

    if FRASE_POSTVENTA in texto_completo:
        return "POSTVENTA"

    return "SIN_DATOS"