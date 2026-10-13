import json
import urllib.request


# =========================================================
# CONFIGURACIÓN OLLAMA
# =========================================================

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL_NAME = "qwen3:1.7b"


# =========================================================
# INFORMACIÓN OFICIAL SELEC
# =========================================================

SELEC_INFO = {

    "empresa": {
        "nombre": "SELEC",
        "descripcion": (
            "SELEC trabaja con soluciones y productos "
            "eléctricos, automatización, potencia y control, "
            "accionamiento eléctrico, telecomunicaciones "
            "e instrumentación."
        ),
    },


    "contacto": {

        "correo": "info@selec.cl",

        "chile": {
            "telefono_contacto": "(+56) 9 8894 3735",
            "telefono_oficina": "(+56) 2 6465 9750",
            "direccion": (
                "Av. Pedro de Valdivia 273, Of. 601, "
                "Providencia, Santiago"
            ),
        },

        "colombia": {
            "telefono": "(+57) 602 4856625",
            "direccion": (
                "Calle 2 oeste #26-40, Cali, Colombia"
            ),
        },
    },


    "portafolio": {

        "automatizacion": [
            "Sensores",
            "Actuadores",
            "Transductores",
            "Módulos I/O",
            "PLC",
        ],

        "potencia_y_control": [
            "Interruptores",
            "Contactores",
            "Fusibles",
            "Fuentes de poder",
            "UPS",
            "Baterías",
        ],

        "accionamiento_electrico": [
            "Variadores de frecuencia",
            "Partidores suaves",
            "Motores",
            "Guardamotores",
        ],

        "materiales_electricos": [
            "Cables",
            "Iluminación",
            "Enchufes",
            "Conectores",
            "Bornes",
            "Gabinetes",
        ],

        "telecomunicaciones": [
            "CCTV",
            "Routers",
            "Switches",
            "Equipos TI",
            "Racks",
        ],

        "instrumentos_de_medicion": [
            "Multímetros",
            "Termómetros",
            "Osciloscopios",
        ],

        "otros": [
            "Relés de protección",
            "Descansos para motores y molinos",
            "Accesorios",
            "Artículos tecnológicos",
        ],
    },


    "marcas": {

        "descripcion": (
            "SELEC trabaja con un portafolio multimarca. "
            "Entre las marcas disponibles en su portafolio "
            "se encuentran ABB, Siemens, Schneider, "
            "Allen Bradley, Festo, Danfoss, Legrand, Finder, "
            "IFM, Honeywell, Hikvision, SKF, Mean Well "
            "y otras."
        ),

        "regla": (
            "La disponibilidad de una marca o producto específico "
            "debe confirmarse mediante una solicitud de cotización."
        ),
    },


    "cotizacion": {

        "descripcion": (
            "Para solicitar precio, disponibilidad o cotizar "
            "un producto, repuesto, equipo o solución, el cliente "
            "debe utilizar la opción Solicitud de cotización."
        ),

        "datos_utiles": (
            "Si el cliente conoce el número de parte, marca, "
            "descripción o cantidad, puede incluir esos datos "
            "en su solicitud."
        ),
    },


    "postventa": {

        "descripcion": (
            "Para problemas relacionados con una compra existente, "
            "productos con inconvenientes, reclamos o consultas "
            "asociadas a una factura u Orden de Compra, el cliente "
            "debe utilizar la opción Servicio posventa."
        ),
    },


    "propuesta_de_valor": [
        "Portafolio multimarca",
        "Asesoría especializada",
        "Búsqueda de soluciones y productos",
        "Apoyo en la gestión de compras MRO",
    ],


    "reglas_comerciales": {

        "precios": (
            "Los precios no deben ser informados por el asistente. "
            "Deben solicitarse mediante una cotización."
        ),

        "stock": (
            "El asistente no debe confirmar stock o disponibilidad "
            "sin una cotización o validación comercial."
        ),

        "plazos": (
            "El asistente no debe inventar fechas ni plazos "
            "de entrega."
        ),

        "productos_especificos": (
            "Si el cliente pregunta si SELEC vende un producto "
            "específico, el asistente puede indicar si corresponde "
            "a una categoría del portafolio, pero debe recomendar "
            "una cotización para confirmar el producto exacto."
        ),
    },
}


# =========================================================
# CONEXIÓN CON OLLAMA
# =========================================================

def call_ollama(
    messages,
    json_mode=False,
):

    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "stream": False,
        "think": False,
    }


    if json_mode:
        payload["format"] = "json"


    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(
            payload
        ).encode(
            "utf-8"
        ),
        headers={
            "Content-Type": "application/json"
        },
        method="POST",
    )


    with urllib.request.urlopen(
        req,
        timeout=60
    ) as response:

        result = json.loads(
            response
            .read()
            .decode(
                "utf-8"
            )
        )


    return (
        result
        .get(
            "message",
            {}
        )
        .get(
            "content",
            ""
        )
        .strip()
    )


# =========================================================
# CLASIFICAR CONSULTA
# =========================================================

