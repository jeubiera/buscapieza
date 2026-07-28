@echo off
title BuscaPieza RD - Servidor
color 0B

:: Cambiarse al directorio donde está este .bat
cd /d "%~dp0"

echo.
echo  Iniciando BuscaPieza RD...
echo  Directorio: %CD%
echo  Abre tu navegador en: http://localhost:5050
echo.
echo  IMPORTANTE: Asegurate de que XAMPP MySQL este activo
echo  Presiona Ctrl+C para detener el servidor
echo.
python app.py
pause
