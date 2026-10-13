from flask import (
    Blueprint,
    Flask,
    render_template,
    request,
    jsonify,
)
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
import sys
import uuid


# =========================================================
# ACCESO AL PROYECTO PRINCIPAL
# =========================================================

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# Cargar las mismas credenciales que utiliza el chatbot
load_dotenv(
    PROJECT_ROOT / ".env",
    override=True
)


# =========================================================
# INTEGRACIÓN EXISTENTE CON ZOHO CRM
# =========================================================

from conversation.quotation import (
    registrar_cotizacion_en_zoho,
)

from services.email_service import (
    enviar_correo_owner,
)

from utils.email_postventa import (
    enviar_correo_postventa,
)

from services.ollama_service import (
    responder_atencion_cliente,
    clasificar_consulta,
)


formulario_mvp_bp = Blueprint(
    "formulario_mvp",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/formulario-static",
)


# Mantenemos el nombre "app" dentro de este archivo
# para no tener que modificar todas las rutas existentes.
app = formulario_mvp_bp


# Guardaremos temporalmente las solicitudes del MVP en memoria.
# Para la reunión es suficiente.
solicitudes = []


# =========================================================
# INICIO
# =========================================================

@app.route("/formulario")
def inicio():

    return render_template(
        "inicio.html"
    )


# =========================================================
# COTIZACIÓN
# =========================================================

