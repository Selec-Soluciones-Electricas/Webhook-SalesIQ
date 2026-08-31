# Bot de WhatsApp - Webhook SalesIQ

## Descripción

Este proyecto corresponde a un bot de WhatsApp integrado con Zoho SalesIQ.

El proyecto funciona como un backend desarrollado en Python y Flask. Recibe los mensajes enviados por los clientes mediante un Webhook, identifica el estado actual de la conversación y procesa la información de acuerdo con el flujo correspondiente.

El sistema permite principalmente:

* Gestionar conversaciones mediante WhatsApp y Zoho SalesIQ.
* Gestionar solicitudes de cotización.
* Gestionar solicitudes de postventa.
* Recopilar información de empresas, contactos y productos.
* Validar información recibida.
* Crear y actualizar registros en Zoho CRM.
* Crear y actualizar empresas, contactos y negocios.
* Asignar propietarios a los registros.
* Enviar correos asociados a las solicitudes.
* Enviar alertas cuando una solicitud de cotización queda incompleta.
* Procesar cantidades escritas con números o con palabras.
* Mantener información de la conversación mediante sesiones.
* Sincronizar información de los negocios con Zoho Creator.
* Mantener el propietario del negocio sincronizado entre Zoho CRM y Zoho Creator.

---

# Tecnologías utilizadas

* Python
* Flask
* Requests
* python-dotenv
* Zoho SalesIQ
* Zoho CRM
* Zoho Creator
* Railway

### ¿Para qué sirve cada una?

* **Python:** es el lenguaje principal utilizado para desarrollar el bot.
* **Flask:** permite crear el servidor y recibir las peticiones del Webhook.
* **Requests:** permite realizar peticiones HTTP a las APIs de Zoho.
* **python-dotenv:** permite cargar configuraciones y credenciales mediante variables de entorno.
* **Zoho SalesIQ:** permite gestionar las conversaciones con los clientes.
* **Zoho CRM:** permite almacenar y administrar empresas, contactos y negocios.
* **Zoho Creator:** permite trabajar con información relacionada con licitaciones y cotizaciones.
* **Railway:** permite desplegar y ejecutar el servidor.

---

# Estructura actual del proyecto

La estructura actual es:

```text
Webhook-SalesIQ/
│
├── ServerHook.py
├── Procfile
├── requirements.txt
├── README.md
├── .gitignore
│
├── routes/
│   └── webhook.py
│
├── services/
│   ├── email_service.py
│   ├── salesiq_service.py
│   └── zoho_service.py
│
├── conversation/
│   ├── state_machine.py
│   ├── quotation.py
│   └── postventa.py
│
├── validators/
│   ├── email.py
│   ├── phone.py
│   └── rut.py
│
├── utils/
│   └── security.py
│
└── frontend/
    └── index.html
```

## ServerHook.py

Es el archivo que actualmente inicia la aplicación Flask.

Se encarga principalmente de:

* Cargar las variables de entorno.
* Crear la aplicación Flask.
* Crear la estructura de sesiones.
* Obtener el token de Zoho.
* Registrar las rutas del Webhook.
* Iniciar el servidor.

El proyecto **no utiliza actualmente `app.py` como archivo principal**.

Para iniciar el proyecto se utiliza:

```bash
python ServerHook.py
```

---

# routes/

## routes/webhook.py

Contiene las rutas principales del servidor.

Entre ellas:

```text
/
```

Ruta utilizada para comprobar que el servidor está funcionando.

```text
/test
```

Frontend utilizado para realizar pruebas locales.

```text
/salesiq-webhook
```

Endpoint utilizado para recibir los eventos provenientes de Zoho SalesIQ.

El Webhook procesa principalmente eventos como:

* `trigger`
* `message`

También identifica al visitante y recupera la sesión correspondiente.

---

# services/

## services/salesiq_service.py

Contiene funciones relacionadas con Zoho SalesIQ.

Entre otras responsabilidades permite:

* Obtener el mensaje recibido.
* Obtener el identificador del visitante.
* Procesar información proveniente de SalesIQ.

---

