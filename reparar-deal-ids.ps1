# =========================================================
# Reparacion de Deal ID en Registro_CRM_WhatsApp
# ---------------------------------------------------------
# Llama al endpoint /cron/reparar-deal-ids por lotes hasta
# revisar todas las filas OK sin Deal ID.
#
# Uso:
#   .\reparar-deal-ids.ps1                  # prueba en seco (no modifica nada)
#   .\reparar-deal-ids.ps1 -Aplicar         # repara de verdad
#   .\reparar-deal-ids.ps1 -Aplicar -Limite 5   # lotes mas chicos
#
# El secreto se pide por consola (o se lee de la variable de
# entorno CRON_SECRET), para no dejarlo escrito en el archivo.
# =========================================================

param(
    [switch]$Aplicar,
    [int]$Offset = 0,     # 0 = revisar todas las filas pendientes
    [int]$Limite = 8
)

$base = "https://webhook-salesiq-production.up.railway.app/cron/reparar-deal-ids"

# Windows PowerShell 5.1 puede usar TLS antiguo por defecto; se
# fuerza TLS 1.2 para conectar con Railway.
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$secret = $env:CRON_SECRET
if (-not $secret) {
    $secret = Read-Host "CRON_SECRET"
}

$modo = if ($Aplicar) { "REAL" } else { "PRUEBA EN SECO (dry_run)" }
Write-Host "Modo: $modo | offset inicial: $Offset | lote: $Limite`n" -ForegroundColor Cyan

$totalReparadas = 0
$propuestas     = @()
$noEncontradas  = @()
$revisionManual = @()
$iteracion      = 0
$maxIteraciones = 50   # tope de seguridad para no quedar en bucle

do {
    $iteracion++

    $url = "${base}?limite=$Limite&offset=$Offset"
    if (-not $Aplicar) { $url += "&dry_run=1" }

    try {
        $r = Invoke-RestMethod -Uri $url -Headers @{ "X-Cron-Secret" = $secret } -TimeoutSec 60
    }
    catch {
        Write-Host "Error llamando al endpoint: $($_.Exception.Message)" -ForegroundColor Red
        if ($_.Exception.Response) {
            Write-Host "Codigo HTTP: $([int]$_.Exception.Response.StatusCode)" -ForegroundColor Red
        }
        else {
            Write-Host "Sin respuesta del servidor: revisar conexion a internet/VPN/proxy o si el servicio en Railway esta activo." -ForegroundColor Red
        }
        break
    }

    if ($r.error) {
        Write-Host "El endpoint respondio con error: $($r.error)" -ForegroundColor Red
        break
    }

    $totalReparadas += $r.reparadas
    $propuestas     += $r.propuestas
    $noEncontradas  += $r.no_encontradas
    $revisionManual += $r.requieren_revision_manual

    Write-Host ("Lote {0,2} | offset={1,3} | procesadas={2} | propuestas={3} | reparadas={4} | no_encontradas={5} | quedan={6}" -f `
        $iteracion, $Offset, $r.procesadas_en_lote, $r.propuestas.Count, $r.reparadas, $r.no_encontradas.Count, $r.quedan_por_revisar)

    if ($r.fallos_actualizacion.Count -gt 0) {
        Write-Host "`nFallos de actualizacion (se detiene el proceso):" -ForegroundColor Red
        $r.fallos_actualizacion | Format-Table visit_id, conversation_id, deal_id, detalle_error -AutoSize -Wrap
        break
    }

    $Offset = $r.siguiente_offset

} while ($r.quedan_por_revisar -gt 0 -and $r.procesadas_en_lote -gt 0 -and $iteracion -lt $maxIteraciones)

# =========================================================
# RESUMEN
# =========================================================

Write-Host "`n================ RESUMEN ================" -ForegroundColor Cyan

if ($Aplicar) {
    Write-Host "Filas reparadas: $totalReparadas" -ForegroundColor Green
}
else {
    Write-Host "Propuestas encontradas (no aplicadas): $($propuestas.Count)" -ForegroundColor Yellow
    if ($propuestas.Count -gt 0) {
        $propuestas | Format-Table visit_id, conversation_id, deal_id, criterio, candidatos -AutoSize
    }
    Write-Host "Si se ven bien, ejecuta:  .\reparar-deal-ids.ps1 -Aplicar" -ForegroundColor Yellow
}

# Aviso si un mismo Deal ID quedo propuesto para mas de una fila
# (en dry_run cada lote se evalua por separado).
$duplicados = $propuestas | Group-Object deal_id | Where-Object { $_.Count -gt 1 }
if ($duplicados) {
    Write-Host "`nATENCION: Deal ID propuesto para mas de una fila (revisar a mano):" -ForegroundColor Red
    foreach ($d in $duplicados) {
        Write-Host ("  {0} -> {1}" -f $d.Name, (($d.Group | ForEach-Object { $_.visit_id }) -join ", ")) -ForegroundColor Red
    }
}
# Aviso si hay filas que no se pudieron encontrar en Zoho CRM (por ejemplo, porque el contacto/empresa fue eliminado).
if ($noEncontradas.Count -gt 0) {
    Write-Host "`nNo encontradas: $($noEncontradas.Count)" -ForegroundColor Yellow
    $noEncontradas | Format-Table visit_id, conversation_id, motivo, deals_en_ventana, deals_cualquier_fuente, deals_busqueda_global, telefonos, emails, empresas, candidatos -AutoSize
}
#Aviso si hay filas que requieren revision manual (por ejemplo, porque hay mas de un candidato con el mismo Deal ID).
if ($revisionManual.Count -gt 0) {
    Write-Host "`nRequieren revision manual: $($revisionManual.Count)" -ForegroundColor Yellow
    $revisionManual | Format-Table visit_id, conversation_id, motivo -AutoSize -Wrap
}