import os
from dotenv import load_dotenv

load_dotenv()

from flask import Flask

from routes.webhook import register_routes
from services.zoho_service import get_access_token

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


# =========================================================
# CONFIGURACIÓN
# =========================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


if load_dotenv:
    load_dotenv(os.path.join(BASE_DIR, "credentials"))
    load_dotenv(os.path.join(BASE_DIR, ".env"))


# =========================================================
# APLICACIÓN FLASK
# =========================================================

app = Flask(__name__)


# =========================================================
# SESIONES
# =========================================================

sessions = {}


# =========================================================
# ZOHO
# =========================================================

access_token = get_access_token()


# =========================================================
# REGISTRO DE RUTAS
# =========================================================

register_routes(
    app,
    sessions,
    access_token,
)


# =========================================================
# DEBUG DE RUTAS
# =========================================================

print("=== RUTAS REGISTRADAS ===")
print(app.url_map)
print("=========================")


# =========================================================
# SERVIDOR
# =========================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            3001,
        )
    )

    debug_mode = (
        os.environ
        .get(
            "FLASK_DEBUG",
            "false",
        )
        .strip()
        .lower()
        == "true"
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=debug_mode,
    )