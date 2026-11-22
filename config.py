import os


def _database_url():
    url = os.environ.get('DATABASE_URL', '').strip()
    if not url:
        return 'postgresql+psycopg2://postgres:@localhost:5432/buscapieza'  # Solo desarrollo local
    # Muchos hostings (Heroku, Render, Railway...) entregan "postgres://", que SQLAlchemy no acepta
    if url.startswith('postgres://'):
        url = 'postgresql+psycopg2://' + url[len('postgres://'):]
    elif url.startswith('postgresql://'):
        url = 'postgresql+psycopg2://' + url[len('postgresql://'):]
    return url


def _bool(nombre, default='False'):
    return os.environ.get(nombre, default).strip().lower() in ('1', 'true', 'yes', 'si', 'sí')


class Config:
    """
    Configuración base de BuscaPieza RD

    Todas las credenciales sensibles se cargan desde variables de entorno.
    Crea un archivo .env basado en .env.example para configurar tu instalación.
    Las claves de integraciones también se pueden cambiar desde /admin/configuracion
    (se guardan cifradas en la BD y tienen prioridad sobre el .env).
    """

    # =========================================
    # SEGURIDAD
    # =========================================
    # La validación (obligatoria) se hace en create_app para no matar el proceso al importar.
    SECRET_KEY = os.environ.get('SECRET_KEY')

    SESSION_COOKIE_HTTPONLY  = True
    SESSION_COOKIE_SAMESITE  = 'Lax'
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = 'Lax'

    WTF_CSRF_ENABLED    = True
    WTF_CSRF_TIME_LIMIT = None   # el token vive lo que dure la sesión

    # Admin inicial (solo se usa si no existe ningún admin en la BD)
    ADMIN_EMAIL    = os.environ.get('ADMIN_EMAIL', 'admin@buscapieza.do')
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', '')

    # =========================================
    # BASE DE DATOS
    # =========================================
    # Formato: postgresql+psycopg2://usuario:contraseña@host:5432/nombre_db
    SQLALCHEMY_DATABASE_URI = _database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = False
    SQLALCHEMY_ENGINE_OPTIONS = {'pool_pre_ping': True}

    # Las tablas se crean con migraciones (`flask db upgrade`, lo hace iniciar.bat).
    # AUTO_CREATE_DB=True usa db.create_all() en su lugar (solo para pruebas rápidas).
    AUTO_CREATE_DB = _bool('AUTO_CREATE_DB', 'False')

    # =========================================
    # URL PÚBLICA (para enlaces en WhatsApp / Push)
    # =========================================
    APP_URL = os.environ.get('APP_URL', 'http://127.0.0.1:5050').rstrip('/')

    # =========================================
    # CLOUDINARY (Almacenamiento de imágenes)
    # =========================================
    CLOUDINARY_CLOUD_NAME = os.environ.get('CLOUDINARY_CLOUD_NAME', '')
    CLOUDINARY_API_KEY    = os.environ.get('CLOUDINARY_API_KEY', '')
    CLOUDINARY_API_SECRET = os.environ.get('CLOUDINARY_API_SECRET', '')

    # =========================================
    # GREEN API (WhatsApp Business)
    # =========================================
    GREEN_API_INSTANCE = os.environ.get('GREEN_API_INSTANCE', '')
    GREEN_API_TOKEN    = os.environ.get('GREEN_API_TOKEN', '')

    # =========================================
    # FIREBASE (Notificaciones Push)
    # =========================================
    # Servidor: ruta al JSON de la cuenta de servicio (Admin SDK)
    FIREBASE_CREDENTIALS_PATH = os.environ.get('FIREBASE_CREDENTIALS_PATH', '')
    # Navegador: configuración web (JSON de "firebaseConfig") y clave VAPID pública
    FIREBASE_WEB_CONFIG   = os.environ.get('FIREBASE_WEB_CONFIG', '')
    FIREBASE_VAPID_PUBLIC = os.environ.get('FIREBASE_VAPID_PUBLIC', '')

    # =========================================
    # CONFIGURACIÓN DEL BROKER
    # =========================================
    BROKER_WHATSAPP = os.environ.get('BROKER_WHATSAPP', '18091234567')
    BROKER_NOMBRE   = os.environ.get('BROKER_NOMBRE', 'BuscaPieza RD')

    # =========================================
    # NOTIFICACIONES
    # =========================================
    # True = se envían dentro de la petición (útil en tests). False = hilo en segundo plano.
    NOTIFICACIONES_SINCRONAS = False

    # =========================================
    # ARCHIVOS Y UPLOADS
    # =========================================
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024  # 20MB máximo por petición
    UPLOAD_FOLDER = os.path.join('static', 'uploads')
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif'}

    # =========================================
    # SERVIDOR FLASK
    # =========================================
    FLASK_HOST = os.environ.get('FLASK_HOST', '127.0.0.1')
    FLASK_PORT = int(os.environ.get('FLASK_PORT', 5050))
    FLASK_DEBUG = _bool('FLASK_DEBUG')