## services/zoho_service.py

Contiene la integración principal con Zoho CRM.

Entre las funciones implementadas se encuentran:

* Obtener el Access Token.
* Mantener una caché temporal del token.
* Normalizar propietarios.
* Crear o buscar Accounts.
* Crear o actualizar Contacts.
* Crear Deals.
* Asociar Accounts y Contacts al Deal.
* Asignar propietarios.

---

## services/email_service.py

Contiene la lógica relacionada con los correos enviados por el sistema.

Actualmente se utiliza para diferentes tipos de notificaciones, entre ellas:

* Correo al propietario de una cotización.
* Correo de primer contacto.
* Alerta de solicitud de cotización incompleta.

---

# conversation/

## conversation/state_machine.py

Contiene la máquina de estados de la conversación.

Los estados permiten saber en qué etapa se encuentra actualmente el cliente.

Entre los estados utilizados se encuentran:

```text
inicio
menu_principal
cotizacion_empresa_bloque
cotizacion_producto_bloque
cotizacion_bloque
postventa_bloque
```

El flujo general es:

```text
Inicio
  ↓
Menú principal
  ↓
┌───────────────────────┐
│                       │
↓                       ↓
Cotización           Postventa
│                       │
↓                       ↓
Empresa                Datos
│
↓
Producto
│
↓
Validación
│
↓
Zoho CRM
```

---

## conversation/quotation.py

Contiene la lógica principal del flujo de cotización.

Se encarga de:

* Procesar los datos de empresa.
* Procesar los datos de contacto.
* Procesar los datos del producto.
* Extraer información de mensajes.
* Validar campos.
* Procesar cantidades.
* Crear el resumen.
* Registrar la cotización en Zoho CRM.
* Enviar alertas cuando faltan datos.

---

## conversation/postventa.py

Contiene el flujo correspondiente a las solicitudes de postventa.

Actualmente solicita:

```text
Nombre
RUT
Número de factura
Descripción del problema
```

---

# validators/

## validators/email.py

Contiene la extracción y validación básica del correo electrónico.

Se utiliza para identificar correos dentro de los mensajes recibidos.

---

## validators/phone.py

Contiene funciones relacionadas con teléfonos.

Permite:

* Limpiar caracteres no numéricos.
* Obtener solamente los dígitos.
* Comprobar si un teléfono tiene una longitud plausible.

---

## validators/rut.py

Contiene la validación básica del RUT.

Actualmente se comprueba que el valor tenga una estructura plausible y una cantidad razonable de dígitos.

No se utiliza actualmente un cálculo completo del dígito verificador mediante módulo 11.

---

# utils/

## utils/security.py

Contiene funciones relacionadas con la protección de información sensible en los logs.

Se implementó el enmascaramiento de:

* Correos.
* Teléfonos.
* RUT.
* IDs.
* Información del visitante.
* IDs de conversación.
* Información del propietario.

Por ejemplo, en lugar de mostrar completamente un correo o teléfono en los logs, se muestra una versión parcialmente protegida.

También existe una función para limpiar el payload recibido desde SalesIQ antes de imprimirlo en los logs.

---

# Arquitectura

El proyecto utiliza principalmente una arquitectura basada en:

* Webhook.
* Máquina de estados.
* Servicios separados.
* Validadores.
* Sesiones en memoria.

No corresponde exactamente al patrón MVC tradicional.

El flujo principal es:

```text
Cliente
   ↓
WhatsApp
   ↓
Zoho SalesIQ
   ↓
Webhook Flask
   ↓
Procesamiento del mensaje
   ↓
Máquina de estados
   ↓
Validación
   ↓
Servicios
   ↓
Zoho CRM
   ↓
Zoho Creator cuando corresponde
```

---

# Gestión de sesiones

Actualmente las sesiones se mantienen en memoria mediante:

```python
sessions = {}
```

Cada visitante tiene asociada una sesión.

Dentro de la sesión se almacenan datos como:

* Estado actual.
* Información de empresa.
* Información de contacto.
* Información del producto.
* Propietario asignado.
* Número de conversación.
* Control de correos enviados.
* Control de alertas.