@app.route(
    "/solicitud/cotizacion",
    methods=["GET", "POST"]
)
def cotizacion():

    if request.method == "GET":

        return render_template(
            "cotizacion.html"
        )


    # =====================================================
    # ORIGEN
    # =====================================================

    origen = request.form.get(
        "origen",
        ""
    ).strip().lower()


    if origen not in {
        "web",
        "whatsapp",
    }:

        origen = "no_identificado"


    # =====================================================
    # DATOS GENERALES
    # =====================================================

    empresa = request.form.get(
        "empresa",
        ""
    ).strip()


    rut_empresa = request.form.get(
        "rut_empresa",
        ""
    ).strip()


    contacto = request.form.get(
        "contacto",
        ""
    ).strip()


    correo = request.form.get(
        "correo",
        ""
    ).strip()


    telefono = request.form.get(
        "telefono",
        ""
    ).strip()


    direccion_entrega = request.form.get(
        "direccion_entrega",
        ""
    ).strip()


    # =====================================================
    # VALIDACIONES GENERALES
    # =====================================================

    if not empresa:

        return (
            "Debes indicar la empresa.",
            400
        )


    if not rut_empresa:

        return (
            "Debes indicar el RUT de la empresa.",
            400
        )


    if not contacto:

        return (
            "Debes indicar un nombre de contacto.",
            400
        )


    # -----------------------------------------------------
    # CORREO AHORA ES OBLIGATORIO
    # -----------------------------------------------------

    if not correo:

        return (
            "Debes indicar un correo de contacto.",
            400
        )


    # -----------------------------------------------------
    # TELÉFONO ES OPCIONAL
    # -----------------------------------------------------

    # No realizamos validación obligatoria
    # sobre telefono.


    # =====================================================
    # ENTREGA
    # =====================================================

    if not direccion_entrega:

        direccion_entrega = (
            "Bodega SELEC"
        )


    # =====================================================
    # RECIBIR PRODUCTOS
    # =====================================================

    uids = request.form.getlist(
        "producto_uid[]"
    )


    numeros_parte = request.form.getlist(
        "producto_numero_parte[]"
    )


    marcas = request.form.getlist(
        "producto_marca[]"
    )


    descripciones = request.form.getlist(
        "producto_descripcion[]"
    )


    cantidades = request.form.getlist(
        "producto_cantidad[]"
    )


    productos = []

    productos_para_solicitud = []


    # =====================================================
    # PROCESAR PRODUCTOS UNO POR UNO
    # =====================================================

    total_filas = max(
        len(uids),
        len(numeros_parte),
        len(marcas),
        len(descripciones),
        len(cantidades),
    )


    for indice in range(
        total_filas
    ):

        uid = (
            str(
                uids[indice]
            ).strip()
            if indice < len(uids)
            else str(
                indice + 1
            )
        )


        numero_parte = (
            str(
                numeros_parte[indice]
            ).strip()
            if indice < len(
                numeros_parte
            )
            else ""
        )


        marca = (
            str(
                marcas[indice]
            ).strip()
            if indice < len(
                marcas
            )
            else ""
        )


        descripcion = (
            str(
                descripciones[indice]
            ).strip()
            if indice < len(
                descripciones
            )
            else ""
        )


        cantidad_raw = (
            str(
                cantidades[indice]
            ).strip()
            if indice < len(
                cantidades
            )
            else "1"
        )


        # =================================================
        # ARCHIVOS DEL PRODUCTO
        # =================================================

        archivos = request.files.getlist(
            f"producto_archivos_{uid}"
        )


        archivos = [
            archivo
            for archivo in archivos
            if archivo
            and str(
                archivo.filename or ""
            ).strip()
        ]


        # =================================================
        # IGNORAR FILA COMPLETAMENTE VACÍA
        # =================================================

        tiene_informacion = bool(
            numero_parte
            or marca
            or descripcion
            or archivos
        )


        if not tiene_informacion:

            continue


        # =================================================
        # DESCRIPCIÓN OBLIGATORIA POR PRODUCTO
        # =================================================

        if not descripcion:

            return (
                "Cada producto debe tener una descripción.",
                400
            )


        # =================================================
        # CANTIDAD
        # =================================================

        if not cantidad_raw:

            cantidad_raw = "1"


        try:

            cantidad_numero = int(
                cantidad_raw
            )

        except (
            ValueError,
            TypeError,
        ):

            return (
                "La cantidad de cada producto debe ser "
                "un número entero.",
                400
            )


        if cantidad_numero <= 0:

            return (
                "La cantidad de cada producto debe ser "
                "mayor a 0.",
                400
            )


        cantidad = str(
            cantidad_numero
        )


        # =================================================
        # PRODUCTO PARA PROCESAMIENTO INTERNO / CRM
        # =================================================

        producto = {

            "uid":
                uid,

            "numero_parte":
                numero_parte,

            "marca":
                marca,

            "descripcion":
                descripcion,

            "cantidad":
                cantidad,

            # Aquí mantenemos los archivos reales.
            # Más adelante los utilizaremos para subirlos
            # a Zoho.
            "archivos":
                archivos,
        }


        productos.append(
            producto
        )


        # =================================================
        # PRODUCTO PARA LOG / /SOLICITUDES
        # =================================================
        #
        # No guardamos el objeto FileStorage porque no se
        # puede convertir directamente a JSON.
        # Guardamos solamente los nombres.
        # =================================================

        productos_para_solicitud.append({

            "uid":
                uid,

            "numero_parte":
                numero_parte,

            "marca":
                marca,

            "descripcion":
                descripcion,

            "cantidad":
                cantidad,

            "archivos": [
                str(
                    archivo.filename
                ).strip()
                for archivo in archivos
            ],
        })


    # =====================================================
    # DEBE EXISTIR AL MENOS UN PRODUCTO
    # =====================================================

    if not productos:

        return (
            "Debes agregar al menos un producto.",
            400
        )


    # =====================================================
    # CANTIDAD DE PRODUCTOS
    # =====================================================
    #
    # IMPORTANTE:
    #
    # Esto representa cuántos productos diferentes
    # fueron agregados.
    #
    # Ejemplo:
    #
    # Producto A -> 5 unidades
    # Producto B -> 8 unidades
    #
    # cantidad_productos_solicitados = 2
    #
    # NO 13.
    # =====================================================

    cantidad_productos_solicitados = (
        len(
            productos
        )
    )


    # =====================================================
    # SOLICITUD
    # =====================================================

    solicitud = {

        "id": str(
            uuid.uuid4()
        ),

        "tipo":
            "cotizacion",

        "origen":
            origen,

        "fecha":
            datetime.now().strftime(
                "%d/%m/%Y %H:%M:%S"
            ),

        "empresa":
            empresa,

        "rut_empresa":
            rut_empresa,

        "contacto":
            contacto,

        "correo":
            correo,

        "telefono":
            telefono,

        "direccion_entrega":
            direccion_entrega,

        "cantidad_productos_solicitados":
            cantidad_productos_solicitados,

        "productos":
            productos_para_solicitud,
    }


    # =====================================================
    # ADAPTAR AL FORMATO DEL BACKEND DE COTIZACIÓN
    # =====================================================
    #
    # Conservamos temporalmente los campos antiguos
    # utilizando el primer producto.
    #
    # Esto evita romper las funciones actuales mientras
    # hacemos en el siguiente paso la modificación de Zoho
    # para trabajar realmente con todos los productos.
    # =====================================================

    primer_producto = (
        productos[0]
    )


    datos_crm = {

        "empresa":
            empresa,

        "rut":
            rut_empresa,

        "contacto":
            contacto,

        "correo":
            correo,

        "telefono":
            telefono,

        "direccion_entrega":
            direccion_entrega,

        "origen":
            origen,


        # ---------------------------------------------
        # ESTRUCTURA NUEVA
        # ---------------------------------------------

        "productos":
            productos,

        "cantidad_productos_solicitados":
            cantidad_productos_solicitados,


        # ---------------------------------------------
        # COMPATIBILIDAD TEMPORAL
        # ---------------------------------------------

        "num_parte":
            primer_producto[
                "numero_parte"
            ],

        "marca":
            primer_producto[
                "marca"
            ],

        "descripcion":
            primer_producto[
                "descripcion"
            ],

        "cantidad":
            primer_producto[
                "cantidad"
            ],
    }


    # =====================================================
    # REGISTRAR EN ZOHO CRM
    # =====================================================
    #
    # IMPORTANTE:
    #
    # Este bloque todavía utiliza la lógica CRM actual.
    # En el siguiente cambio modificaremos
    # registrar_cotizacion_en_zoho() y crear_deal_en_zoho()
    # para que utilicen:
    #
    # - todos los productos;
    # - cantidad de productos solicitados;
    # - nuevo nombre aleatorio del negocio;
    # - Patricio como Owner;
    # - Oferta entregada a tiempo en blanco;
    # - archivos;
    # - Bodega SELEC.
    # =====================================================

    try:

        owner, deal_resp, deal_id = (
            registrar_cotizacion_en_zoho(
                datos_crm
            )
        )


    except Exception as error:

        print(
            "[FORMULARIO] "
            "Error registrando cotización:",
            error
        )


        return (
            "No fue posible registrar la solicitud "
            "en Zoho CRM.",
            500
        )


    # =====================================================
    # VALIDAR NEGOCIO
    # =====================================================

    if not deal_id:

        print(
            "[FORMULARIO] "
            "Zoho no devolvió Deal ID."
        )


        return (
            "La solicitud fue recibida, pero no fue "
            "posible crear el negocio en Zoho CRM.",
            502
        )


    # =====================================================
    # INFORMACIÓN CRM
    # =====================================================

    solicitud[
        "crm_deal_id"
    ] = str(
        deal_id
    )


    solicitud[
        "crm_owner"
    ] = (
        (owner or {}).get(
            "nombre",
            ""
        )
    )


    # =====================================================
    # NOTIFICAR POR CORREO
    # =====================================================
    #
    # Este correo todavía será ajustado posteriormente:
    #
    # - Patricio como destinatario.
    # - "Negocio" en vez de "Deal".
    # - Link de Zoho One.
    # =====================================================

    try:

        respuesta_correo = (
            enviar_correo_owner(

                owner,

                str(
                    deal_id
                ),

                (
                    "Cotización - "
                    f"{empresa}"
                ),

                datos_crm,
            )
        )


        if (
            respuesta_correo is not None
            and respuesta_correo.status_code
            in (
                200,
                201,
            )
        ):

            print(
                "[FORMULARIO] "
                "Correo enviado al owner:",
                (owner or {}).get(
                    "nombre",
                    ""
                )
            )


        else:

            print(
                "[FORMULARIO] "
                "El negocio fue creado, "
                "pero no fue posible confirmar "
                "el envío del correo al owner."
            )


    except Exception as error:

        print(
            "[FORMULARIO] "
            "Error enviando correo al owner:",
            error
        )


    # =====================================================
    # GUARDAR SOLICITUD TEMPORALMENTE
    # =====================================================

    solicitudes.append(
        solicitud
    )


    # =====================================================
    # LOG
    # =====================================================

    print("")
    print(
        "=============================================="
    )
    print(
        "NUEVA SOLICITUD DE COTIZACIÓN"
    )
    print(
        "=============================================="
    )


    print(
        "Empresa:",
        empresa
    )


    print(
        "RUT:",
        rut_empresa
    )


    print(
        "Contacto:",
        contacto
    )


    print(
        "Correo:",
        correo
    )


    print(
        "Teléfono:",
        telefono or "(no informado)"
    )


    print(
        "Entrega:",
        direccion_entrega
    )


    print(
        "Cantidad de productos solicitados:",
        cantidad_productos_solicitados
    )


    for indice, producto in enumerate(
        productos_para_solicitud,
        start=1
    ):

        print("")
        print(
            f"Producto {indice}:"
        )

        print(
            "  Número de parte:",
            producto[
                "numero_parte"
            ] or "(no informado)"
        )

        print(
            "  Marca:",
            producto[
                "marca"
            ] or "(no informada)"
        )

        print(
            "  Descripción:",
            producto[
                "descripcion"
            ]
        )

        print(
            "  Cantidad:",
            producto[
                "cantidad"
            ]
        )

        print(
            "  Archivos:",
            producto[
                "archivos"
            ] or "(sin archivos)"
        )


    print("")
    print(
        "=============================================="
    )
    print("")


    # =====================================================
    # CONFIRMACIÓN
    # =====================================================

    return render_template(
        "confirmacion.html",
        tipo="cotizacion",
        solicitud=solicitud
    )

