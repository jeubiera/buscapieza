import os
import secrets
import sys
import time

# En consolas Windows sin UTF-8 (o con salida redirigida) un emoji no debe tumbar la app
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors='replace')
    except (AttributeError, ValueError):
        pass

from dotenv import load_dotenv

# IMPORTANTE: Cargar .env ANTES de importar config
load_dotenv()

from flask import Flask, request, g, flash, redirect, url_for
from flask_wtf.csrf import CSRFError

from extensions import db, login_manager, migrate, csrf
from config import config, validar_configuracion
from logging_config import configurar_logging


def create_app(config_name=None):
    """
    Factory pattern para crear la aplicación Flask

    Args:
        config_name: 'development', 'production', 'testing' o None (usa FLASK_ENV)
    """
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'development')

    app = Flask(__name__)
    app.config.from_object(config.get(config_name, config['default']))

    if not app.config.get('SECRET_KEY'):
        raise RuntimeError(
            "SECRET_KEY no está configurada. Genera una con: "
            "python -c \"import secrets; print(secrets.token_hex(32))\" y ponla en .env"
        )
    if config_name == 'production' and (
            len(app.config['SECRET_KEY']) < 32
            or app.config['SECRET_KEY'] in ('buscapieza-broker-secret-2024',
                                            'cambia-esto-por-una-clave-aleatoria-de-64-caracteres')):
        raise RuntimeError("SECRET_KEY de producción demasiado débil o de ejemplo: genera una nueva")

    # Configurar logging
    configurar_logging(app)

    # Inicializar extensiones
    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view     = 'auth.login'
    login_manager.login_message  = 'Debes iniciar sesión para continuar'
    login_manager.login_message_category = 'info'

    # Registrar blueprints
    from blueprints.main       import main_bp
    from blueprints.auth       import auth_bp
    from blueprints.solicitudes import sol_bp
    from blueprints.ofertas    import oferta_bp
    from blueprints.admin      import admin_bp
    from blueprints.ventas     import ventas_bp
    from blueprints.pagos      import pagos_bp
    from blueprints.referidos  import referidos_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp,    url_prefix='/auth')
    app.register_blueprint(sol_bp,     url_prefix='/solicitudes')
    app.register_blueprint(oferta_bp,  url_prefix='/ofertas')
    app.register_blueprint(admin_bp,   url_prefix='/admin')
    app.register_blueprint(ventas_bp)
    app.register_blueprint(pagos_bp,   url_prefix='/pagos')
    app.register_blueprint(referidos_bp)

    os.makedirs(os.path.join(app.root_path, app.config['UPLOAD_FOLDER']), exist_ok=True)

    if app.config.get('AUTO_CREATE_DB'):
        from sqlalchemy.exc import OperationalError
        with app.app_context():
            try:
                db.create_all()
            except OperationalError as e:
                raise RuntimeError(
                    "No se pudo conectar a la base de datos.\n"
                    f"  URL: {db.engine.url.render_as_string(hide_password=True)}\n"
                    "  ¿Está PostgreSQL en ejecución y son correctos usuario, contraseña y nombre de la BD "
                    "en DATABASE_URL (.env)?\n"
                    f"  Detalle: {e.orig}"
                ) from None
            seed_datos(app)

    # Claves guardadas desde el panel admin (tienen prioridad sobre el .env)
    from services.config_svc import cargar_config_bd
    cargar_config_bd(app)

    if not app.testing:
        validar_configuracion(app)

    _registrar_cli(app)
    _registrar_hooks(app)
    return app


def _version_estaticos(app):
    """Versión para las URL de CSS/JS: cambia cuando cambian los archivos (evita cachés viejas)."""
    marcas = []
    for rel in ('static/css/main.css', 'static/js/main.js'):
        try:
            marcas.append(int(os.path.getmtime(os.path.join(app.root_path, rel))))
        except OSError:
            pass
    return str(max(marcas)) if marcas else '1'


