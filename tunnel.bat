@echo off
title BuscaPieza RD - Tunel Cloudflare
color 0E

cd /d "%~dp0"

echo.
echo  Abriendo tunel Cloudflare hacia http://localhost:5050
echo  (la URL publica aparecera abajo, tipo https://xxxx.trycloudflare.com)
echo.
echo  IMPORTANTE: Deja el servidor Flask (iniciar.bat) corriendo en otra ventana.
echo  Presiona Ctrl+C para cerrar el tunel.
echo.

:: Usamos --config con un archivo vacio propio de este proyecto para que
:: cloudflared NO cargue el config.yml global (~/.cloudflared/config.yml),
:: que ya tiene un tunel con nombre para otro proyecto (marketgarrido.com)
:: con una regla catch-all "http_status:404" que interceptaba las peticiones.
cloudflared tunnel --config "%~dp0cloudflared_quick.yml" --url http://localhost:5050
pause