La sesión permite que el sistema recuerde en qué parte de la conversación se encuentra el cliente.

Actualmente las sesiones **no utilizan Redis ni una base de datos externa**.

---

# Reinicio de conversación mediante saludo

Se implementó un mecanismo para reiniciar la conversación cuando el cliente envía nuevamente un saludo.

Se reconocen mensajes como:

```text
hola
holaa
holaaa
buenas
buenos dias
buenas tardes
buenas noches
hello
hi
```

Cuando se detecta uno de estos mensajes:

```text
Saludo
  ↓
Limpiar sesión
  ↓
Crear estado menu_principal
  ↓
Seleccionar propietario
  ↓
Mostrar menú
```

Esto evita que una conversación de prueba o una conversación anterior continúe accidentalmente desde un estado anterior.

---

# Menú principal

El menú principal actualmente permite seleccionar entre:

```text
1. Cotizar productos
2. Soporte postventa
```

Si el cliente introduce una opción que no corresponde, el sistema mantiene al visitante en el menú y vuelve a solicitar una opción válida.

---

# Flujo de cotización

El flujo actual de cotización **todavía utiliza mensajes agrupados**.

La información de empresa y contacto se solicita en un solo mensaje.

El cliente recibe:

```text
Nombre de la empresa:
RUT:
Nombre de contacto:
Correo:
Teléfono:
```

El cliente puede completar este formato y enviarlo en un solo mensaje.

Por lo tanto, **la encuesta paso a paso todavía no está implementada**.

---

# Procesamiento de empresa y contacto

El sistema puede identificar información aunque el cliente no mantenga exactamente el formato esperado.

Busca etiquetas como:

```text
Empresa:
RUT:
Contacto:
Correo:
Teléfono:
```

También existen mecanismos para inferir información cuando algunos datos son enviados sin etiquetas.

El sistema intenta identificar:

* Empresa.
* RUT.
* Contacto.
* Correo.
* Teléfono.

---

# Validación de datos de empresa

Antes de continuar con la cotización se comprueba que estén presentes los datos obligatorios:

```text
Nombre de la empresa
RUT
Nombre de contacto
Correo
Teléfono
```

También se comprueba que el correo tenga un formato válido.

Si falta información, el sistema:

1. Mantiene al cliente en el flujo de cotización.
2. Identifica los campos faltantes.
3. Informa cuáles deben ser corregidos.
4. Entrega ejemplos para completar los datos.
5. Envía una alerta interna cuando corresponde.

---

# Flujo del producto

Una vez que los datos de empresa y contacto son válidos, el bot solicita la información del producto.

Actualmente se solicita en **un solo mensaje**:

```text
Número de parte:
Marca:
Descripción:
Cantidad:
Dirección de entrega:
```

El sistema también puede procesar información que venga sin todas las etiquetas.

---

# Procesamiento de productos

El sistema puede identificar:

* Número de parte.
* Marca.
* Descripción.
* Cantidad.
* Dirección de entrega.

También se implementó lógica para intentar diferenciar una dirección de entrega de otros valores numéricos.

Esto es importante porque una dirección puede contener números.

Por ejemplo:

```text
Av. Ejemplo 222
```

El `222` no debe interpretarse automáticamente como la cantidad del producto.

---

# Cantidades escritas con números

El sistema permite recibir cantidades utilizando números.

Ejemplos:

```text
5
10
20
2.5
2,5
```

Los valores se normalizan antes de almacenarlos.

---

# Cantidades escritas con palabras

También se implementó el procesamiento de cantidades escritas con palabras en español.

Por ejemplo:

```text
cinco
diez
quince
veinte
veinticinco
treinta y dos
cien
ciento veinte
doscientos
quinientos veinte
```

El sistema convierte estos valores a números antes de continuar.

Por ejemplo:

```text
Cantidad: cinco
```

se procesa como:

```text
Cantidad: 5
```

---

# Protección contra números de direcciones

Se modificó la extracción de cantidades para evitar buscar simplemente cualquier número dentro del mensaje.

