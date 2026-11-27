# SELEC Sofía — parche de automatización controlada (27-11-2026)

## Alcance de esta entrega

Implementa el procesamiento automático **de registros de prueba** de las opciones 1 (Deals), 2 (Casos de postventa) y 3 (Casos de consultas) por el cron existente, **sin ingresar un Call ID por cada llamada**.

- Mantiene el piloto previo y los escritores Sandbox independientes.
- Por defecto está **desactivado** y NO cambia variables de Render.
- Solo recibe las listas ya clasificadas por Retell en el cron actual.
- Solo considera llamadas **nuevas** a partir de un corte explícito UTC (milisegundos Unix).
- Valida los tipos, estados, identificadores y fechas antes de intentar escribir.
- Procesa máximo de 1 a 5 candidatos por ejecución; valor predeterminado: 1.
- Reutiliza la comprobación de duplicados de Zoho CRM existente.
- No reintenta un POST con respuesta incierta; detiene el resto del lote.
- Solo notifica Casos cuya creación acaba de confirmar Zoho.
- Para pruebas envía exclusivamente al buzón `SOFIA_PROD_CASES_MAIL_TEST_TO` y bloquea destinatarios reales.
- Muestra referencia corta de Caso en correo, pero conserva el ID real en el enlace.
- Elimina de las descripciones futuras la frase que afirmaba que no se había enviado una notificación.

**NO es todavía la migración comercial final**: el código actual sigue marcando los registros `[PRUEBA SOFIA]`, el escritor de Deals no crea ni vincula automáticamente Accounts y Contacts reales, y el envío real a los equipos no está habilitado. Falta validar en CRM el primer Deal automático, las demás opciones y la configuración del agente de Retell (encuesta/guion).

## Instalación

1. Hacer copia/commit del repositorio local.
2. Extraer el ZIP **sobre la raíz de `Webhook-SalesIQ`**, conservando la estructura `routes/`, `services/` y `tests/` y sustituyendo los archivos indicados.
3. Ejecutar los tests: `python -m pytest -q` (en la revisión local: 102 tests y 6 subtests aprobados).
4. Desplegar en Render **con todas las nuevas opciones apagadas**; observar que `sofia-selec` vuelve a Live.
5. Antes de habilitar, verificar que solo exista una instancia/cadencia de cron que pueda procesar las mismas llamadas. La búsqueda previa a la escritura no garantiza atomicidad ante dos cron concurrentes; para la operación comercial definitiva se recomienda índice único de Call ID en Zoho CRM.

## Variables de prueba automática controlada

Mantener:

- `SOFIA_PROD_CRON_PILOT_ENABLED=false`
- `SOFIA_PROD_CASES_MAIL_MANUAL_TEST_ENABLED=false`
- `SOFIA_PROD_CASES_MAIL_REAL_RECIPIENTS_ENABLED=false`
- `SOFIA_PROD_CASES_MAIL_TEST_TO=ederth@selec.cl`

Activar únicamente cuando se vaya a ejecutar una **nueva llamada ficticia**:

- `SOFIA_PROD_CRON_AUTO_ENABLED=true`
- `SOFIA_PROD_AUTO_TEST_ONLY=true`
- `SOFIA_PROD_AUTO_START_MS=<milisegundos UTC obtenidos AHORA, antes de realizar la llamada>`
- `SOFIA_PROD_AUTO_MAX_PER_RUN=1`
- `SOFIA_PROD_CASES_WRITES_ENABLED=true` (para opción 2/3)
- `SOFIA_PROD_CASES_MAILS_ENABLED=true` (para correo de opción 2/3)
- `SOFIA_PROD_DEALS_WRITES_ENABLED=false` (hasta probar primero Casos)

Para generar la fecha de inicio en **PowerShell** justo antes de habilitar:

`[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()`

No reutilizar la fecha de una llamada antigua ni copiar la fecha de ejemplo. El corte persiste; no debe moverse retroactivamente después de iniciar operaciones. En la primera prueba se recomienda activar el cron automático con Casos solamente, hacer **una llamada nueva** a opción 3 y comprobar el log `[SOFIA PROD AUTO TEST]` más el correo. Para probar opción 1, realizar otro despliegue controlado con un corte **nuevo**, `CASES_WRITES=false`, `CASES_MAILS=false`, `DEALS_WRITES=true` y una Cuenta de prueba en `SOFIA_PROD_TEST_ACCOUNT_ID` si el layout la requiere. El flujo de Negocios solo crea Deals de prueba.

Apagar en caso de incidente: `SOFIA_PROD_CRON_AUTO_ENABLED=false`, `SOFIA_PROD_CASES_WRITES_ENABLED=false`, `SOFIA_PROD_DEALS_WRITES_ENABLED=false`, `SOFIA_PROD_CASES_MAILS_ENABLED=false`.

## Pendientes antes de producción real

1. Modelo de Deals reales: cuenta por RUT, contacto por correo y propietario según reglas de SELEC; verificar campos y layout en CRM producción.
2. Modo real separado del modo `AUTO_TEST_ONLY`, con consentimiento para correos al equipo; nunca convertir registros de prueba silenciosamente.
3. Evitar concurrencia entre cron/instancias e introducir garantía robusta de idempotencia (campo único de Call ID en Zoho, si es compatible).
4. Validar Casos incompletos: si Retell no entrega resumen ni descripción, el clasificador todavía envía esa llamada a revisión y NO la crea.
5. Revisar guion de Sofía en Retell: postventa 12–24 horas; `operaciones@selec.cl`; respuesta formal de opción 3; mini encuesta 1–10 y motivo si calificación < 7.
6. Verificar destinatarios finales Deivys/Carolina/Luis y Patricio/Carolina/Luis con prueba autorizada; el parche solo notifica al buzón de pruebas.

## Seguridad

El ZIP del usuario incluía `.env` e historial Git. Este parche **NO incluye** `.env`, secretos, tokens, `.git` ni paquetes ZIP históricos.