def _registrar_hooks(app):
    asset_v = _version_estaticos(app)

    @app.context_processor
    def inyectar_globales():
        import json
        from services.whatsapp_svc import _limpiar_numero
        web_cfg = app.config.get('FIREBASE_WEB_CONFIG') or ''
        try:
            web_cfg = json.loads(web_cfg) if web_cfg else None
        except ValueError:
            web_cfg = None
        return {
            'broker_wa': _limpiar_numero(app.config.get('BROKER_WHATSAPP', '') or ''),
            'broker_nombre': app.config.get('BROKER_NOMBRE', 'BuscatodoRD'),
            'firebase_web_config': web_cfg if app.config.get('FIREBASE_VAPID_PUBLIC') else None,
            'firebase_vapid': app.config.get('FIREBASE_VAPID_PUBLIC', ''),
            'asset_v': asset_v,
        }

    # Middleware para logging de requests
    @app.before_request
    def before_request():
        g.start_time = time.time()

    @app.before_request
    def capturar_referido():
        """Enlaces https://.../?ref=CODIGO: se recuerda el código hasta que la persona se registre."""
        from flask import session
        from flask_login import current_user
        ref = request.args.get('ref')
        if ref and not current_user.is_authenticated:
            session['ref'] = ref.strip().upper()[:12]

    @app.after_request
    def after_request(response):
        # Cabeceras básicas de seguridad
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
        response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')

        if hasattr(g, 'start_time'):
            elapsed = time.time() - g.start_time
            response.headers['X-Response-Time'] = f'{elapsed:.3f}s'
            if app.config.get('FLASK_DEBUG') or response.status_code >= 400:
                app.logger.info(
                    f'{request.remote_addr} - "{request.method} {request.path}" '
                    f'{response.status_code} - {elapsed:.3f}s'
                )
        return response

    @app.errorhandler(CSRFError)
    def csrf_error(error):
        app.logger.warning(f'CSRF rechazado: {request.path} — {error.description}')
        if request.is_json or request.path.endswith('push-token'):
            return {'ok': False, 'msg': 'Sesión expirada, recarga la página'}, 400
        flash('La sesión del formulario expiró. Vuelve a intentarlo.', 'warning')
        return redirect(request.referrer or url_for('main.index'))

    @app.errorhandler(413)
    def demasiado_grande(error):
        flash('Los archivos son demasiado grandes (máximo 20 MB en total).', 'danger')
        return redirect(request.referrer or url_for('main.index'))

    @app.errorhandler(404)
    def not_found(error):
        app.logger.warning(f'404 Not Found: {request.url}')
        return "Página no encontrada", 404

    @app.errorhandler(500)
    def internal_error(error):
        app.logger.error(f'500 Internal Error: {error}', exc_info=True)
        db.session.rollback()
        return "Error interno del servidor", 500


def _registrar_cli(app):
    import click

    @app.cli.command('seed')
    def seed_cmd():
        """Carga provincias, categorías, configuración y el admin inicial."""
        creado = seed_datos(app)
        print('✅ Datos iniciales cargados')
        # Código 3 = se acaba de generar la contraseña del admin (iniciar.bat hace pausa)
        if creado:
            sys.exit(3)

    @app.cli.command('cerrar-referidos')
    @click.option('--periodo', default=None, help='AAAA-MM (por defecto, el mes pasado)')
    def cerrar_referidos_cmd(periodo):
        """Cierre mensual del programa de referidos (para programarlo el día 1 de cada mes)."""
        from services import referidos as ref
        periodo = periodo or ref.ultimo_periodo_cerrable()
        try:
            c = ref.cerrar_periodo(periodo)
            db.session.commit()
            click.echo(f'Periodo {periodo}: {c.disponibles} disponibles, {c.acumuladas} acumuladas, {c.vencidas} vencidas')
        except ref.ErrorReferidos as e:
            db.session.rollback()
            click.echo(str(e))

    @app.cli.command('admin-password')
    @click.option('--email', default=None, help='Email del admin (por defecto, el primero que exista)')
    def admin_password_cmd(email):
        """Establece una nueva contraseña para un usuario admin (se escribe oculta)."""
        from models import Usuario
        from blueprints.auth import validar_password
        q = Usuario.query.filter_by(rol='admin')
        admin = q.filter_by(email=email.lower().strip()).first() if email else q.order_by(Usuario.id).first()
        if not admin:
            raise click.ClickException('No se encontró ningún admin. Ejecuta primero: flask seed')
        click.echo(f'Admin: {admin.email}')
        nueva = click.prompt('Nueva contraseña', hide_input=True, confirmation_prompt='Repite la contraseña')
        error = validar_password(nueva, None)
        if error:
            raise click.ClickException(error)
        admin.set_password(nueva)
        admin.activo = True
        db.session.commit()
        click.echo('✅ Contraseña actualizada. Ya puedes entrar en /auth/login')


