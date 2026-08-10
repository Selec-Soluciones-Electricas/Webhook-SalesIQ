# Bot de WhatsApp - Webhook SalesIQ

## Descripción

Este proyecto corresponde a un bot que permite atender conversaciones con clientes mediante Zoho SalesIQ.

El proyecto funciona como un backend desarrollado en Python y Flask. Recibe los mensajes enviados por el cliente, identifica en qué parte de la conversación se encuentra y responde dependiendo de la opción seleccionada.

También permite enviar y guardar información en Zoho CRM, principalmente para solicitudes de cotización y postventa.

---

## Tecnologías utilizadas

- Python
- Flask
- Requests
- python-dotenv
- Zoho SalesIQ
- Zoho CRM

### ¿Para qué sirve cada una?

- **Python:** es el lenguaje principal utilizado para desarrollar el bot.
- **Flask:** permite crear el servidor y recibir los mensajes mediante un Webhook.
- **Requests:** permite realizar conexiones y peticiones a APIs externas.
- **python-dotenv:** permite manejar variables de configuración y credenciales.
- **Zoho SalesIQ:** permite recibir y gestionar las conversaciones con los clientes.
- **Zoho CRM:** permite guardar y gestionar la información de empresas, contactos y oportunidades.

---

# Estructura del proyecto

La estructura principal del proyecto es:

```text
Webhook-SalesIQ/
│
├── ServerHook.py
├── requirements.txt
├── Procfile
└── .gitignore
````

### ServerHook.py

Es el archivo principal del proyecto.

En este archivo se encuentra gran parte de la lógica del bot, como:

* Configuración del servidor.
* Recepción de mensajes.
* Gestión de sesiones.
* Procesamiento de conversaciones.
* Menú principal.
* Solicitudes de cotización.
* Servicio de postventa.
* Validación de datos.
* Conexión con Zoho CRM.
* Envío de respuestas al cliente.

### requirements.txt

Contiene las librerías que necesita el proyecto para funcionar.

Entre ellas se encuentran:

```text
Flask
requests
python-dotenv
```

### Procfile

Indica el comando que se debe utilizar para iniciar el proyecto cuando se despliega en una plataforma como Railway.

```text
web: python ServerHook.py
```

### .gitignore

Indica qué archivos no deben subirse al repositorio de Git, por ejemplo archivos temporales o información que no debería compartirse.

---

# Patrón de diseño / arquitectura

El proyecto utiliza principalmente una arquitectura basada en **Webhook y máquina de estados**.

No corresponde exactamente al patrón MVC tradicional, ya que el proyecto no tiene separados los componentes Model, View y Controller.

## Webhook

El Webhook permite que Zoho SalesIQ envíe información al servidor cuando ocurre una interacción con el cliente.

El flujo general es:

```text
Cliente
   ↓
WhatsApp / Zoho SalesIQ
   ↓
Webhook Flask
   ↓
Procesamiento del mensaje
   ↓
Estado de la conversación
   ↓
Respuesta
   ↓
Zoho CRM cuando corresponde
```

## Máquina de estados

El bot utiliza estados para saber en qué parte de la conversación se encuentra el cliente.

Por ejemplo:

```text
menu_principal
      ↓
cotizacion_empresa_bloque
      ↓
cotizacion_producto_bloque
      ↓
menu_principal
```

El estado permite que el bot sepa qué debe hacer cuando recibe el siguiente mensaje.

---

# Funcionamiento del bot

Cuando un cliente inicia una conversación, el bot muestra un menú con diferentes opciones.

Entre ellas:

* Solicitud de cotización.
* Servicio de postventa.

Dependiendo de la opción seleccionada, el cliente entra en un flujo diferente.

El funcionamiento general es:

```text
Cliente
   ↓
Menú principal
   ↓
Seleccionar opción
   ↓
Flujo correspondiente
   ↓
Solicitar información
   ↓
Validar información
   ↓
Guardar/procesar información
   ↓
