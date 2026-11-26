
from copy import deepcopy

CAMPO_PRUEBA = "Registro_de_prueba_Sof_a"
PREFIJO = "[PRUEBA SOFIA]"


def marcar_registro_prueba(modulo, datos):
    if modulo not in ("Deals", "Cases"):
        raise ValueError("Modulo no permitido")

    if not isinstance(datos, dict):
        raise ValueError("Datos invalidos")

    campo_id = (
        "Retell_Call_ID"
        if modulo == "Deals"
        else "ID_de_llamada_Retell"
    )

    call_id = datos.get(campo_id)

    if (
        not isinstance(call_id, str)
        or not call_id.startswith("call_")
        or len(call_id) > 255
    ):
        raise ValueError("Falta identificador Retell")

    registro = deepcopy(datos)
    registro[CAMPO_PRUEBA] = True

    if modulo == "Deals":
        nombre = str(registro.get("Deal_Name") or "").strip()
        if not nombre:
            raise ValueError("Negocio sin nombre")
        if not nombre.startswith(PREFIJO):
            registro["Deal_Name"] = f"{PREFIJO} {nombre}"

    else:
        asunto = str(registro.get("Subject") or "").strip()
        if not asunto:
            raise ValueError("Caso sin asunto")

        descripcion = str(registro.get("Description") or "")
        if not descripcion.startswith(PREFIJO):
            registro["Description"] = (
                f"{PREFIJO}\n\n{descripcion}"
            )

    return registro
