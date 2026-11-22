r"""
Servidor de producción (Windows) para BuscaPieza RD.

Usa waitress (gunicorn no funciona en Windows) y escucha solo en 127.0.0.1:
el tráfico público entra por el túnel de Cloudflare, que reenvía a esta dirección.

    venv\Scripts\python.exe servidor.py

El instalador lo registra como tarea programada "BuscaPieza-Servidor"
(arranca con Windows y se reinicia si se cae).
"""
import os
import sys

RAIZ = os.path.dirname(os.path.abspath(__file__))
os.chdir(RAIZ)
sys.path.insert(0, RAIZ)

from waitress import serve                                   # noqa: E402
from werkzeug.middleware.proxy_fix import ProxyFix           # noqa: E402

from app import create_app                                   # noqa: E402

app = create_app(os.environ.get('FLASK_ENV') or 'production')
# Cloudflare Tunnel envía X-Forwarded-For / X-Forwarded-Proto: así Flask ve https y la IP real
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)


if __name__ == '__main__':
    host = app.config.get('FLASK_HOST', '127.0.0.1')
    port = int(app.config.get('FLASK_PORT', 5050))
    hilos = int(os.environ.get('WAITRESS_THREADS', '8'))
    app.logger.info(f'Servidor waitress en http://{host}:{port} ({hilos} hilos)')
    print(f'BuscaPieza RD escuchando en http://{host}:{port}', flush=True)
    serve(app, host=host, port=port, threads=hilos, ident='BuscaPieza',
          clear_untrusted_proxy_headers=False)
