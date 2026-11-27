# Sofía SELEC — Integración comercial controlada (27-11-2026)

## Incluye
- `services/sofia/metadatos_comerciales.py`: preflight **GET** de los campos de Zoho. Comprueba campos API, posibilidad de creación, obligatorios del sistema y unicidad de `Accounts.Billing_Code`, `Contacts.Email` y `Deals.Retell_Call_ID`.
- `services/sofia/cron_comercial_produccion.py`: conecta llamadas elegibles con el escritor comercial existente, respetando fecha de inicio, tope y la detección de duplicados. Desactivado por defecto.
- `services/sofia/registro_negocios_comerciales.py`: incorpora bloqueos extra cuando están habilitados los modos de pruebas de Casos, correos y Sandbox.
- `routes/cron_sofia.py`: llama al modo comercial y añade un endpoint de diagnóstico protegido: `POST /cron/sofia/comercial/diagnostico-campos`.
- `tests/test_sofia_cron_comercial_20261127.py`: pruebas offline sin llamadas a servicios externos.

## Instalación local
1. Haz una copia de seguridad de `Webhook-SalesIQ`.
2. Descomprime este ZIP y copia las carpetas dentro de `Webhook-SalesIQ`; **combina carpetas** y sustituye solo los archivos indicados.
3. Confirma que sigues en `sofia-render-cron` (`git branch --show-current`).
4. Ejecuta `python -m pytest -q`. En la versión del ZIP revisado pasaron **147 pruebas y 6 subpruebas**.
5. No hagas `git add .`: selecciona explícitamente los archivos de este parche en el commit.

## ATENCIÓN: no activar aún
- El modo comercial está **inactivo** si falta `SOFIA_PROD_COMMERCIAL_CRON_ENABLED=true`, aun cuando el código esté desplegado.
- Requiere además `SOFIA_PROD_COMMERCIAL_ENABLED=true`, `SOFIA_PROD_COMMERCIAL_CLIENTS_WRITES_ENABLED=true`, `SOFIA_PROD_COMMERCIAL_DEALS_WRITES_ENABLED=true` y `SOFIA_PROD_COMMERCIAL_START_MS` en milisegundos UTC.
- Se bloquea cuando hay modos automáticos de prueba, pilotos o escrituras Sandbox activas.
- El modo comercial **solo implementa Negocios**. Las opciones 2/3 siguen teniendo escritor y correo de PRUEBA; falta desarrollar los casos/correos reales.
- Las verificaciones de campos pueden fallar si Zoho no tiene permisos `settings.fields.READ` o si los campos clave no están configurados como únicos. En ese caso, no se crean registros.
- Este preflight comprueba metadatos comunes, pero no certifica reglas de diseño (layouts) específicas ni otras reglas comerciales; hay que revisar esas reglas antes de la activación final.
- No valida mecanismos de exclusión entre instancias distintos de la unicidad en Zoho. La unicidad efectiva en CRM es obligatoria; las búsquedas por sí solas no evitan una carrera concurrente.
- No se ha hecho ninguna prueba de escritura real con estas modificaciones.

## Diagnóstico sin Render Shell
Una vez desplegado este parche en `sofia-selec`, el endpoint protegido permite consultar los tres módulos con las credenciales ya configuradas en Render y devuelve **solo estados de campos**, sin revelar clientes ni tokens.

Desde PowerShell, copia y ejecuta el siguiente bloque (te pedirá el secreto del cron sin mostrarlo):

```powershell
$secure = Read-Host 'CRON_SECRET' -AsSecureString
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $secret = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    try {
        Invoke-RestMethod -Method Post `
          -Uri 'https://sofia-selec.onrender.com/cron/sofia/comercial/diagnostico-campos' `
          -Headers @{'X-Cron-Secret'=$secret} `
          -TimeoutSec 90 | ConvertTo-Json -Depth 7
    } catch {
        if ($_.ErrorDetails.Message) { $_.ErrorDetails.Message }
        else { 'HTTP_ERROR_DIAGNOSTICO' }
    }
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    Remove-Variable secret -ErrorAction SilentlyContinue
}
```

Un `estado: bloqueado` indica los campos que faltan, sin unicidad o sin permisos de metadatos; **no habilites escrituras**.

## Próximas tareas antes del modo real
1. Ejecutar el diagnóstico protegido y verificar los campos de la organización.
2. Revisar reglas de diseños y campos obligatorios, confirmar opciones de etapa/campaña y permisos de escritura.
3. Definir/activar unicidad en CRM, especialmente `Retell_Call_ID` y `Billing_Code` (RUT normalizado) para evitar duplicados entre procesos.
4. Probar Cuenta → Contacto → Negocio con registros controlados y permisos autorizados.
5. Desarrollar el escritor real y correo real para Casos (postventa/consultas), llamadas interrumpidas y encuesta.