# =========================================================
# POSTVENTA
# =========================================================

@app.route(
    "/solicitud/postventa",
    methods=["GET", "POST"]
)
def postventa():

    if request.method == "GET":

        return render_template(
            "postventa.html"
        )


    # =====================================================
    # DATOS DEL FORMULARIO
    # =====================================================

    origen = request.form.get(
        "origen",
        ""
    ).strip().lower()


    if origen not in {
        "web",
        "whatsapp",
    }:
        origen = "no_identificado"


    archivos_postventa = [
        archivo
        for archivo in request.files.getlist(
            "archivos_postventa"
        )
        if archivo
        and str(
            getattr(
                archivo,
                "filename",
                ""
            )
            or ""
        ).strip()
    ]


    solicitud = {

        "id": str(
            uuid.uuid4()
        ),

        "tipo": "postventa",

        "origen": origen,

        "fecha": datetime.now().strftime(
            "%d/%m/%Y %H:%M:%S"
        ),

        "nombre_postventa": request.form.get(
            "nombre_postventa",
            ""
        ).strip(),

        "correo_postventa": request.form.get(
            "correo_postventa",
            ""
        ).strip(),

        "rut_postventa": request.form.get(
            "rut_postventa",
            ""
        ).strip(),

        "factura_oc": request.form.get(
            "factura_oc",
            ""
        ).strip(),

        "descripcion_postventa": request.form.get(
            "descripcion_postventa",
            ""
        ).strip(),

        "archivos_postventa": [
            str(
                archivo.filename
            ).strip()
            for archivo in archivos_postventa
        ],
    }

    if not solicitud["correo_postventa"]:

            return (
            "Debes indicar un correo de contacto.",
            400
        )


    # =====================================================
    # ADAPTAR FORMULARIO AL FORMATO DE POSTVENTA ACTUAL
    # =====================================================

    datos_postventa = {

        "nombre":
            solicitud["nombre_postventa"],

        "correo":
            solicitud["correo_postventa"],

        "rut":
            solicitud["rut_postventa"],

        "numero_factura":
            solicitud["factura_oc"],

        "detalle":
            solicitud["descripcion_postventa"],

        "origen":
            solicitud["origen"],

        # Archivos reales recibidos desde el formulario.
        # Estos se utilizarán para adjuntarlos al Case.
        "archivos":
            archivos_postventa,
    }


    # =====================================================
    # REGISTRAR POSTVENTA EN ZOHO CRM
    # =====================================================

    try:

        resultado = (
            enviar_correo_postventa(
                datos_postventa
            )
        )

    except Exception as error:

        print(
            "[FORMULARIO] Error registrando postventa:",
            error
        )

        return (
            "No fue posible registrar la solicitud "
            "de postventa en Zoho CRM.",
            500
        )


    # =====================================================
    # VALIDAR CASE
    # =====================================================

    case_id = str(
        resultado.get(
            "case_id",
            ""
        )
    ).strip()


    if not case_id:

        print(
            "[FORMULARIO] Zoho no devolvió Case ID."
        )

        return (
            "La solicitud fue recibida, pero no fue "
            "posible crear el caso en Zoho CRM.",
            502
        )


    solicitud["crm_case_id"] = (
        case_id
    )


    # =====================================================
    # GUARDAR SOLICITUD TEMPORALMENTE
    # =====================================================

    solicitudes.append(
        solicitud
    )


    # =====================================================
    # LOG
    # =====================================================

    print("")
    print(
        "=============================================="
    )
    print(
        "NUEVA SOLICITUD DE POSVENTA"
    )
    print(
        "=============================================="
    )

    for clave, valor in solicitud.items():

        print(
            f"{clave}: {valor}"
        )

    print(
        "=============================================="
    )
    print("")


    # =====================================================
    # CONFIRMACIÓN
    # =====================================================

    return render_template(
        "confirmacion.html",
        tipo="postventa",
        solicitud=solicitud
    )