Primero se intenta identificar:

```text
Cantidad: 5
```

o:

```text
Cantidad: cinco
```

También se puede identificar una línea independiente que represente claramente una cantidad.

Esto evita casos como:

```text
cinco
Av. Ejemplo 222
```

donde el sistema podría interpretar incorrectamente `222` como la cantidad.

---

# Validación de cantidad

La cantidad debe ser un valor numérico válido y mayor que cero.

Si se recibe:

```text
Cantidad: cinco
```

se convierte a:

```text
5
```

Si se recibe un valor inválido, el sistema informa que la cantidad debe ser corregida.

---

# Validación de cotización

Antes de registrar la cotización se comprueba que existan los campos obligatorios:

```text
Nombre de la empresa
RUT
Nombre de contacto
Correo
Teléfono
Número de parte
Cantidad
Dirección de entrega
```

Si falta alguno, el sistema no registra automáticamente la cotización.

En su lugar, informa al cliente qué campos deben corregirse.

---

# Alertas de solicitudes incompletas

Se implementó un sistema de correo para avisar cuando una solicitud de cotización no puede completarse debido a información faltante o inválida.

La alerta incluye información como:

```text
Empresa
RUT
Contacto
Correo
Teléfono
Número de parte
Marca
Cantidad
Dirección de entrega
Campos faltantes o inválidos
Último mensaje recibido
```

El sistema además controla que la alerta no se envíe repetidamente durante la misma sesión.

El flujo es:

```text
Cliente envía información
        ↓
Procesar
        ↓
Validar
        ↓
¿Faltan datos?
     ↙       ↘
   Sí         No
   ↓           ↓
Enviar       Continuar
alerta       cotización
```

---

# Resumen de cotización

Cuando la información es válida, el sistema construye un resumen antes de completar el registro.

El resumen contiene:

```text
Nombre de la empresa
RUT
Nombre de contacto
Correo
Teléfono
Número de parte
Marca
Descripción
Cantidad
Dirección de entrega
```

La información sensible se muestra protegida cuando corresponde.

---

# Integración con Zoho CRM

Una vez validada la información, el sistema trabaja con Zoho CRM.

El flujo es:

```text
Información del cliente
        ↓
Buscar Account
        ↓
Crear Account si no existe
        ↓
Buscar / crear Contact
        ↓
Crear Deal
        ↓
Asociar Account
        ↓
Asociar Contact
        ↓
Asignar Owner
```

---

# Búsqueda de Account mediante RUT

Se realizó una modificación importante en la lógica de Accounts.

El **RUT se utiliza como identificador principal para encontrar una empresa existente**.

Esto evita que una misma empresa pueda generar Accounts duplicadas solamente porque el nombre fue escrito de una manera diferente.

Por ejemplo:

```text
Empresa registrada:
Empresa ABC
RUT: 12345678-9
```

Si posteriormente el cliente escribe:

```text
Empresa A.B.C.
RUT: 12345678-9
```

el sistema utiliza el RUT para encontrar la Account existente.

El nombre de la empresa se normaliza únicamente para determinadas comparaciones y no necesariamente modifica el nombre almacenado.

---

# Creación de Account

Si no existe una Account con el RUT recibido, el sistema crea una nueva Account.

La información utilizada incluye:

* Nombre de empresa.
* RUT.
* Teléfono.
* Propietario.

---

# Gestión de Contactos

El sistema busca contactos principalmente mediante el correo electrónico.

Si el contacto existe:

```text
Buscar Contact
      ↓
¿Existe?
   ↙       ↘
 Sí         No
 ↓           ↓
Actualizar  Crear
```

Cuando un contacto existente necesita ser actualizado, también puede actualizarse la relación con la Account correspondiente.

---

# Asociación Contact → Account

El contacto creado o actualizado queda asociado a la Account encontrada o creada mediante el RUT.

Esto permite mantener la relación:

```text
Account
   ↓
Contact
```

---

# Creación del Deal

Después de obtener la Account y el Contact, el sistema crea el Deal correspondiente.

El Deal contiene información como:

