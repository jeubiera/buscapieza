"""
Tests para autenticación, registro y autorización
"""
from models import Usuario
from tests.conftest import PASSWORD, crear_usuario, login


def _registro(client, **override):
    data = {
        'nombre': 'Nuevo Usuario',
        'email': 'nuevo@test.com',
        'telefono': '809-999-9999',
        'password': 'NuevoPass123!',
        'password2': 'NuevoPass123!',
        'rol': 'cliente',
    }
    data.update(override)
    return client.post('/auth/registro', data=data)


class TestLogin:

    def test_login_page_loads(self, client):
        response = client.get('/auth/login')
        assert response.status_code == 200
        assert 'Iniciar'.encode() in response.data

    def test_login_successful(self, client, cliente_user):
        response = client.post('/auth/login', data={'email': 'cliente@test.com', 'password': PASSWORD})
        assert response.status_code == 302
        assert '/solicitudes/mis-solicitudes' in response.headers['Location']

    def test_login_wrong_password(self, client, cliente_user):
        response = client.post('/auth/login', data={'email': 'cliente@test.com', 'password': 'Mala123456'})
        assert response.status_code == 200
        assert 'incorrectos'.encode() in response.data

    def test_login_nonexistent_user(self, client):
        response = client.post('/auth/login', data={'email': 'noexiste@test.com', 'password': 'x' * 10})
        assert response.status_code == 200

    def test_login_usuario_inactivo(self, client):
        crear_usuario('inactivo@test.com', activo=False)
        response = client.post('/auth/login', data={'email': 'inactivo@test.com', 'password': PASSWORD})
        assert response.status_code == 200
        assert 'incorrectos'.encode() in response.data

    def test_login_no_redirige_a_otro_dominio(self, client, cliente_user):
        for malo in ['https://evil.com', '//evil.com', '/\\evil.com', 'javascript:alert(1)']:
            response = client.post(f'/auth/login?next={malo}',
                                   data={'email': 'cliente@test.com', 'password': PASSWORD})
            assert response.status_code == 302
            assert 'evil.com' not in response.headers['Location']
            client.get('/auth/logout')

    def test_login_respeta_next_interno(self, client, cliente_user):
        response = client.post('/auth/login?next=/solicitudes/nueva',
                               data={'email': 'cliente@test.com', 'password': PASSWORD})
        assert response.headers['Location'].endswith('/solicitudes/nueva')

    def test_logout(self, authenticated_client):
        response = authenticated_client.get('/auth/logout', follow_redirects=True)
        assert response.status_code == 200

    def test_sesion_de_usuario_desactivado_se_invalida(self, client, _db, cliente_user):
        login(client, cliente_user)
        assert client.get('/solicitudes/mis-solicitudes').status_code == 200
        cliente_user.activo = False
        _db.session.commit()
        assert client.get('/solicitudes/mis-solicitudes').status_code == 302


class TestRegistro:

    def test_registro_page_loads(self, client):
        response = client.get('/auth/registro')
        assert response.status_code == 200
        assert 'Crear Cuenta'.encode() in response.data

    def test_registro_successful(self, client):
        response = _registro(client)
        assert response.status_code == 302
        user = Usuario.query.filter_by(email='nuevo@test.com').first()
        assert user is not None
        assert user.rol == 'cliente'
        assert user.check_password('NuevoPass123!')

    def test_registro_passwords_dont_match(self, client):
        response = _registro(client, password2='Distinta123!')
        assert response.status_code == 400
        assert Usuario.query.filter_by(email='nuevo@test.com').first() is None

    def test_registro_password_corta(self, client):
        response = _registro(client, password='corta', password2='corta')
        assert response.status_code == 400
        assert Usuario.query.filter_by(email='nuevo@test.com').first() is None

    def test_registro_email_invalido(self, client):
        assert _registro(client, email='no-es-email').status_code == 400

    def test_registro_email_duplicado(self, client, cliente_user):
        response = _registro(client, email='cliente@test.com')
        assert response.status_code == 400
        assert Usuario.query.filter_by(email='cliente@test.com').count() == 1

    def test_registro_no_permite_crear_admin(self, client):
        response = _registro(client, rol='admin')
        assert response.status_code == 400
        assert Usuario.query.filter_by(email='nuevo@test.com').first() is None

    def test_registro_roles_validos(self, client):
        for rol in ['cliente', 'proveedor']:
            _registro(client, email=f'{rol}nuevo@test.com', rol=rol)
            client.get('/auth/logout')
            user = Usuario.query.filter_by(email=f'{rol}nuevo@test.com').first()
            assert user is not None and user.rol == rol

    def test_proveedor_nuevo_queda_pendiente_de_verificar(self, client):
        _registro(client, rol='proveedor', email='prov@test.com', empresa='Mi Negocio')
        user = Usuario.query.filter_by(email='prov@test.com').first()
        assert user.verificado is False
        assert user.empresa == 'Mi Negocio'


