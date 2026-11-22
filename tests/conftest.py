"""
Configuración de pytest y fixtures compartidas.

Cada test recibe una app con una base SQLite en memoria nueva, así los tests
no se pisan entre sí (antes compartían BD y fallaban por emails duplicados).
"""
import os

os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-testing-only')
os.environ['FLASK_ENV'] = 'testing'

import pytest
from flask import g

from app import create_app
from extensions import db as _db_ext
from models import Usuario, Solicitud, Categoria, Provincia


@pytest.fixture
def app():
    app = create_app('testing')

    @app.before_request
    def _olvidar_usuario_cacheado():
        # El app context del fixture se reutiliza entre peticiones: sin esto
        # Flask-Login devolvería el usuario de la petición anterior.
        g.pop('_login_user', None)

    with app.app_context():
        yield app
        _db_ext.session.remove()
        _db_ext.drop_all()


@pytest.fixture
def _db(app):
    return _db_ext


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def runner(app):
    return app.test_cli_runner()


PASSWORD = 'TestPassword123!'


def crear_usuario(email, rol='cliente', verificado=True, activo=True, **extra):
    u = Usuario(
        nombre=extra.pop('nombre', f'{rol.title()} Test'),
        email=email,
        telefono=extra.pop('telefono', '8091234567'),
        rol=rol, activo=activo, verificado=verificado, **extra
    )
    u.set_password(PASSWORD)
    _db_ext.session.add(u)
    _db_ext.session.commit()
    return u


def crear_solicitud(cliente, **campos):
    sol = Solicitud(
        cliente_id=cliente.id,
        categoria_id=Categoria.query.first().id,
        provincia_id=Provincia.query.first().id,
        titulo=campos.pop('titulo', 'Busco alternador'),
        descripcion=campos.pop('descripcion', 'Alternador Toyota Corolla 2015'),
        **campos
    )
    _db_ext.session.add(sol)
    _db_ext.session.flush()
    sol.generar_codigo()
    _db_ext.session.commit()
    return sol


def login(client, user):
    with client.session_transaction() as sess:
        sess.clear()            # como un navegador distinto: sin mensajes ni datos del usuario anterior
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
    return client


@pytest.fixture
def admin_user(_db):
    return crear_usuario('admin@test.com', rol='admin')


@pytest.fixture
def cliente_user(_db):
    return crear_usuario('cliente@test.com', rol='cliente')


@pytest.fixture
def proveedor_user(_db):
    return crear_usuario('proveedor@test.com', rol='proveedor', empresa='Repuestos Test')


@pytest.fixture
def solicitud(cliente_user):
    return crear_solicitud(cliente_user)


@pytest.fixture
def authenticated_client(client, cliente_user):
    return login(client, cliente_user)


@pytest.fixture
def admin_authenticated_client(client, admin_user):
    return login(client, admin_user)


@pytest.fixture
def proveedor_client(client, proveedor_user):
    return login(client, proveedor_user)