def clasificar_consulta(
    mensaje
):

    mensaje = str(
        mensaje or ""
    ).strip()


    if not mensaje:
        return "general"


    prompt = """
Eres un clasificador de consultas para SELEC.

Debes decidir si el mensaje del cliente corresponde a:

- general
- cotizacion
- postventa

DEFINICIONES:

cotizacion:
El cliente quiere comprar, cotizar, conocer precio,
disponibilidad comercial o solicitar un producto,
repuesto, equipo o solución.

Ejemplos:
- Necesito cotizar un contactor Siemens.
- ¿Cuánto cuesta este producto?
- Necesito comprar un variador.
- Quiero precio para 10 fusibles.

postventa:
El cliente ya realizó una compra y tiene un problema,
reclamo, falla, producto dañado, garantía o consulta
relacionada con una factura u Orden de Compra existente.

Ejemplos:
- El producto llegó dañado.
- Tengo un problema con mi compra.
- Necesito hacer un reclamo.
- Tengo una factura y necesito soporte.
- El equipo que compré no funciona.

general:
Preguntas informativas sobre SELEC que no requieren
crear una cotización ni un caso de postventa.

Ejemplos:
- ¿Cuál es el correo?
- ¿Cuál es el teléfono?
- ¿Dónde están ubicados?
- ¿Tienen oficina en Colombia?
- ¿Cómo me comunico con ustedes?
- ¿Qué productos venden?
- ¿Qué marcas trabajan?

REGLAS:

- No inventes categorías nuevas.
- Devuelve solamente JSON válido.
- No escribas explicaciones.

FORMATO:

{
    "tipo": "general"
}
"""


    try:

        respuesta = call_ollama(
            [
                {
                    "role": "system",
                    "content": prompt,
                },
                {
                    "role": "user",
                    "content": mensaje,
                },
            ],
            json_mode=True,
        )


        resultado = json.loads(
            respuesta
        )


        tipo = str(
            resultado.get(
                "tipo",
                ""
            )
        ).strip().lower()


        if tipo in {
            "general",
            "cotizacion",
            "postventa",
        }:

            return tipo


    except Exception as error:

        print(
            "[OLLAMA] Error clasificando consulta:",
            error
        )


    # =====================================================
    # RESPALDO SI OLLAMA NO CLASIFICA
    # =====================================================

    texto = mensaje.lower()


    palabras_postventa = [
        "postventa",
        "posventa",
        "reclamo",
        "garantía",
        "garantia",
        "dañado",
        "dañada",
        "falló",
        "fallo",
        "no funciona",
        "problema con mi compra",
        "producto llegó",
        "producto llego",
    ]


    if any(
        palabra in texto
        for palabra in palabras_postventa
    ):

        return "postventa"


    palabras_cotizacion = [
        "cotizar",
        "cotización",
        "cotizacion",
        "precio",
        "comprar",
        "cuánto cuesta",
        "cuanto cuesta",
        "valor de",
        "necesito un",
        "necesito una",
    ]


    if any(
        palabra in texto
        for palabra in palabras_cotizacion
    ):

        return "cotizacion"


    return "general"


# =========================================================
# RESPUESTAS FRECUENTES DIRECTAS
# =========================================================