class TestCambiarPassword:

    def test_cambiar_password(self, authenticated_client, cliente_user):
        r = authenticated_client.post('/auth/cambiar-password', data={
            'actual': PASSWORD, 'password': 'OtraClave456!', 'password2': 'OtraClave456!'})
        assert r.status_code == 302
        assert cliente_user.check_password('OtraClave456!')

    def test_cambiar_password_actual_incorrecta(self, authenticated_client, cliente_user):
        authenticated_client.post('/auth/cambiar-password', data={
            'actual': 'incorrecta', 'password': 'OtraClave456!', 'password2': 'OtraClave456!'})
        assert cliente_user.check_password(PASSWORD)


class TestAutorizacion:

    def test_admin_puede_acceder_admin_panel(self, admin_authenticated_client):
        assert admin_authenticated_client.get('/admin/dashboard').status_code == 200

    def test_cliente_no_puede_acceder_admin_panel(self, authenticated_client):
        for ruta in ['/admin/dashboard', '/admin/configuracion', '/admin/solicitudes', '/admin/analytics']:
            response = authenticated_client.get(ruta)
            assert response.status_code == 302, ruta

    def test_cliente_no_puede_hacer_post_admin(self, authenticated_client, solicitud):
        authenticated_client.post(f'/admin/solicitud/{solicitud.id}/estado', data={'estado': 'cancelada'})
        assert solicitud.estado == 'pendiente'

    def test_usuario_no_autenticado_redirige_login(self, client):
        for route in ['/solicitudes/nueva', '/ofertas/mis-ofertas', '/admin/dashboard']:
            response = client.get(route)
            assert response.status_code == 302
            assert '/auth/login' in response.headers['Location']


class TestCSRF:

    def test_post_sin_token_csrf_es_rechazado(self, app, client, cliente_user):
        app.config['WTF_CSRF_ENABLED'] = True
        response = client.post('/auth/login', data={'email': 'cliente@test.com', 'password': PASSWORD})
        # Redirige con aviso y NO inicia sesión
        assert response.status_code == 302
        assert client.get('/solicitudes/mis-solicitudes').status_code == 302

    def test_formularios_incluyen_token(self, app, client):
        app.config['WTF_CSRF_ENABLED'] = True
        html = client.get('/auth/login').data
        assert b'name="csrf_token"' in html


class TestComandosCLI:

    def test_admin_password(self, runner):
        from models import Usuario
        r = runner.invoke(args=['admin-password'], input='NuevaClave789!\nNuevaClave789!\n')
        assert r.exit_code == 0, r.output
        admin = Usuario.query.filter_by(rol='admin').first()
        assert admin.check_password('NuevaClave789!')

    def test_admin_password_corta(self, runner):
        r = runner.invoke(args=['admin-password'], input='corta\ncorta\n')
        assert r.exit_code != 0

    def test_seed_es_idempotente(self, runner):
        from models import Provincia
        r = runner.invoke(args=['seed'])
        assert r.exit_code == 0  # el admin ya existía: no pide pausa
        assert Provincia.query.count() == 32
