<#
  Instalador de BuscaPieza RD para un servidor Windows con Cloudflare Tunnel.

  Uso (como administrador; INSTALAR-SERVIDOR.bat lo hace por ti):
      powershell -ExecutionPolicy Bypass -File instalador\instalar-servidor.ps1 [-Destino C:\BuscaPieza]

  Qué hace:
    1. Comprueba Python 3.11+, PostgreSQL y cloudflared (ofrece instalarlos con winget)
    2. Copia la aplicación a la carpeta destino
    3. Crea el entorno virtual e instala dependencias
    4. Genera el .env de producción (asistente)
    5. Crea usuario y base en PostgreSQL, aplica migraciones y datos iniciales
    6. Registra la tarea "BuscaPieza-Servidor" (arranca con Windows, se reinicia si cae)
    7. Registra el respaldo diario "BuscaPieza-Respaldo"
    8. Instala/configura el túnel de Cloudflare y comprueba la URL pública
#>
param(
    [string]$Destino = 'C:\BuscaPieza',
    [string]$HoraRespaldo = '02:30'
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'comun.ps1')

$Origen = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path.TrimEnd('\')
$Destino = $Destino.TrimEnd('\')

Write-Host ''
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host '   BUSCAPIEZA RD - Instalación en servidor Windows' -ForegroundColor Cyan
Write-Host '============================================================' -ForegroundColor Cyan
Write-Info "Origen:  $Origen"
Write-Info "Destino: $Destino"

if (-not (Test-Administrador)) { Stop-Instalacion 'Ejecuta este instalador como administrador (usa INSTALAR-SERVIDOR.bat).' }

# Archivos descargados de internet: quitar la marca de "bloqueado"
Get-ChildItem -Path $Origen -Recurse -File -ErrorAction SilentlyContinue | Unblock-File -ErrorAction SilentlyContinue

# ─────────────────────────────────────────────────────────────────────────────
Write-Paso '1/8' 'Comprobando requisitos'

$python = Find-Python
if (-not $python) {
    if (Test-Winget) {
        $r = Read-Host '    Python 3.12 no está instalado. ¿Instalarlo ahora con winget? [S/n]'
        if ($r -notmatch '^[nN]') {
            & winget install -e --id Python.Python.3.12 --scope machine --accept-package-agreements --accept-source-agreements
            $python = Find-Python
        }
    }
    if (-not $python) {
        Stop-Instalacion "Instala Python 3.12 (64 bits, 'para todos los usuarios') desde https://www.python.org/downloads/windows/ y vuelve a ejecutar."
    }
}
Write-Ok "Python: $python"

$pgBin = Find-PostgresBin
$pgServicio = Get-Service -Name 'postgresql*' -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $pgBin -or -not $pgServicio) {
    Stop-Instalacion ("PostgreSQL no está instalado. Descárgalo de https://www.postgresql.org/download/windows/ " +
                      "(apunta la contraseña del usuario 'postgres') y vuelve a ejecutar este instalador.")
}
if ($pgServicio.Status -ne 'Running') {
    Write-Aviso "El servicio $($pgServicio.Name) está detenido; iniciándolo..."
    Start-Service $pgServicio.Name
    Set-Service $pgServicio.Name -StartupType Automatic
}
Write-Ok "PostgreSQL: $($pgServicio.Name) ($pgBin)"

$cloudflared = Find-Cloudflared
if (-not $cloudflared) {
    if (Test-Winget) {
        $r = Read-Host '    cloudflared no está instalado. ¿Instalarlo ahora con winget? [S/n]'
        if ($r -notmatch '^[nN]') {
            & winget install -e --id Cloudflare.cloudflared --accept-package-agreements --accept-source-agreements
            $cloudflared = Find-Cloudflared
        }
    }
    if (-not $cloudflared) {
        Write-Aviso 'cloudflared no está instalado: se omitirá el paso del túnel.'
        Write-Info  'Descárgalo de https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/'
    }
}
if ($cloudflared) { Write-Ok "cloudflared: $cloudflared" }

# ─────────────────────────────────────────────────────────────────────────────
Write-Paso '2/8' "Copiando la aplicación a $Destino"
if (Test-Path (Join-Path $Destino 'servidor.py')) {
    Write-Aviso 'Ya hay una instalación en esa carpeta: se detiene y se actualiza el código (datos y .env se conservan).'
    Stop-BuscaPieza $Destino
}
if ($Origen -ne $Destino) {
    New-Item -ItemType Directory -Force -Path $Destino | Out-Null
    Copy-Codigo $Origen $Destino
}
Write-Ok 'Archivos copiados'

# ─────────────────────────────────────────────────────────────────────────────
Write-Paso '3/8' 'Entorno virtual y dependencias (puede tardar unos minutos)'
$vpy = Join-Path $Destino 'venv\Scripts\python.exe'
if (-not (Test-Path $vpy)) {
    Invoke-Programa $python @('-m', 'venv', (Join-Path $Destino 'venv')) 'No se pudo crear el entorno virtual' | Out-Null
}
Install-Dependencias $Destino
Write-Ok 'Dependencias instaladas'

# ─────────────────────────────────────────────────────────────────────────────
Write-Paso '4/8' 'Configuración (.env)'
$rutaEnv = Join-Path $Destino '.env'
& $vpy (Join-Path $Destino 'scripts\configurar_env.py')
if ($LASTEXITCODE -ne 0) { Stop-Instalacion 'Configuración cancelada.' }
# Solo Administradores y SYSTEM pueden leer el .env (SIDs: independientes del idioma de Windows)
& icacls $rutaEnv /inheritance:r /grant:r '*S-1-5-32-544:F' '*S-1-5-18:F' | Out-Null
Write-Ok '.env protegido (solo Administradores y SYSTEM)'
$appUrl = Get-ValorEnv $rutaEnv 'APP_URL'
$puerto = Get-ValorEnv $rutaEnv 'FLASK_PORT'
if (-not $puerto) { $puerto = '5050' }
$dominio = $appUrl -replace '^https?://', '' -replace '/.*$', ''

# ─────────────────────────────────────────────────────────────────────────────
Write-Paso '5/8' 'Base de datos PostgreSQL'
$env:Path = "$pgBin;$env:Path"
Write-Info "Se pedirá la contraseña del superusuario 'postgres' (la del instalador de PostgreSQL)."
& $vpy (Join-Path $Destino 'scripts\crear_db_postgres.py')
if ($LASTEXITCODE -ne 0) { Stop-Instalacion 'No se pudo crear el usuario o la base de datos.' }
$codigoSeed = Update-BaseDatos $Destino
& $vpy (Join-Path $Destino 'scripts\configurar_env.py') --borrar-admin-password | Out-Host
Write-Ok 'Tablas y datos iniciales listos'
if ($codigoSeed -eq 3) {
    Write-Aviso 'Se generó una contraseña de admin (aparece arriba). Apúntala ahora.'
    Read-Host '    Pulsa Enter para continuar' | Out-Null
}

# ─────────────────────────────────────────────────────────────────────────────
Write-Paso '6/8' "Servicio de la aplicación (tarea '$TareaServidor')"
Stop-BuscaPieza $Destino
$accion = New-ScheduledTaskAction -Execute $vpy -Argument "`"$(Join-Path $Destino 'scripts\supervisor.py')`"" -WorkingDirectory $Destino
$disparador = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$ajustes = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $TareaServidor -Action $accion -Trigger $disparador -Principal $principal `
    -Settings $ajustes -Description 'BuscaPieza RD (waitress en 127.0.0.1). Instalado por instalar-servidor.ps1' -Force | Out-Null
Start-ScheduledTask -TaskName $TareaServidor
$urlLocal = "http://127.0.0.1:$puerto/salud"
if (Wait-Salud $urlLocal 90) {
    Write-Ok "La aplicación responde en http://127.0.0.1:$puerto"
} else {
    Stop-Instalacion "La aplicación no responde en $urlLocal. Revisa $Destino\logs\servidor-consola.log y logs\errors.log"
}

# ─────────────────────────────────────────────────────────────────────────────
Write-Paso '7/8' "Respaldo diario de la base ($HoraRespaldo, tarea '$TareaRespaldo')"
$accionR = New-ScheduledTaskAction -Execute $vpy -Argument "`"$(Join-Path $Destino 'scripts\respaldar_db.py')`"" -WorkingDirectory $Destino
$dispR = New-ScheduledTaskTrigger -Daily -At $HoraRespaldo
$ajustesR = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask -TaskName $TareaRespaldo -Action $accionR -Trigger $dispR -Principal $principal `
    -Settings $ajustesR -Description 'Respaldo diario de PostgreSQL de BuscaPieza RD' -Force | Out-Null
& $vpy (Join-Path $Destino 'scripts\respaldar_db.py') | Out-Host
if ($LASTEXITCODE -eq 0) { Write-Ok "Respaldo de prueba creado en $Destino\backups" }
else { Write-Aviso 'El respaldo de prueba falló; revisa el mensaje de arriba.' }

# ─────────────────────────────────────────────────────────────────────────────
Write-Paso '8/8' "Túnel de Cloudflare para https://$dominio"
$tunelListo = $false
if (-not $cloudflared) {
    Write-Aviso 'Omitido: cloudflared no está instalado.'
} else {
    $servicioCf = Get-Service -Name 'cloudflared' -ErrorAction SilentlyContinue
    if ($servicioCf) {
        Write-Aviso 'Este servidor ya tiene un túnel de Cloudflare instalado como servicio (cloudflared).'
        Write-Info  'No se instala otro: añade un "Public Hostname" a ese túnel en el panel de Cloudflare:'
        Write-Info  '  Zero Trust > Networks > Tunnels > (tu túnel) > Public Hostname > Add a public hostname'
        Write-Info  "    Hostname: $dominio"
        Write-Info  "    Service:  HTTP   URL: localhost:$puerto"
        Write-Info  '  (si ese túnel usa un config.yml local, añade la regla de ingress ANTES de la regla http_status:404)'
        Read-Host '    Pulsa Enter cuando lo hayas añadido' | Out-Null
    } else {
        Write-Info 'Crea el túnel en el panel de Cloudflare (el dominio debe estar en tu cuenta de Cloudflare):'
        Write-Info '  1. https://one.dash.cloudflare.com > Networks > Tunnels > Create a tunnel > Cloudflared'
        Write-Info '  2. Nombre: buscapieza  >  en "Install and run a connector" elige Windows'
        Write-Info '  3. Copia el comando que muestra (cloudflared.exe service install eyJ...)'
        Write-Info "  4. En 'Public Hostname': Hostname $dominio  >  Service HTTP  >  URL localhost:$puerto"
        Write-Host ''
        $seguro = Read-Host '    Pega aquí el comando o el token (Enter para omitir)' -AsSecureString
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($seguro)
        try { $texto = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
        $token = [regex]::Match($texto, 'eyJ[A-Za-z0-9_\-\.=]+').Value
        if ($token) {
            & $cloudflared service install $token | Out-Host
            if ($LASTEXITCODE -ne 0) { Write-Aviso 'cloudflared no se pudo instalar como servicio.' }
            else { Write-Ok 'Túnel instalado como servicio de Windows (cloudflared)' }
        } elseif ($texto) {
            Write-Aviso 'No se encontró un token válido (empieza por eyJ...). Puedes instalarlo luego con:'
            Write-Info  '  cloudflared.exe service install <TOKEN>'
        } else {
            Write-Aviso 'Omitido. Instálalo luego con: cloudflared.exe service install <TOKEN>'
        }
        $texto = $null; $token = $null
    }
    Write-Info "Comprobando https://$dominio/salud (hasta 2 minutos)..."
    $tunelListo = Wait-Salud "https://$dominio/salud" 120
    if ($tunelListo) { Write-Ok "Accesible públicamente en https://$dominio" }
    else {
        Write-Aviso "Aún no responde https://$dominio. Revisa:"
        Write-Info  "  - Que el dominio esté en Cloudflare y el Public Hostname apunte a HTTP localhost:$puerto"
        Write-Info  '  - Que el servicio cloudflared esté en ejecución (services.msc)'
        Write-Info  '  - Los cambios de DNS pueden tardar unos minutos'
    }
}

# ─────────────────────────────────────────────────────────────────────────────
Write-Host ''
Write-Host '============================================================' -ForegroundColor Green
Write-Host '   INSTALACIÓN COMPLETADA' -ForegroundColor Green
Write-Host '============================================================' -ForegroundColor Green
Write-Info "Carpeta:        $Destino"
Write-Info "URL pública:    https://$dominio  $(if ($tunelListo) { '(OK)' } else { '(pendiente de túnel)' })"
Write-Info "URL local:      http://127.0.0.1:$puerto"
Write-Info "Admin:          $(Get-ValorEnv $rutaEnv 'ADMIN_EMAIL')"
Write-Info "Logs:           $Destino\logs"
Write-Info "Respaldos:      $Destino\backups (diario a las $HoraRespaldo)"
Write-Host ''
Write-Info 'Siguientes pasos:'
Write-Info "  - Entra en https://$dominio/auth/login y revisa Admin > Configuración"
Write-Info '  - Para actualizar a una versión nueva: descomprime el paquete nuevo y ejecuta ACTUALIZAR.bat'
Write-Host ''
