"""
Ejecución de tareas en segundo plano (notificaciones WhatsApp / Push).

Las llamadas a Green API y Firebase pueden tardar varios segundos cada una; hacerlas
dentro de la petición dejaba al usuario esperando (o provocaba timeouts al notificar
a muchos proveedores). Aquí se envían en un pool de hilos con su propio app context.

Importante: pasa IDs, no objetos del ORM — cada hilo abre su propia sesión.
Con NOTIFICACIONES_SINCRONAS=True (tests) se ejecutan en línea.
"""
from concurrent.futures import ThreadPoolExecutor
from flask import current_app

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix='bp-notif')


def en_segundo_plano(func, *args, **kwargs):
    app = current_app._get_current_object()

    def _ejecutar():
        with app.app_context():
            from extensions import db
            try:
                func(*args, **kwargs)
            except Exception as e:
                app.logger.error(f"Error en tarea {func.__name__}: {e}", exc_info=True)
            finally:
                db.session.remove()

    if app.config.get('NOTIFICACIONES_SINCRONAS'):
        try:
            func(*args, **kwargs)
        except Exception as e:
            app.logger.error(f"Error en tarea {func.__name__}: {e}", exc_info=True)
        return None
    return _executor.submit(_ejecutar)
