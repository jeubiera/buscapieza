@echo off
:: BuscatodoRD - Actualizar una instalacion existente (pide permisos de administrador)
:: Descomprime el paquete nuevo en una carpeta distinta de C:\BuscatodoRD y ejecuta este archivo.
cd /d "%~dp0"
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Solicitando permisos de administrador...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalador\actualizar.ps1" %*
echo.
pause