def respuesta_faq_directa(
    mensaje
):

    texto = str(
        mensaje or ""
    ).lower().strip()


    # -----------------------------------------------------
    # PRODUCTOS / PORTAFOLIO
    # -----------------------------------------------------

    if any(
        frase in texto
        for frase in [
            "qué productos",
            "que productos",
            "tipo de productos",
            "productos tienen",
            "productos disponibles",
            "qué venden",
            "que venden",
            "portafolio",
        ]
    ):

        return (
            "En SELEC puedes encontrar productos de automatización, "
            "potencia y control, accionamiento eléctrico, materiales "
            "eléctricos, telecomunicaciones e instrumentos de medición. "
            "Si buscas algo específico, dime qué producto necesitas."
        )


    # -----------------------------------------------------
    # CORREO
    # -----------------------------------------------------

    if any(
        palabra in texto
        for palabra in [
            "correo",
            "email",
            "e-mail",
        ]
    ):

        return (
            "Puedes comunicarte con SELEC al correo "
            "info@selec.cl."
        )


    # -----------------------------------------------------
    # TELÉFONO
    # -----------------------------------------------------

    if any(
        palabra in texto
        for palabra in [
            "teléfono",
            "telefono",
            "número de contacto",
            "numero de contacto",
            "llamar",
            "contacto telefónico",
            "contacto telefonico",
        ]
    ):

        if (
            "colombia" in texto
            or "cali" in texto
        ):

            return (
                "En Colombia puedes comunicarte con SELEC "
                "al (+57) 602 4856625."
            )


        return (
            "En Chile puedes comunicarte al "
            "(+56) 9 8894 3735. "
            "También contamos con el teléfono de oficina "
            "(+56) 2 6465 9750."
        )


    # -----------------------------------------------------
    # UBICACIÓN COLOMBIA
    # -----------------------------------------------------

    if (
        "colombia" in texto
        or "cali" in texto
    ):

        if any(
            palabra in texto
            for palabra in [
                "dónde",
                "donde",
                "dirección",
                "direccion",
                "ubicación",
                "ubicacion",
                "oficina",
                "sede",
            ]
        ):

            return (
                "SELEC cuenta con presencia en Cali, Colombia, "
                "en Calle 2 oeste #26-40."
            )


    # -----------------------------------------------------
    # UBICACIÓN CHILE
    # -----------------------------------------------------

    if any(
        frase in texto
        for frase in [
            "dónde están",
            "donde estan",
            "dirección",
            "direccion",
            "ubicación",
            "ubicacion",
            "oficina en chile",
            "sede en chile",
        ]
    ):

        return (
            "En Chile estamos ubicados en "
            "Av. Pedro de Valdivia 273, Of. 601, "
            "Providencia, Santiago."
        )


    # -----------------------------------------------------
    # MARCAS
    # -----------------------------------------------------

    if any(
        palabra in texto
        for palabra in [
            "marcas",
            "qué marcas",
            "que marcas",
        ]
    ):

        return (
            "SELEC trabaja con un portafolio multimarca que incluye "
            "ABB, Siemens, Schneider, Allen Bradley, Festo, Danfoss, "
            "Legrand, Finder, IFM, Honeywell, Hikvision, SKF, "
            "Mean Well y otras."
        )


    # -----------------------------------------------------
    # CÓMO COTIZAR
    # -----------------------------------------------------

    if any(
        frase in texto
        for frase in [
            "cómo cotizar",
            "como cotizar",
            "cómo solicito una cotización",
            "como solicito una cotizacion",
            "cómo pedir una cotización",
            "como pedir una cotizacion",
        ]
    ):

        return (
            "Puedes realizar una solicitud desde la opción "
            "Solicitud de cotización. "
            "Si tienes marca, número de parte o descripción "
            "del producto, puedes incluirlos para facilitar "
            "la gestión."
        )


    # -----------------------------------------------------
    # CÓMO SOLICITAR POSVENTA
    # -----------------------------------------------------

    if any(
        frase in texto
        for frase in [
            "cómo hago una postventa",
            "como hago una postventa",
            "cómo solicito posventa",
            "como solicito posventa",
            "cómo hago un reclamo",
            "como hago un reclamo",
            "cómo solicitar postventa",
            "como solicitar postventa",
        ]
    ):

        return (
            "Puedes registrar tu caso desde la opción "
            "Servicio posventa. "
            "Ten a mano tu número de factura u Orden de Compra "
            "y una breve descripción de lo ocurrido."
        )


    return None


# =========================================================
# RESPONDER ATENCIÓN AL CLIENTE
# =========================================================

def responder_atencion_cliente(
    mensaje
):

    # -----------------------------------------------------
    # PRIMERO BUSCAMOS UNA FAQ DIRECTA
    # -----------------------------------------------------

    respuesta_directa = (
        respuesta_faq_directa(
            mensaje
        )
    )


    if respuesta_directa:
        return respuesta_directa


    # -----------------------------------------------------
    # SI NO ES UNA FAQ CONOCIDA, CONSULTAMOS OLLAMA
    # -----------------------------------------------------

    informacion = json.dumps(
        SELEC_INFO,
        ensure_ascii=False,
        indent=2,
    )


    system_prompt = f"""
Eres el asistente virtual de atención al cliente de SELEC.

Debes responder solamente utilizando la información oficial
que aparece a continuación.

INFORMACIÓN OFICIAL:

{informacion}

REGLAS:

- Responde siempre en español latinoamericano.
- Sé cordial, profesional y natural.
- Responde como un asistente de WhatsApp.
- Las respuestas deben ser breves y fáciles de leer.
- Intenta responder en un máximo de 3 frases.
- No uses Markdown.
- No uses asteriscos.
- No uses títulos con símbolos.
- No entregues listas demasiado largas.
- Nunca inventes información.
- No inventes precios.
- No inventes stock.
- No inventes horarios.
- No inventes productos ni marcas que no estén
  en la información oficial.
- No uses conocimiento externo.
- Si la información solicitada no está disponible,
  dilo claramente.
- Si el cliente pregunta por un producto específico
  que pertenece al portafolio, puedes indicar que
  SELEC trabaja con esa categoría.
- La disponibilidad exacta de productos debe
  confirmarse mediante cotización.
- No menciones Ollama.
- No menciones el modelo de inteligencia artificial.
"""


    mensajes = [
        {
            "role": "system",
            "content": system_prompt,
        },
        {
            "role": "user",
            "content": str(
                mensaje or ""
            ).strip(),
        },
    ]


    try:

        respuesta = call_ollama(
            mensajes
        )


        if respuesta:
            return respuesta


    except Exception as error:

        print(
            "[OLLAMA] Error respondiendo:",
            error
        )


    return (
        "En este momento no pude procesar tu consulta. "
        "Puedes comunicarte con SELEC al correo "
        "info@selec.cl."
    )