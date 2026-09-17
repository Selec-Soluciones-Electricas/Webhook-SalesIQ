import json
from pathlib import Path


# =========================================================
# RUTA DEL FLOW
# =========================================================

BASE_DIR = Path(__file__).resolve().parent.parent

FLOW_PATH = (
    BASE_DIR
    / "whatsapp_flows"
    / "selec_solicitudes.json"
)


# =========================================================
# CARGAR FLOW JSON
# =========================================================

def cargar_flow_json() -> dict:
    """
    Carga el Flow JSON de SELEC desde el proyecto.
    """

    if not FLOW_PATH.exists():
        raise FileNotFoundError(
            f"No se encontró el Flow JSON en: {FLOW_PATH}"
        )

    with FLOW_PATH.open(
        "r",
        encoding="utf-8",
    ) as archivo:

        return json.load(
            archivo
        )


# =========================================================
# VALIDACIÓN BÁSICA
# =========================================================

def validar_flow_json() -> bool:
    """
    Realiza una validación básica local.

    Esto NO reemplaza la validación oficial de Meta,
    pero permite detectar errores simples antes de subirlo.
    """

    flow = cargar_flow_json()

    if not isinstance(
        flow,
        dict,
    ):
        raise ValueError(
            "El Flow debe ser un objeto JSON."
        )

    version = flow.get(
        "version"
    )

    screens = flow.get(
        "screens"
    )

    if not version:
        raise ValueError(
            "El Flow no tiene campo 'version'."
        )

    if not isinstance(
        screens,
        list,
    ):
        raise ValueError(
            "El Flow no contiene una lista válida de 'screens'."
        )

    if not screens:
        raise ValueError(
            "El Flow no contiene pantallas."
        )

    ids = set()

    for screen in screens:

        screen_id = str(
            screen.get(
                "id",
                "",
            )
        ).strip()

        if not screen_id:
            raise ValueError(
                "Existe una pantalla sin ID."
            )

        if screen_id in ids:
            raise ValueError(
                f"ID de pantalla duplicado: {screen_id}"
            )

        ids.add(
            screen_id
        )

    return True


# =========================================================
# TEST LOCAL
# =========================================================

if __name__ == "__main__":

    try:

        validar_flow_json()

        flow = cargar_flow_json()

        print(
            "Flow JSON cargado correctamente."
        )

        print(
            "Versión:",
            flow.get("version")
        )

        print(
            "Pantallas:",
            len(
                flow.get(
                    "screens",
                    [],
                )
            )
        )

        print(
            "IDs:"
        )

        for screen in flow.get(
            "screens",
            []
        ):

            print(
                "-",
                screen.get("id")
            )

    except Exception as error:

        print(
            "ERROR:",
            error
        )