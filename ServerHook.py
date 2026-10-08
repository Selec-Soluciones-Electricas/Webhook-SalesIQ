import os

# =========================================================
# CONFIGURACIÓN (cargar variables ANTES de importar rutas)
# =========================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv:
    load_dotenv(os.path.join(BASE_DIR, "credentials"))
    load_dotenv(os.path.join(BASE_DIR, ".env"))

from flask import Flask

from routes.webhook import register_routes
from routes.cron import register_cron_routes
from routes.reparacion import register_reparacion_routes
from routes.excel_routes import excel_bp
from services.zoho_service import get_access_token


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

register_cron_routes(app)

register_reparacion_routes(app)

app.register_blueprint(excel_bp)


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