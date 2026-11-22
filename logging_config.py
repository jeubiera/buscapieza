"""
Configuración de logging para BuscaPieza RD

Sistema de logs con rotación automática y diferentes niveles por entorno.
"""
import logging
import os
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from datetime import datetime


def configurar_logging(app):
    """
    Configura el sistema de logging con rotación de archivos

    Args:
        app: Instancia de Flask
    """
    # Quitar handlers de una llamada anterior (app.logger es compartido entre
    # instancias de create_app, p. ej. en tests o con recarga en caliente)
    for lg in (app.logger, logging.getLogger('buscapieza.transactions'),
               logging.getLogger('buscapieza.notifications')):
        for h in [h for h in lg.handlers if getattr(h, '_buscapieza', False)]:
            lg.removeHandler(h)
            h.close()

    # En tests no se escriben archivos de log
    if app.testing:
        app.logger.setLevel(logging.WARNING)
        return app

    # Crear directorio de logs si no existe
    log_dir = os.path.join(app.root_path, 'logs')
    os.makedirs(log_dir, exist_ok=True)

    # Determinar nivel de log según entorno
    if app.config.get('FLASK_DEBUG'):
        log_level = logging.DEBUG
    else:
        log_level = logging.INFO

    # Formato de logs
    formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s en %(module)s.%(funcName)s:%(lineno)d - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # =========================================
    # 1. LOG GENERAL (app.log)
    # =========================================
    # Rotación por tamaño (10MB, mantener 10 backups)
    file_handler = RotatingFileHandler(
        os.path.join(log_dir, 'app.log'),
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=10,
        encoding='utf-8'
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)

    # =========================================
    # 2. LOG DE ERRORES (errors.log)
    # =========================================
    # Solo errores y críticos
    error_handler = RotatingFileHandler(
        os.path.join(log_dir, 'errors.log'),
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=10,
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)

    # =========================================
    # 3. LOG DIARIO (access-YYYY-MM-DD.log)
    # =========================================
    # Rotación diaria, mantener 30 días
    daily_handler = TimedRotatingFileHandler(
        os.path.join(log_dir, 'access.log'),
        when='midnight',
        interval=1,
        backupCount=30,
        encoding='utf-8'
    )
    daily_handler.setLevel(logging.INFO)
    daily_handler.setFormatter(formatter)
    # Agregar sufijo de fecha a los archivos rotados
    daily_handler.suffix = '%Y-%m-%d'

    # =========================================
    # 4. LOG DE TRANSACCIONES (transactions.log)
    # =========================================
    # Específico para transacciones y comisiones
    transaction_handler = RotatingFileHandler(
        os.path.join(log_dir, 'transactions.log'),
        maxBytes=5 * 1024 * 1024,  # 5MB
        backupCount=20,
        encoding='utf-8'
    )
    transaction_handler.setLevel(logging.INFO)
    transaction_handler.setFormatter(formatter)

    # =========================================
    # 5. CONSOLE HANDLER (desarrollo)
    # =========================================
    if app.config.get('FLASK_DEBUG'):
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(logging.Formatter(
            '%(levelname)s: %(message)s'
        ))
        console_handler._buscapieza = True
        app.logger.addHandler(console_handler)

    for h in (file_handler, error_handler, daily_handler, transaction_handler):
        h._buscapieza = True

    # Agregar handlers al logger de Flask
    app.logger.addHandler(file_handler)
    app.logger.addHandler(error_handler)
    app.logger.addHandler(daily_handler)

    # Configurar nivel del logger
    app.logger.setLevel(log_level)

    # =========================================
    # LOGGER SEPARADO PARA TRANSACCIONES
    # =========================================
    transaction_logger = logging.getLogger('buscapieza.transactions')
    transaction_logger.setLevel(logging.INFO)
    transaction_logger.addHandler(transaction_handler)
    app.transaction_logger = transaction_logger

    # =========================================
    # LOGGER PARA NOTIFICACIONES
    # =========================================
    notification_handler = RotatingFileHandler(
        os.path.join(log_dir, 'notifications.log'),
        maxBytes=5 * 1024 * 1024,
        backupCount=10,
        encoding='utf-8'
    )
    notification_handler.setFormatter(formatter)
    notification_handler._buscapieza = True

    notification_logger = logging.getLogger('buscapieza.notifications')
    notification_logger.setLevel(logging.INFO)
    notification_logger.addHandler(notification_handler)
    app.notification_logger = notification_logger

    # Log de inicio
    app.logger.info('='*60)
    app.logger.info(f'BuscaPieza RD iniciando - Entorno: {app.config.get("FLASK_ENV", "development")}')
    app.logger.info(f'Nivel de log: {logging.getLevelName(log_level)}')
    app.logger.info('='*60)

    return app


def log_transaction(app, transaccion, accion='creada'):
    """
    Helper para loguear transacciones

    Args:
        app: Instancia de Flask
        transaccion: Objeto Transaccion
        accion: Tipo de acción (creada, pagada, cancelada, etc.)
    """
    if hasattr(app, 'transaction_logger'):
        app.transaction_logger.info(
            f'Transacción #{transaccion.id} {accion} - '
            f'Cliente: {transaccion.cliente_id}, '
            f'Proveedor: {transaccion.proveedor_id}, '
            f'Precio Cliente: ${transaccion.precio_cliente}, '
            f'Comisión Broker: ${transaccion.comision_broker}, '
            f'Estado: {transaccion.estado_pago}'
        )


def log_notification(app, tipo, destinatario, mensaje, exito=True, error=None):
    """
    Helper para loguear notificaciones

    Args:
        app: Instancia de Flask
        tipo: Tipo de notificación (whatsapp, push, email)
        destinatario: Destinatario de la notificación
        mensaje: Mensaje enviado
        exito: Si se envió correctamente
        error: Mensaje de error si falló
    """
    if hasattr(app, 'notification_logger'):
        status = 'OK' if exito else 'ERROR'
        log_msg = f'[{tipo.upper()}] {status} - Destinatario: {destinatario}'

        if exito:
            app.notification_logger.info(log_msg)
        else:
            app.notification_logger.error(f'{log_msg} - Error: {error}')


def log_request(app, request, response):
    """
    Helper para loguear requests HTTP

    Args:
        app: Instancia de Flask
        request: Request de Flask
        response: Response de Flask
    """
    app.logger.info(
        f'{request.remote_addr} - "{request.method} {request.path}" '
        f'{response.status_code} - User Agent: {request.user_agent}'
    )
