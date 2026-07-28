@echo off
title BuscaPieza RD - Instalacion
color 0A

:: Cambiarse al directorio donde está este .bat
cd /d "%~dp0"

echo.
echo  ============================================
echo   BUSCAPIEZA RD - Instalacion
echo  ============================================
echo  Directorio: %CD%
echo.

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python no esta instalado.
    echo Descargalo de: https://www.python.org/downloads/
    pause & exit /b 1
)

echo [1/3] Instalando dependencias Python...
pip install -r requirements.txt --quiet
if %errorlevel% neq 0 (
    echo [ERROR] Fallo la instalacion de dependencias.
    pause & exit /b 1
)
echo     OK - Dependencias instaladas

echo [2/3] Creando carpetas necesarias...
if not exist "static\uploads" mkdir "static\uploads"
if not exist "static\icons"   mkdir "static\icons"
echo     OK

echo [3/3] Listo!
echo.
echo  ============================================
echo   Ejecuta iniciar.bat para arrancar
echo   Admin: admin@buscapieza.do / Admin2024!
echo  ============================================
echo.
pause