* Nombre.
* Importe.
* Fase.
* Probabilidad.
* Fecha de cierre.
* Propietario.
* Account.
* Contact.
* Otros campos configurados en Zoho CRM.

---

# Asociación Deal → Account

El Deal queda asociado a la Account obtenida mediante el RUT.

El flujo es:

```text
RUT
 ↓
Account
 ↓
Deal
```

Esto permite que el negocio quede relacionado con la empresa correcta.

---

# Asignación de propietarios

El sistema cuenta con una estructura para trabajar con propietarios configurados mediante variables de entorno.

El propietario se guarda dentro de la sesión:

```text
owner_asignado
```

y posteriormente se utiliza durante la creación de:

* Account.
* Contact.
* Deal.

---

# Correos al propietario

Cuando una cotización es registrada correctamente, se puede enviar un correo al propietario correspondiente.

El correo contiene información relacionada con la solicitud de cotización.

---

# Correo de primer contacto

Cuando SalesIQ genera el evento inicial correspondiente, el sistema puede enviar un correo de primer contacto.

Se controla mediante la sesión para evitar enviar repetidamente el mismo correo durante la misma conversación.

---

# Número de conversación

Se implementó el almacenamiento del identificador de la conversación o visita.

Dependiendo de la información entregada por SalesIQ, se utiliza:

```text
visitid
```

o:

```text
active_conversation_id
```

La información se almacena en la sesión como:

```text
num_chat
```

Esto permite mantener una referencia de la conversación asociada al proceso.

---

# Respuestas del bot

Se modificó la construcción de respuestas para evitar enviar múltiples mensajes separados cuando internamente existen varias partes de una misma respuesta.

Por ejemplo, en lugar de:

```text
Mensaje 1

Mensaje 2

Mensaje 3
```

como mensajes independientes, el sistema los agrupa en una única respuesta con saltos de línea.

Esto permite entregar respuestas más limpias al usuario.

---

# Sincronización con Zoho Creator

Además de Zoho CRM, el sistema utilizado por el proceso de cotización puede trabajar con Zoho Creator.

La información del negocio puede utilizarse para alimentar los registros correspondientes en Creator.

Entre los datos relacionados se encuentran:

* Nombre del trato.
* Fuente de posible cliente.
* Tipo.
* Importe.
* Fase.
* Probabilidad.
* ID del Deal.
* Fecha de envío.
* Lugar de entrega.
* Notas.
* Contacto.
* Cliente.
* Fecha límite de oferta.
* Fecha de cierre.
* Número de licitación.
* Asignado a.
* Propietario de negocio.
* Productos.

---

# Propietario de negocio en Zoho Creator

Se realizó una modificación para sincronizar el propietario del Deal de Zoho CRM con Zoho Creator.

El propietario del negocio en Zoho CRM se utiliza para completar el campo:

```text
Propietario_de_negocio
```

en Zoho Creator.

El flujo es:

```text
Zoho CRM
   │
   └── Propietario del Deal
              ↓
      Sincronización
              ↓
Zoho Creator
   │
   └── Propietario_de_negocio
```

Esto permite que el responsable del negocio se mantenga correctamente reflejado en Creator.

---

# Creación y actualización en Zoho Creator

La sincronización utiliza el identificador del Deal de Zoho CRM para buscar el registro correspondiente.

El sistema utiliza:

```text
ID_Deals_CRM
```

para determinar si el registro ya existe.

El comportamiento es:

```text
Buscar ID_Deals_CRM
       ↓
¿Existe?
   ↙       ↘
 Sí         No
 ↓           ↓
Actualizar  Crear
```

Esto permite evitar registros duplicados.

---

# Productos en Zoho Creator

La información del producto puede enviarse al subformulario correspondiente.

Se procesan datos como:

```text
Código de producto
Descripción
Marca
Cantidad
```

---

# Procesamiento de fechas

Se implementó el procesamiento de diferentes fechas provenientes de Zoho CRM.

Entre ellas:

* Fecha límite de oferta.
* Fecha de envío al cliente.
* Fecha de cierre.