Responder al cliente
```

---

# Flujo de cotización

El flujo de cotización funciona aproximadamente de la siguiente manera:

```text
Solicitud de cotización
          ↓
Datos de empresa y contacto
          ↓
Validación
          ↓
Datos del producto
          ↓
Validación
          ↓
Zoho CRM
          ↓
Empresa + Contacto + Deal
```

---

# Datos solicitados al cliente

Actualmente el bot solicita los datos de la empresa y del contacto mediante un solo mensaje:

```text
Nombre de la empresa:
RUT:
Nombre de contacto:
Correo:
Teléfono:
```

El sistema intenta separar y reconocer cada uno de estos datos para posteriormente validarlos.

---

# Validación de información

El bot comprueba que los datos necesarios hayan sido ingresados antes de continuar.

Se realizan validaciones principalmente sobre:

* Campos obligatorios.
* Correo electrónico.
* RUT.
* Teléfono.
* Información faltante.

Si falta algún dato, el bot solicita al cliente que lo complete.

---

# Gestión de sesiones

El bot necesita recordar en qué parte de la conversación se encuentra cada cliente.

Para esto utiliza una estructura de sesiones:

```python
sessions = {}
```

Dentro de la sesión se puede guardar información relacionada con el visitante y el estado actual de la conversación.

Por ejemplo:

```text
Cliente
   ↓
Estado actual
   ↓
Información entregada
   ↓
Siguiente acción
```

Una mejora futura sería utilizar Redis o una base de datos para guardar estas sesiones de forma permanente.

---

# Seguridad

El proyecto cuenta con funciones que permiten ocultar parte de información sensible en los registros del sistema.

Se puede ocultar información como:

* Correos.
* Teléfonos.
* RUT.
* Otros datos sensibles.

Esto ayuda a evitar que información personal quede expuesta directamente en los logs.

---

# Instalación

## Requisitos

Para ejecutar el proyecto se necesita tener instalado:

* Python
* Git

También es necesario contar con las credenciales y configuraciones correspondientes de Zoho.

---

## Instalación de dependencias

Primero se debe ingresar a la carpeta del proyecto:

```bash
cd Webhook-SalesIQ
```

Después se pueden instalar las dependencias con:

```bash
pip install -r requirements.txt
```

También se recomienda utilizar un entorno virtual:

```bash
python -m venv venv
```

En Windows:

```bash
venv\Scripts\activate
```

En Linux o macOS:

```bash
source venv/bin/activate
```

---

# Configuración

El proyecto utiliza variables de entorno para manejar configuraciones y credenciales.

Estas variables deben estar configuradas antes de ejecutar el proyecto.

Las credenciales no deberían escribirse directamente dentro del código ni subirse al repositorio.

---

# Cómo ejecutar el proyecto

Para iniciar el servidor localmente se puede ejecutar:

```bash
python ServerHook.py
```

Una vez iniciado, el servidor queda disponible para recibir las peticiones del Webhook.

Durante el desarrollo se recomienda realizar las pruebas primero de forma local antes de subir los cambios al servidor de producción.

---

# Despliegue

El proyecto puede utilizar Railway para ejecutar el servidor.

El flujo de trabajo utilizado para realizar cambios es:

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

De esta manera primero se comprueba que el cambio funcione antes de enviarlo a producción.

---

# Problema encontrado

Uno de los principales problemas encontrados en el proyecto está relacionado con la encuesta que se utiliza para obtener los datos de la empresa y del contacto.

Actualmente se solicita al cliente completar todos los datos en un solo mensaje:

```text
Nombre de la empresa:
RUT:
Nombre de contacto:
Correo:
Teléfono:
```

Este sistema puede provocar problemas porque el cliente puede:

* No responder.
* No completar todos los campos.
* Escribir los datos en otro formato.
* Ingresar información incorrecta.
* No entender cómo completar el formulario.
* Abandonar la conversación.

Por esto se considera necesario mejorar la forma en que se solicitan estos datos.

---

# Mejoras propuestas

## 1. Encuesta paso a paso

Esta sería la mejora principal.

En lugar de pedir los cinco datos en un solo mensaje, el bot podría solicitar cada dato individualmente.

Ejemplo:

```text
Bot:
1/5 ¿Cuál es el nombre de la empresa?

