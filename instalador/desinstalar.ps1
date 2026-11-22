<#
  Quita las tareas programadas de BuscaPieza RD (y opcionalmente el servicio del túnel).
  NO borra la carpeta, el .env, los respaldos ni la base de datos.

      powershell -ExecutionPolicy Bypass -File instalador\desinstalar.ps1 [-Destino C:\BuscaPieza]
#>
param([string]$Destino = 'C:\BuscaPieza')

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'comun.ps1')
if (-not (Test-Administrador)) { Stop-Instalacion 'Ejecuta como administrador.' }

Stop-BuscaPieza $Destino.TrimEnd('\')
foreach ($t in $TareaServidor, $TareaRespaldo) {
    if (Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $t -Confirm:$false
        Write-Ok "Tarea '$t' eliminada"
    }
}

$cf = Find-Cloudflared
if ($cf -and (Get-Service -Name 'cloudflared' -ErrorAction SilentlyContinue)) {
    $r = Read-Host '¿Desinstalar también el servicio del túnel cloudflared? (afecta a TODOS los sitios de ese túnel) [s/N]'
    if ($r -match '^[sS]') { & $cf service uninstall | Out-Host }
}

Write-Host ''
Write-Info "Se conservaron: $Destino (código, .env, logs, backups) y la base de datos."
Write-Info 'Para borrarlo todo: elimina la carpeta y, en PostgreSQL, DROP DATABASE buscapieza; DROP ROLE buscapieza;'
Write-Host ''