def seed_datos(app):
    from models import Categoria, Provincia, Usuario, Configuracion
    if not Provincia.query.first():
        for p in [
            'Santo Domingo','Distrito Nacional','Santiago','La Vega','San Pedro de Macorís',
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

    admin_generado = False
    if not Usuario.query.filter_by(rol='admin').first():
        password = app.config.get('ADMIN_PASSWORD') or ''
        generada = not password
        if generada:
            password = secrets.token_urlsafe(12)
        admin = Usuario(
            nombre='Admin BuscatodoRD', email=app.config.get('ADMIN_EMAIL', 'admin@buscatodo.com.do').lower(),
            telefono='8090000000', rol='admin', activo=True, verificado=True
        )
        admin.set_password(password)
        db.session.add(admin)
        if generada and not app.testing:
            admin_generado = True
            # La contraseña solo se muestra en consola, nunca en los archivos de log
            app.logger.warning(f"Admin inicial creado ({admin.email}) con contraseña generada; "
                               f"se mostró en la consola. Cámbiala en /auth/cambiar-password")
            print(f"\n{'='*60}\n"
                  f"  ADMIN INICIAL CREADO (se muestra UNA sola vez)\n"
                  f"  Email:      {admin.email}\n"
                  f"  Contraseña: {password}\n"
                  f"  Cámbiala en /auth/cambiar-password\n"
                  f"{'='*60}\n", flush=True)

    # Configuraciones de comisiones y sistema
    existentes = {c.clave for c in Configuracion.query.all()}
    for clave, valor in [
        ('comision_default', '15.00'),  # % de comisión por defecto
        ('comision_minima', '5.00'),    # % mínimo de comisión
        ('comision_maxima', '30.00'),   # % máximo de comisión
        ('moneda', 'RD$'),              # Moneda del sistema
        ('itbis_porcentaje', '0'),      # % de ITBIS en pagos en línea (0 hasta confirmar con el contador)
    ]:
        if clave not in existentes:
            db.session.add(Configuracion(clave=clave, valor=valor))

    from services.pagos import sembrar_planes
    sembrar_planes()

    db.session.commit()
    return admin_generado


@login_manager.user_loader
def load_user(uid):
    from models import Usuario
    try:
        user = db.session.get(Usuario, int(uid))
    except (TypeError, ValueError):
        return None
    # Un usuario desactivado pierde la sesión inmediatamente
    return user if user and user.activo else None


if __name__ == '__main__':
    app = create_app()
    host = app.config.get('FLASK_HOST', '127.0.0.1')
    port = app.config.get('FLASK_PORT', 5050)
    debug = app.config.get('FLASK_DEBUG', False)

    print(f"\n{'='*60}")
    print(f"🚀 BuscatodoRD iniciando...")
    print(f"🌐 URL: http://{host}:{port}")
    print(f"📝 Modo: {'Desarrollo' if debug else 'Producción'}")
    print(f"{'='*60}\n")

    app.run(host=host, port=port, debug=debug)