# =========================================================
# PANTALLA ATENCIÓN AL CLIENTE
# =========================================================

@app.route(
    "/atencion-cliente",
    methods=["GET"]
)
def vista_atencion_cliente():

    return render_template(
        "atencion.html"
    )

# =========================================================
# ATENCIÓN AL CLIENTE - OLLAMA
# =========================================================

@app.route(
    "/api/atencion",
    methods=["POST"]
)
def atencion_cliente():

    body = request.get_json(
        silent=True
    ) or {}


    mensaje = str(
        body.get(
            "mensaje",
            ""
        )
    ).strip()


    if not mensaje:

        return jsonify({
            "ok": False,
            "error": "Debes escribir una consulta."
        }), 400


    tipo = clasificar_consulta(
        mensaje
    )


    # =====================================================
    # DERIVAR A COTIZACIÓN
    # =====================================================

    if tipo == "cotizacion":

        return jsonify({
            "ok": True,
            "accion": "cotizacion",
            "respuesta": (
                "Claro. Para gestionar tu solicitud "
                "de cotización, puedes completar el "
                "formulario de cotización."
            ),
        })


    # =====================================================
    # DERIVAR A POSVENTA
    # =====================================================

    if tipo == "postventa":

        return jsonify({
            "ok": True,
            "accion": "postventa",
            "respuesta": (
                "Claro. Para ayudarte con este caso, "
                "puedes registrar una solicitud de "
                "posventa."
            ),
        })


    # =====================================================
    # CONSULTA GENERAL
    # =====================================================

    respuesta = responder_atencion_cliente(
        mensaje
    )


    return jsonify({
        "ok": True,
        "accion": "general",
        "respuesta": respuesta,
    })


# =========================================================
# VER SOLICITUDES DEL MVP
# =========================================================

@app.route("/solicitudes")
def ver_solicitudes():

    return {

        "total":
            len(solicitudes),

        "solicitudes":
            solicitudes,
    }


# =========================================================
# EJECUCIÓN LOCAL
# =========================================================

if __name__ == "__main__":

    local_app = Flask(__name__)

    local_app.register_blueprint(
        formulario_mvp_bp
    )

    print(
        "MVP FORMULARIO SELEC iniciado"
    )

    print(
        "http://localhost:3003"
    )

    local_app.run(
        host="127.0.0.1",
        port=3003,
        debug=True,
    )