Cliente:
Empresa ABC

Bot:
2/5 ¿Cuál es el RUT de la empresa?

Cliente:
76.123.456-7

Bot:
3/5 ¿Cuál es el nombre del contacto?
```

El bot validaría cada respuesta antes de continuar.

### Beneficios

* Es más fácil para el cliente.
* Reduce errores.
* Permite saber exactamente qué dato falta.
* Evita que el cliente tenga que copiar un formato.
* Permite validar cada dato inmediatamente.

---

# 2. No permitir avanzar con datos incompletos

El bot debería evitar que el flujo avance si falta información obligatoria.

El funcionamiento sería:

```text
Dato recibido
     ↓
Validar
     ↓
¿Es válido?
   ↙     ↘
 No       Sí
 ↓         ↓
Corregir  Siguiente dato
```

De esta manera se asegura que todos los datos necesarios estén completos antes de continuar con la cotización.

---

# 3. Confirmación de los datos

Después de obtener todos los datos, el bot podría mostrar un resumen:

```text
Empresa: Empresa ABC
RUT: 76.123.456-7
Contacto: Juan Pérez
Correo: juan@empresa.cl
Teléfono: +56912345678

¿Los datos están correctos?

[ Sí, continuar ]
[ Corregir ]
```

Esto permite que el cliente revise la información antes de enviarla a CRM.

---

# 4. Corrección individual

Si el cliente selecciona "Corregir", el bot podría preguntar qué dato desea modificar:

```text
¿Qué dato desea corregir?

[ Empresa ]
[ RUT ]
[ Contacto ]
[ Correo ]
[ Teléfono ]
```

Así el cliente no tiene que volver a escribir toda la información.

---

# 5. Mejorar la validación del RUT

Actualmente la validación del RUT es básica.

Una mejora sería implementar el algoritmo de módulo 11 para comprobar realmente si el RUT ingresado es válido.

El proceso sería:

```text
RUT ingresado
     ↓
Limpiar formato
     ↓
Calcular dígito verificador
     ↓
Comparar
     ↓
RUT válido / RUT inválido
```

---

# 6. Mejorar la validación del teléfono

Se podría permitir que el cliente escriba el teléfono en diferentes formatos.

Por ejemplo:

```text
+56 9 1234 5678
56912345678
9 1234 5678
```

El sistema podría convertirlos a un formato estándar antes de guardarlos.

---

# 7. Recordatorios automáticos

Si el cliente comienza la encuesta pero deja de responder, se podría enviar un recordatorio.

Ejemplo:

```text
Encuesta enviada
      ↓
Sin respuesta
      ↓
Primer recordatorio
      ↓
Sin respuesta
      ↓
Segundo recordatorio
      ↓
Derivar a un ejecutivo
```

Esto permitiría intentar recuperar conversaciones que fueron abandonadas.

---

# 8. Utilizar botones

Para respuestas simples se podrían utilizar botones.

Por ejemplo:

```text
¿Los datos están correctos?

