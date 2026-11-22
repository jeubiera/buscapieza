@echo off
title BuscatodoRD - Instalacion
color 0A

:: Cambiarse al directorio donde está este .bat
cd /d "%~dp0"

echo.
echo  ============================================
echo   BUSCATODO RD - Instalacion
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
echo   1. Edita .env (DATABASE_URL de PostgreSQL)
echo   2. Crea la base:  python scripts\crear_db_postgres.py
echo   3. Ejecuta iniciar.bat para arrancar
echo   Admin: ADMIN_EMAIL / ADMIN_PASSWORD de tu .env
echo   (si ADMIN_PASSWORD esta vacio, la clave se muestra al arrancar)
echo  ============================================
echo.
pause
