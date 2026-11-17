
from flask import Flask, jsonify
from dotenv import load_dotenv

# Cargar configuración local para pruebas.
# En Render utilizaremos variables de entorno.
load_dotenv()

# Importar únicamente las rutas de Sofía.
from routes.retell_webhook import retell_bp
from routes.sofia_funciones import sofia_funciones_bp
from routes.cron_sofia import register_sofia_cron_routes

app = Flask(__name__)

# Eventos de llamadas de Retell.
app.register_blueprint(retell_bp)

# Funciones de Sofía.
app.register_blueprint(sofia_funciones_bp)

# Cron independiente de Sofía.
# Las escrituras CRM permanecen desactivadas.
register_sofia_cron_routes(app)


@app.get("/health")
def health():
    return jsonify({
        "servicio": "sofia",
        "estado": "ok"
    }), 200