Las fechas se convierten al formato requerido antes de utilizarlas en otros procesos.

---

# Manejo de errores

Se incorporaron controles para manejar errores durante operaciones externas.

Se registran errores relacionados con:

* Obtención del token.
* Peticiones HTTP.
* Creación de Accounts.
* Creación o actualización de Contacts.
* Creación de Deals.
* Conversión de cantidades.
* Procesamiento de fechas.
* Envío de correos.

Los logs se utilizan para facilitar el diagnóstico durante las pruebas.

---

# Seguridad de logs

Los datos sensibles no se muestran directamente en determinados logs.

Se utilizan funciones para enmascarar:

```text
Correo
Teléfono
RUT
IDs
Visitor ID
Conversation ID
Owner ID
```

Esto permite mantener información útil para depuración sin exponer completamente los datos personales.

---

# Frontend de pruebas

El proyecto incluye:

```text
frontend/index.html
```

Este frontend permite realizar pruebas del Webhook de manera local.

Se accede mediante:

```text
/test
```

Esto permite probar el flujo de conversación sin depender exclusivamente de una conversación real de WhatsApp.

---

# Instalación

## Requisitos

Para ejecutar el proyecto se necesita:

* Python.
* Git.
* Credenciales de Zoho.
* Acceso a Zoho SalesIQ.
* Acceso a Zoho CRM.
* Configuración de Zoho Creator cuando corresponda.

---

# Instalación de dependencias

Ingresar a la carpeta:

```bash
cd Webhook-SalesIQ
```

Instalar las dependencias:

```bash
pip install -r requirements.txt
```

También se recomienda utilizar un entorno virtual.

### Windows

```bash
python -m venv venv
venv\Scripts\activate
```

### Linux / macOS

```bash
python -m venv venv
source venv/bin/activate
```

---

# Configuración

El proyecto utiliza variables de entorno para almacenar configuraciones y credenciales.

Las credenciales no deben escribirse directamente dentro del código ni subirse al repositorio.

El archivo `.env` se utiliza durante el desarrollo local para configurar las variables necesarias.

---

# Ejecución local

El servidor se inicia mediante:

```bash
python ServerHook.py
```

El servidor utiliza el puerto configurado mediante la variable:

```text
PORT
```

Si no existe, utiliza el puerto configurado por defecto en `ServerHook.py`.

---

# Pruebas

El flujo recomendado para realizar cambios es:

```text
Modificar código
      ↓
Ejecutar localmente
      ↓
Probar mediante /test
      ↓
Revisar logs
      ↓
Comprobar Zoho CRM
      ↓
Comprobar Zoho Creator
      ↓
Confirmar funcionamiento
```

Esto permite detectar problemas antes de realizar cambios en producción.

---

# Despliegue

El proyecto puede desplegarse utilizando Railway.

El flujo utilizado es:

```text
Modificar código
      ↓
Probar localmente
      ↓
git add
      ↓
git commit
      ↓
git push
      ↓
Repositorio
      ↓
Railway
      ↓
Nuevo despliegue
```

El `Procfile` utiliza:

```text
web: python ServerHook.py
```

---

# Funcionalidades actualmente implementadas

Actualmente el proyecto cuenta con:

* Webhook Flask para Zoho SalesIQ.
* Máquina de estados.
* Gestión de sesiones en memoria.
* Menú principal.
* Flujo de cotización.
* Flujo de postventa.
* Recopilación de empresa y contacto en un solo mensaje.
* Recopilación de información del producto en un solo mensaje.
* Extracción de datos con etiquetas.
* Inferencia de datos sin etiquetas.
* Validación de campos obligatorios.
* Validación básica de correo.
* Validación plausible de RUT.
* Validación plausible de teléfono.
* Conversión de cantidades escritas con palabras.
* Normalización de cantidades.
* Detección de cantidades evitando confundir números de direcciones.
* Validación de cantidades mayores que cero.
* Alertas por solicitudes incompletas.
* Control para evitar alertas duplicadas.
* Envío de correos al propietario.
* Correo de primer contacto.
* Gestión de propietarios.
* Creación y actualización de Accounts.
* Búsqueda de Account mediante RUT.
* Creación y actualización de Contacts.
* Asociación Contact → Account.
* Creación de Deals.
* Asociación Deal → Account.
* Asociación Deal → Contact.
* Asignación de Owner al Deal.
* Caché temporal de Access Token.
* Protección de información sensible en logs.
* Identificación del número de conversación.
* Reinicio de sesión mediante saludos.
* Respuestas agrupadas en un único mensaje.
* Frontend local de pruebas.
* Integración con Zoho Creator.
* Sincronización del propietario del negocio con Zoho Creator.
* Creación o actualización de registros en Creator.
* Procesamiento de productos para Creator.
* Procesamiento de fechas.

