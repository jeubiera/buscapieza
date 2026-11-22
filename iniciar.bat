@echo off
title BuscatodoRD - Servidor
color 0B

:: Cambiarse al directorio donde está este .bat
cd /d "%~dp0"

echo.
echo  Iniciando BuscatodoRD...
echo  Directorio: %CD%
echo  Abre tu navegador en: http://localhost:PUERTO  (FLASK_PORT de tu .env, 5050 por defecto)
echo.
echo  IMPORTANTE: PostgreSQL debe estar en ejecucion (servicio postgresql-x64)
echo  Presiona Ctrl+C para detener el servidor
echo.

:: Aplicar migraciones pendientes y datos iniciales (no hace nada si ya estan)
python -m flask --app "app:create_app" db upgrade
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] No se pudo preparar la base de datos.
    echo  - Revisa que PostgreSQL este en ejecucion
    echo  - Revisa DATABASE_URL en .env
    echo  - Si la base aun no existe: python scripts\crear_db_postgres.py
    pause & exit /b 1
)
python -m flask --app "app:create_app" seed
if %errorlevel% equ 3 (
    echo.
    echo  ^>^>^> APUNTA la contrasena del admin que aparece arriba. No se volvera a mostrar.
    echo  ^>^>^> Si la pierdes: python -m flask --app "app:create_app" admin-password
    echo.
    pause
)

python app.py
pause