[ Sí, continuar ]
[ Corregir ]
```

Esto evita tener que interpretar respuestas como:

```text
sí
si
ok
correcto
dale
```

---

# 9. Utilizar inteligencia artificial

Como una mejora más avanzada, se podría utilizar inteligencia artificial para interpretar respuestas escritas de forma natural.

Por ejemplo, el cliente podría escribir:

```text
Hola, soy Juan Pérez de Empresa ABC,
el RUT es 76.123.456-7,
mi correo es juan@empresa.cl
y mi teléfono es +56912345678.
```

La IA podría identificar:

```text
Empresa: Empresa ABC
RUT: 76.123.456-7
Contacto: Juan Pérez
Correo: juan@empresa.cl
Teléfono: +56912345678
```

Después de obtener estos datos, el sistema debería validarlos antes de aceptarlos.

La IA serviría principalmente para interpretar y separar la información.

---

# 10. Guardar las sesiones de forma permanente

Actualmente las sesiones se guardan en memoria:

```python
sessions = {}
```

Si el servidor se reinicia, las sesiones pueden perderse.

Como mejora se podría utilizar:

* Redis.
* PostgreSQL.
* Otra base de datos.

Esto permitiría mantener el estado de las conversaciones aunque el servidor se reinicie.

---

# 11. Separar el código

Actualmente gran parte de la lógica está dentro de:

```text
ServerHook.py
```

A futuro se podría separar en diferentes carpetas y archivos.

Por ejemplo:

```text
Webhook-SalesIQ/
│
├── app.py
│
├── routes/
│   └── webhook.py
│
├── services/
│   ├── salesiq_service.py
│   ├── zoho_service.py
│   └── email_service.py
│
├── conversation/
│   ├── state_machine.py
│   ├── quotation.py
│   └── postventa.py
│
├── validators/
│   ├── rut.py
│   ├── email.py
│   └── phone.py
│
└── utils/
```

Esto permitiría tener el proyecto más ordenado y facilitaría encontrar y modificar cada parte.

---

# Prioridad de las mejoras

Las mejoras principales se pueden ordenar de la siguiente manera:

| Prioridad | Mejora                                    |
| --------- | ----------------------------------------- |
| Alta      | Encuesta paso a paso                      |
| Alta      | Validación de cada respuesta              |
| Alta      | Confirmación final                        |
| Alta      | Corrección individual                     |
| Media     | Validación real del RUT                   |
| Media     | Validación del teléfono                   |
| Media     | Recordatorios                             |
| Media     | Botones                                   |
| Futura    | Guardar sesiones en Redis o base de datos |
| Futura    | Inteligencia artificial                   |
| Futura    | Separar `ServerHook.py`                   |
| Opcional  | Barra de progreso                         |

---

# Mejora principal

La mejora en la que se debería centrar el desarrollo es la **encuesta conversacional paso a paso**.

El objetivo es que el cliente entregue correctamente los cinco datos necesarios antes de continuar con la cotización.

El flujo sería:

```text
Solicitud de cotización
          ↓
Nombre de empresa
          ↓
Validar
          ↓
RUT
          ↓
Validar
          ↓
Nombre de contacto
          ↓
Validar
          ↓
Correo
          ↓
Validar
          ↓
Teléfono
          ↓
Validar
          ↓
Mostrar resumen
          ↓
¿Datos correctos?
      ↙          ↘
    Sí            No
    ↓             ↓
Continuar      Corregir
    ↓
Continuar cotización
```

La idea es que el sistema **no permita avanzar mientras falten datos obligatorios o estos sean inválidos**.

No se puede obligar al cliente a responder, pero sí se puede hacer que el sistema guíe al usuario, le indique qué información falta y no permita avanzar hasta completar correctamente los datos.

---

# Conclusión

El proyecto permite gestionar conversaciones con clientes mediante Zoho SalesIQ y conectar la información obtenida con Zoho CRM.

El sistema utiliza Flask para recibir los Webhooks y una máquina de estados para controlar las diferentes etapas de la conversación.

El principal problema encontrado está en la forma actual de solicitar los datos de empresa y contacto, ya que el cliente debe completar varios campos en un solo mensaje.

La principal mejora propuesta es convertir esta encuesta en un proceso paso a paso, donde cada dato sea solicitado y validado individualmente.

También se propone agregar una confirmación final, corrección individual de datos, mejores validaciones, recordatorios, botones, persistencia de sesiones e inteligencia artificial como mejoras futuras.

El objetivo final es reducir los errores y conseguir que la información necesaria para realizar una cotización sea entregada de forma completa y correcta.

```

**Este formato está mucho más acorde a lo que te pidieron:** explica el proyecto, el patrón/arquitectura, estructura, funcionamiento, ejecución y las mejoras, pero sin intentar sonar como documentación de una empresa gigante.
```
