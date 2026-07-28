import os
import sys

class Config:
    """
    Configuración base de BuscaPieza RD

    Todas las credenciales sensibles se cargan desde variables de entorno.
    Crea un archivo .env basado en .env.example para configurar tu instalación.
    """

    # =========================================
    # SEGURIDAD
    # =========================================
    SECRET_KEY = os.environ.get('SECRET_KEY')
    if not SECRET_KEY:
        print("ERROR: SECRET_KEY no está configurada.")
        print("Genera una clave segura con: python -c 'import secrets; print(secrets.token_hex(32))'")
        sys.exit(1)

    # =========================================
    # BASE DE DATOS
    # =========================================
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        'mysql+pymysql://root:@localhost/buscapieza_db'  # Solo para desarrollo local
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'

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
    FIREBASE_SERVER_KEY = os.environ.get('FIREBASE_SERVER_KEY', '')

    # =========================================
    # CONFIGURACIÓN DEL BROKER
    # =========================================
    BROKER_WHATSAPP = os.environ.get('BROKER_WHATSAPP', '18091234567')
    BROKER_NOMBRE   = os.environ.get('BROKER_NOMBRE', 'BuscaPieza RD')

    # =========================================
    # ARCHIVOS Y UPLOADS
    # =========================================
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024  # 20MB máximo
    UPLOAD_FOLDER = os.path.join('static', 'uploads')
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif'}

    # =========================================
    # SERVIDOR FLASK
    # =========================================
    FLASK_HOST = os.environ.get('FLASK_HOST', '127.0.0.1')
    FLASK_PORT = int(os.environ.get('FLASK_PORT', 5050))
    FLASK_DEBUG = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'

    @staticmethod
    def validar_configuracion():
        """
        Valida que todas las configuraciones críticas estén presentes
        """
        warnings = []

        # Cloudinary (opcional pero recomendado)
        if not Config.CLOUDINARY_CLOUD_NAME:
            warnings.append("⚠️  CLOUDINARY no configurado. Las imágenes se guardarán localmente.")

        # WhatsApp (opcional pero recomendado)
        if not Config.GREEN_API_INSTANCE or not Config.GREEN_API_TOKEN:
            warnings.append("⚠️  GREEN API (WhatsApp) no configurado. Las notificaciones WhatsApp no funcionarán.")

        # Firebase (opcional)
        if not Config.FIREBASE_SERVER_KEY:
            warnings.append("⚠️  FIREBASE no configurado. Las notificaciones push no funcionarán.")

        if warnings:
            print("\n" + "="*60)
            print("ADVERTENCIAS DE CONFIGURACIÓN:")
            for warning in warnings:
                print(warning)
            print("="*60 + "\n")

        return True


class DevelopmentConfig(Config):
    """Configuración para desarrollo local"""
    DEBUG = True
    TESTING = False


class ProductionConfig(Config):
    """Configuración para producción"""
    DEBUG = False
    TESTING = False

    # Validar que estamos usando HTTPS en producción
    @staticmethod
    def init_app(app):
        Config.init_app(app)

        # Log de advertencias si no hay configuraciones críticas
        import logging
        logging.basicConfig(level=logging.INFO)


class TestingConfig(Config):
    """Configuración para tests"""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False


# Mapeo de configuraciones por entorno
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}
