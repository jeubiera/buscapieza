<#
  Actualiza una instalación existente con el código de este paquete.
  Conserva .env, la base de datos, logs, respaldos y fotos subidas.

      powershell -ExecutionPolicy Bypass -File instalador\actualizar.ps1 [-Destino C:\BuscaPieza]

  Pasos: respaldo de la BD → detener → copiar código → dependencias → migraciones → arrancar → comprobar
#>
param([string]$Destino = 'C:\BuscaPieza')

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'comun.ps1')

$Origen = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path.TrimEnd('\')
$Destino = $Destino.TrimEnd('\')
$vpy = Join-Path $Destino 'venv\Scripts\python.exe'

Write-Host ''
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host '   BUSCAPIEZA RD - Actualización' -ForegroundColor Cyan
Write-Host '============================================================' -ForegroundColor Cyan

if (-not (Test-Administrador)) { Stop-Instalacion 'Ejecuta como administrador (usa ACTUALIZAR.bat).' }
if (-not (Test-Path (Join-Path $Destino '.env')) -or -not (Test-Path $vpy)) {
    Stop-Instalacion "No hay una instalación en $Destino. Usa INSTALAR-SERVIDOR.bat."
}
if ($Origen -eq $Destino) { Stop-Instalacion 'Descomprime el paquete nuevo en otra carpeta y ejecuta ACTUALIZAR.bat desde allí.' }
Get-ChildItem -Path $Origen -Recurse -File -ErrorAction SilentlyContinue | Unblock-File -ErrorAction SilentlyContinue

$pgBin = Find-PostgresBin
if ($pgBin) { $env:Path = "$pgBin;$env:Path" }

Write-Paso '1/5' 'Respaldo de la base de datos antes de actualizar'
& $vpy (Join-Path $Destino 'scripts\respaldar_db.py') | Out-Host
if ($LASTEXITCODE -ne 0) {
    $r = Read-Host '    El respaldo falló. ¿Continuar igualmente? [s/N]'
    if ($r -notmatch '^[sS]') { Stop-Instalacion 'Actualización cancelada.' }
}

Write-Paso '2/5' 'Deteniendo la aplicación'
Stop-BuscaPieza $Destino
Write-Ok 'Detenida'

Write-Paso '3/5' 'Copiando el código nuevo'
Copy-Codigo $Origen $Destino
Write-Ok 'Código actualizado (.env, datos, logs y respaldos intactos)'

Write-Paso '4/5' 'Dependencias y migraciones'
Install-Dependencias $Destino
Update-BaseDatos $Destino | Out-Null
Write-Ok 'Listo'

Write-Paso '5/5' 'Arrancando'
Start-ScheduledTask -TaskName $TareaServidor
$puerto = Get-ValorEnv (Join-Path $Destino '.env') 'FLASK_PORT'
if (-not $puerto) { $puerto = '5050' }
if (Wait-Salud "http://127.0.0.1:$puerto/salud" 90) {
    Write-Ok 'La aplicación responde'
} else {
    Stop-Instalacion "No responde. Revisa $Destino\logs\servidor-consola.log. El respaldo previo está en $Destino\backups"
}
$appUrl = Get-ValorEnv (Join-Path $Destino '.env') 'APP_URL'
if ($appUrl -and (Wait-Salud "$appUrl/salud" 30)) { Write-Ok "Accesible en $appUrl" }

Write-Host ''
Write-Host '   ACTUALIZACIÓN COMPLETADA' -ForegroundColor Green
Write-Host ''
