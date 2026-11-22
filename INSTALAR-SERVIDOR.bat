@echo off
:: BuscatodoRD - Instalacion en servidor Windows (pide permisos de administrador)
cd /d "%~dp0"
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Solicitando permisos de administrador...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalador\instalar-servidor.ps1" %*
echo.
pause
