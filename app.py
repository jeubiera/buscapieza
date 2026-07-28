from flask import Flask, request, g
from extensions import db, login_manager
from config import config, Config
import os
from dotenv import load_dotenv
from logging_config import configurar_logging
import time

# Cargar variables de entorno desde .env
load_dotenv()

def create_app(config_name=None):
    """
    Factory pattern para crear la aplicación Flask

    Args:
        config_name: 'development', 'production', 'testing' o None (usa FLASK_ENV)
    """
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'development')

    app = Flask(__name__)
    app.config.from_object(config[config_name])

    # Configurar logging
    configurar_logging(app)

    # Validar configuración
    Config.validar_configuracion()

    # Inicializar extensiones
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view     = 'auth.login'
    login_manager.login_message  = 'Debes iniciar sesión para continuar'

    # Registrar blueprints
    from blueprints.main       import main_bp
    from blueprints.auth       import auth_bp
    from blueprints.solicitudes import sol_bp
    from blueprints.ofertas    import oferta_bp
    from blueprints.admin      import admin_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp,    url_prefix='/auth')
    app.register_blueprint(sol_bp,     url_prefix='/solicitudes')
    app.register_blueprint(oferta_bp,  url_prefix='/ofertas')
    app.register_blueprint(admin_bp,   url_prefix='/admin')

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    with app.app_context():
        db.create_all()
        _seed()

    # Middleware para logging de requests
    @app.before_request
    def before_request():
        g.start_time = time.time()

    @app.after_request
    def after_request(response):
        # Calcular tiempo de respuesta
        if hasattr(g, 'start_time'):
            elapsed = time.time() - g.start_time
            response.headers['X-Response-Time'] = f'{elapsed:.3f}s'

            # Log solo en desarrollo o para rutas importantes
            if app.config.get('FLASK_DEBUG') or response.status_code >= 400:
                app.logger.info(
                    f'{request.remote_addr} - "{request.method} {request.path}" '
                    f'{response.status_code} - {elapsed:.3f}s'
                )

        return response

    @app.errorhandler(404)
    def not_found(error):
        app.logger.warning(f'404 Not Found: {request.url}')
        return "Página no encontrada", 404

    @app.errorhandler(500)
    def internal_error(error):
        app.logger.error(f'500 Internal Error: {error}', exc_info=True)
        db.session.rollback()
        return "Error interno del servidor", 500

    return app


def _seed():
    from models import Categoria, Provincia, Usuario, Configuracion
    if not Provincia.query.first():
        for p in [
            'Santo Domingo','Santiago','La Vega','San Pedro de Macorís',
            'San Cristóbal','La Romana','Puerto Plata','Duarte','Espaillat',
            'Barahona','Azua','San Juan','Monseñor Nouel','Monte Plata',
            'Hato Mayor','El Seibo','La Altagracia','Samaná',
            'María Trinidad Sánchez','Sánchez Ramírez','Valverde',
            'Santiago Rodríguez','Monte Cristi','Dajabón','Elías Piña',
            'Independencia','Pedernales','Bahoruco','Peravia',
            'San José de Ocoa','Hermanas Mirabal',
        ]:
            db.session.add(Provincia(nombre=p))

    if not Categoria.query.first():
        for n, i, c in [
            ('Repuestos Automotrices',          '🔧', '#FF6B35'),
            ('Electrónica & Electrodomésticos', '⚡', '#4ECDC4'),
            ('Ferretería & Construcción',       '🏗️', '#F7DC6F'),
            ('Maquinaria & Equipos',            '⚙️', '#A569BD'),
            ('Computadoras & Tecnología',       '💻', '#5DADE2'),
            ('Motocicletas & ATV',              '🏍️', '#E74C3C'),
            ('Hogar & Muebles',                 '🏠', '#27AE60'),
            ('Médico & Farmacéutico',           '💊', '#EC407A'),
            ('Agropecuario',                    '🌾', '#8BC34A'),
            ('Otros',                           '📦', '#90A4AE'),
        ]:
            db.session.add(Categoria(nombre=n, icono=i, color=c))

    if not Usuario.query.filter_by(rol='admin').first():
        admin = Usuario(
            nombre='Admin BuscaPieza', email='admin@buscapieza.do',
            telefono='8091234567', rol='admin', activo=True, verificado=True
        )
        admin.set_password('Admin2024!')
        db.session.add(admin)

    # Configuraciones de comisiones y sistema
    if not Configuracion.query.first():
        configs = [
            ('comision_default', '15.00'),  # % de comisión por defecto
            ('comision_minima', '5.00'),    # % mínimo de comisión
            ('comision_maxima', '30.00'),   # % máximo de comisión
            ('moneda', 'RD$'),              # Moneda del sistema
            ('impuesto_itbis', '18.00'),    # % de ITBIS (opcional)
        ]
        for clave, valor in configs:
            db.session.add(Configuracion(clave=clave, valor=valor))

    db.session.commit()


@login_manager.user_loader
def load_user(uid):
    from models import Usuario
    return Usuario.query.get(int(uid))


if __name__ == '__main__':
    app = create_app()
    host = app.config.get('FLASK_HOST', '127.0.0.1')
    port = app.config.get('FLASK_PORT', 5050)
    debug = app.config.get('FLASK_DEBUG', False)

    print(f"\n{'='*60}")
    print(f"🚀 BuscaPieza RD iniciando...")
    print(f"🌐 URL: http://{host}:{port}")
    print(f"📝 Modo: {'Desarrollo' if debug else 'Producción'}")
    print(f"{'='*60}\n")

    app.run(host=host, port=port, debug=debug)
