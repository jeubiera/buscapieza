# Funciones compartidas por instalar-servidor.ps1, actualizar.ps1 y desinstalar.ps1

$TareaServidor = 'BuscatodoRD-Servidor'
$TareaRespaldo = 'BuscatodoRD-Respaldo'

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
# Python debe escribir UTF-8 aunque su salida pase por PowerShell (evita errores con ✓, ñ, etc.)
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }

function Write-Paso([string]$Numero, [string]$Texto) {
    Write-Host ''
    Write-Host "[$Numero] $Texto" -ForegroundColor Cyan
}
function Write-Ok([string]$Texto)    { Write-Host "    OK  $Texto" -ForegroundColor Green }
function Write-Aviso([string]$Texto) { Write-Host "    !!  $Texto" -ForegroundColor Yellow }
function Write-Info([string]$Texto)  { Write-Host "        $Texto" }

function Stop-Instalacion([string]$Texto) {
    Write-Host ''
    Write-Host "ERROR: $Texto" -ForegroundColor Red
    Write-Host ''
    exit 1
}

function Test-Administrador {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    return ([Security.Principal.WindowsPrincipal]$id).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# Ejecuta un programa externo (no interactivo), muestra su salida y aborta si devuelve error.
# Devuelve solo el código de salida.
function Invoke-Programa {
    param([string]$Programa, [string[]]$Argumentos, [string]$Descripcion, [int[]]$CodigosOk = @(0))
    & $Programa @Argumentos | Out-Host
    if ($CodigosOk -notcontains $LASTEXITCODE) {
        Stop-Instalacion "$Descripcion (código $LASTEXITCODE)"
    }
    return $LASTEXITCODE
}

function Find-Python {
    $ErrorActionPreference = 'Continue'
    $candidatos = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($v in '3.12', '3.13', '3.11') {
            $p = & py "-$v" -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $p) { $candidatos += $p.Trim() }
        }
    }
    $candidatos += Get-ChildItem 'C:\Program Files\Python31*\python.exe' -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | ForEach-Object { $_.FullName }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notmatch 'WindowsApps') { $candidatos += $cmd.Source }

    foreach ($c in $candidatos) {
        if (-not (Test-Path $c)) { continue }
        $ver = & $c -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and [version]$ver -ge [version]'3.11') { return $c }
    }
    return $null
}

function Find-Cloudflared {
    $cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($p in 'C:\Program Files (x86)\cloudflared\cloudflared.exe', 'C:\Program Files\cloudflared\cloudflared.exe') {
        if (Test-Path $p) { return $p }
    }
    return $null
}

function Find-PostgresBin {
    $bins = Get-ChildItem 'C:\Program Files\PostgreSQL\*\bin\pg_dump.exe' -ErrorAction SilentlyContinue |
        Sort-Object { [int]($_.Directory.Parent.Name -replace '\D', '') } -Descending
    if ($bins) { return $bins[0].Directory.FullName }
    $cmd = Get-Command pg_dump -ErrorAction SilentlyContinue
    if ($cmd) { return (Split-Path $cmd.Source) }
    return $null
}

function Test-Winget { return [bool](Get-Command winget -ErrorAction SilentlyContinue) }

function Get-ValorEnv([string]$RutaEnv, [string]$Clave) {
    if (-not (Test-Path $RutaEnv)) { return '' }
    $linea = Get-Content $RutaEnv -Encoding UTF8 | Where-Object { $_ -match "^$Clave=" } | Select-Object -First 1
    if ($linea) { return ($linea -replace "^$Clave=", '').Trim() }
    return ''
}

# Detiene la tarea y cualquier proceso python que esté ejecutando esta instalación
function Stop-BuscatodoRD([string]$Destino) {
    if (Get-ScheduledTask -TaskName $TareaServidor -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $TareaServidor -ErrorAction SilentlyContinue
    }
    $patron = [regex]::Escape($Destino)
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" |
        Where-Object { $_.CommandLine -match $patron -and $_.CommandLine -match 'supervisor\.py|servidor\.py' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
}

function Wait-Salud([string]$Url, [int]$Segundos = 60) {
    $limite = (Get-Date).AddSeconds($Segundos)
    while ((Get-Date) -lt $limite) {
        try {
            $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
            if ($r.StatusCode -eq 200) { return $true }
        } catch { }
        Start-Sleep -Seconds 3
    }
    return $false
}

# Copia el código nuevo sin tocar datos ni configuración del servidor
function Copy-Codigo([string]$Origen, [string]$Destino) {
    $excluirDirs = @('.git', 'venv', '.venv', 'logs', 'backups', '__pycache__', '.pytest_cache',
                     (Join-Path $Destino 'static\uploads'), (Join-Path $Destino 'secrets'))
    $excluirArchivos = @('.env', '.env.anterior', '*.pyc', 'firebase-credentials.json')
    $argRobocopy = @($Origen, $Destino, '/MIR', '/NFL', '/NDL', '/NJH', '/NJS', '/NP', '/R:2', '/W:2',
                     '/XD') + $excluirDirs + @('/XF') + $excluirArchivos
    & robocopy @argRobocopy | Out-Null
    if ($LASTEXITCODE -ge 8) { Stop-Instalacion "No se pudieron copiar los archivos (robocopy $LASTEXITCODE)" }
    New-Item -ItemType Directory -Force -Path (Join-Path $Destino 'static\uploads'), (Join-Path $Destino 'logs'),
        (Join-Path $Destino 'backups') | Out-Null
}

function Install-Dependencias([string]$Destino) {
    $vpy = Join-Path $Destino 'venv\Scripts\python.exe'
    Invoke-Programa $vpy @('-m', 'pip', 'install', '--quiet', '--disable-pip-version-check', '--upgrade', 'pip') 'No se pudo actualizar pip' | Out-Null
    Invoke-Programa $vpy @('-m', 'pip', 'install', '--quiet', '--disable-pip-version-check', '-r', (Join-Path $Destino 'requirements.txt')) 'Falló la instalación de dependencias' | Out-Null
}

function Update-BaseDatos([string]$Destino) {
    $vpy = Join-Path $Destino 'venv\Scripts\python.exe'
    Push-Location $Destino
    try {
        Invoke-Programa $vpy @('-m', 'flask', '--app', 'app:create_app', 'db', 'upgrade') 'Falló la migración de la base de datos' | Out-Null
        $codigo = Invoke-Programa $vpy @('-m', 'flask', '--app', 'app:create_app', 'seed') 'Falló la carga de datos iniciales' -CodigosOk @(0, 3)
        return $codigo
    } finally { Pop-Location }
}