---

# Funcionalidades que todavía NO están implementadas

Para evitar confundir el estado actual del proyecto con ideas que fueron consideradas anteriormente, las siguientes funcionalidades **no forman parte actualmente del sistema**:

* Encuesta paso a paso de empresa y contacto.
* Confirmación interactiva mediante botones.
* Corrección individual mediante menú.
* Recordatorios automáticos al cliente.
* Persistencia de sesiones mediante Redis.
* Persistencia de sesiones mediante PostgreSQL.
* Inteligencia artificial para interpretar automáticamente la información.
* Validación completa del dígito verificador del RUT mediante módulo 11.

Actualmente la recopilación de información continúa funcionando mediante mensajes agrupados.

Por ejemplo:

```text
Nombre de la empresa:
RUT:
Nombre de contacto:
Correo:
Teléfono:
```

Y posteriormente:

```text
Número de parte:
Marca:
Descripción:
Cantidad:
Dirección de entrega:
```

---

# Flujo actual completo

El funcionamiento actual del sistema puede resumirse de la siguiente manera:

```text
                    CLIENTE
                       ↓
                  WhatsApp
                       ↓
                 Zoho SalesIQ
                       ↓
                Webhook Flask
                       ↓
               Identificar sesión
                       ↓
                Máquina de estados
                       ↓
              ┌────────┴────────┐
              ↓                 ↓
         Cotización          Postventa
              ↓
       Empresa + Contacto
       en un solo mensaje
              ↓
          Validación
              ↓
          Producto
       en un solo mensaje
              ↓
          Validación
              ↓
       Crear / buscar
           Account
              ↓
       Crear / actualizar
           Contact
              ↓
          Crear Deal
              ↓
      Asociar Account/Contact
              ↓
        Asignar propietario
              ↓
         Zoho CRM
              ↓
       Zoho Creator cuando
          corresponde
              ↓
       Enviar notificaciones
              ↓
       Responder al cliente
```

---

# Conclusión

El proyecto Webhook-SalesIQ permite gestionar conversaciones de clientes mediante WhatsApp y Zoho SalesIQ, procesar la información recibida y conectarla con Zoho CRM y Zoho Creator.

Durante el desarrollo se implementaron mejoras principalmente en:

* Organización del código.
* Máquina de estados.
* Gestión de sesiones.
* Extracción de información.
* Validación de datos.
* Procesamiento de cantidades.
* Seguridad de logs.
* Gestión de Accounts.
* Gestión de Contacts.
* Gestión de Deals.
* Asignación de propietarios.
* Envío de correos.
* Alertas por solicitudes incompletas.
* Manejo de conversaciones.
* Integración con Zoho Creator.

Una de las mejoras importantes fue permitir que el cliente pueda escribir cantidades utilizando tanto números como palabras, además de mejorar la detección para evitar confundir números presentes en direcciones con cantidades.

También se mejoró la relación entre los registros de Zoho CRM utilizando el RUT como identificador principal de la empresa, asociando correctamente Account, Contact y Deal.

Finalmente, se incorporó la sincronización del propietario del negocio hacia Zoho Creator mediante el campo `Propietario_de_negocio`.

El proyecto continúa utilizando actualmente una encuesta de empresa/contacto en un solo mensaje. La conversión de este proceso a una encuesta paso a paso **todavía queda pendiente** y no forma parte de las funcionalidades actuales.
