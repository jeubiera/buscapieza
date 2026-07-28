"""
Configuración de pytest y fixtures compartidas
"""
import pytest
from app import create_app
from extensions import db
from models import Usuario, Categoria, Provincia


@pytest.fixture(scope='session')
def app():
    """
    Crea una instancia de la aplicación para testing
    """
    app = create_app('testing')
    return app


@pytest.fixture(scope='session')
def _db(app):
    """
    Crea y configura la base de datos para tests
    """
    with app.app_context():
        db.create_all()
        _seed_test_data()
        yield db
        db.session.remove()
        db.drop_all()


@pytest.fixture(scope='function')
def client(app, _db):
    """
    Cliente de testing Flask
    """
    return app.test_client()


@pytest.fixture(scope='function')
def runner(app):
    """
    CLI runner para tests
    """
    return app.test_cli_runner()


@pytest.fixture
def admin_user(_db):
    """
    Fixture que crea un usuario admin para tests
    """
    admin = Usuario(
        nombre='Admin Test',
        email='admin@test.com',
        telefono='8091234567',
        rol='admin',
        activo=True,
        verificado=True
    )
    admin.set_password('TestPassword123!')
    _db.session.add(admin)
    _db.session.commit()
    return admin


@pytest.fixture
def cliente_user(_db):
    """
    Fixture que crea un usuario cliente para tests
    """
    cliente = Usuario(
        nombre='Cliente Test',
        email='cliente@test.com',
        telefono='8091234568',
        rol='cliente',
        activo=True,
        verificado=True
    )
    cliente.set_password('TestPassword123!')
    _db.session.add(cliente)
    _db.session.commit()
    return cliente


@pytest.fixture
def proveedor_user(_db):
    """
    Fixture que crea un usuario proveedor para tests
    """
    proveedor = Usuario(
        nombre='Proveedor Test',
        email='proveedor@test.com',
        telefono='8091234569',
        rol='proveedor',
        activo=True,
        verificado=True
    )
    proveedor.set_password('TestPassword123!')
    _db.session.add(proveedor)
    _db.session.commit()
    return proveedor


@pytest.fixture
def authenticated_client(client, cliente_user):
    """
    Cliente autenticado como cliente
    """
    with client.session_transaction() as sess:
        sess['_user_id'] = str(cliente_user.id)
    return client


@pytest.fixture
def admin_authenticated_client(client, admin_user):
    """
    Cliente autenticado como admin
    """
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_user.id)
    return client


def _seed_test_data():
    """
    Crea datos de prueba en la base de datos
    """
    # Provincias
    if not Provincia.query.first():
        provincias = ['Santo Domingo', 'Santiago', 'La Vega', 'Puerto Plata']
        for p in provincias:
            db.session.add(Provincia(nombre=p))

    # Categorías
    if not Categoria.query.first():
        categorias = [
            ('Repuestos Automotrices', '🔧', '#FF6B35'),
            ('Electrónica & Electrodomésticos', '⚡', '#4ECDC4'),
            ('Ferretería & Construcción', '🏗️', '#F7DC6F'),
            ('Otros', '📦', '#90A4AE'),
        ]
        for nombre, icono, color in categorias:
            db.session.add(Categoria(nombre=nombre, icono=icono, color=color))

    db.session.commit()