def validar_configuracion(app):
    """Advierte (en el log) qué integraciones opcionales faltan."""
    cfg = app.config
    warnings = []
    if not cfg.get('CLOUDINARY_CLOUD_NAME'):
        warnings.append("CLOUDINARY no configurado. Las imágenes se guardarán localmente.")
    if not cfg.get('GREEN_API_INSTANCE') or not cfg.get('GREEN_API_TOKEN'):
        warnings.append("GREEN API (WhatsApp) no configurado. Las notificaciones WhatsApp no funcionarán.")
    if not cfg.get('FIREBASE_CREDENTIALS_PATH'):
        warnings.append("FIREBASE no configurado. Las notificaciones push no funcionarán.")
    for w in warnings:
        app.logger.warning(f"⚠️  {w}")
    return not warnings


class DevelopmentConfig(Config):
    """Configuración para desarrollo local"""
    DEBUG = True
    TESTING = False


class ProductionConfig(Config):
    """Configuración para producción"""
    DEBUG = False
    TESTING = False
    AUTO_CREATE_DB = _bool('AUTO_CREATE_DB', 'False')

    # Detrás de HTTPS (Cloudflare tunnel / Nginx) las cookies solo viajan cifradas.
    SESSION_COOKIE_SECURE  = _bool('SESSION_COOKIE_SECURE', 'True')
    REMEMBER_COOKIE_SECURE = _bool('SESSION_COOKIE_SECURE', 'True')


class TestingConfig(Config):
    """Configuración para tests"""
    TESTING = True
    SECRET_KEY = 'test-secret-key-for-testing-only'
    # Por defecto SQLite en memoria. Para probar contra PostgreSQL usa una BD vacía y desechable:
    #   TEST_DATABASE_URL=postgresql+psycopg2://usuario:clave@localhost:5432/buscapieza_test
    SQLALCHEMY_DATABASE_URI = os.environ.get('TEST_DATABASE_URL', 'sqlite:///:memory:')
    SQLALCHEMY_ENGINE_OPTIONS = {}
    WTF_CSRF_ENABLED = False
    AUTO_CREATE_DB = True
    NOTIFICACIONES_SINCRONAS = True
    ADMIN_PASSWORD = ''
    APP_URL = 'http://localhost'
    # Sin integraciones externas en tests
    CLOUDINARY_CLOUD_NAME = CLOUDINARY_API_KEY = CLOUDINARY_API_SECRET = ''
    GREEN_API_INSTANCE = GREEN_API_TOKEN = ''
    FIREBASE_CREDENTIALS_PATH = FIREBASE_WEB_CONFIG = FIREBASE_VAPID_PUBLIC = ''


# Mapeo de configuraciones por entorno
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}
