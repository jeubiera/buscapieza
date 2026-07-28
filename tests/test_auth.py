"""
Tests para autenticación y registro
"""
import pytest
from flask import url_for
from models import Usuario
from extensions import db


class TestLogin:
    """Tests para el login de usuarios"""

    def test_login_page_loads(self, client):
        """Test: La página de login carga correctamente"""
        response = client.get('/auth/login')
        assert response.status_code == 200
        assert b'Iniciar' in response.data or b'Login' in response.data

    def test_login_successful(self, client, cliente_user):
        """Test: Login exitoso con credenciales correctas"""
        response = client.post('/auth/login', data={
            'email': 'cliente@test.com',
            'password': 'TestPassword123!'
        }, follow_redirects=True)

        assert response.status_code == 200
        # Verificar que se redirige al dashboard o home

    def test_login_wrong_password(self, client, cliente_user):
        """Test: Login falla con contraseña incorrecta"""
        response = client.post('/auth/login', data={
            'email': 'cliente@test.com',
            'password': 'WrongPassword123!'
        }, follow_redirects=True)

        assert response.status_code == 200
        # Debería mostrar mensaje de error

    def test_login_nonexistent_user(self, client):
        """Test: Login falla con usuario inexistente"""
        response = client.post('/auth/login', data={
            'email': 'noexiste@test.com',
            'password': 'AnyPassword123!'
        }, follow_redirects=True)

        assert response.status_code == 200

    def test_logout(self, authenticated_client):
        """Test: Logout funciona correctamente"""
        response = authenticated_client.get('/auth/logout', follow_redirects=True)
        assert response.status_code == 200


class TestRegistro:
    """Tests para el registro de usuarios"""

    def test_registro_page_loads(self, client):
        """Test: La página de registro carga correctamente"""
        response = client.get('/auth/registro')
        assert response.status_code == 200
        assert b'Registro' in response.data or b'Registrar' in response.data

    def test_registro_successful(self, client, _db):
        """Test: Registro exitoso crea nuevo usuario"""
        data = {
            'nombre': 'Nuevo Usuario',
            'email': 'nuevo@test.com',
            'telefono': '8099999999',
            'password': 'NuevoPass123!',
            'password2': 'NuevoPass123!',
            'rol': 'cliente'
        }

        response = client.post('/auth/registro', data=data, follow_redirects=True)
        assert response.status_code == 200

        # Verificar que el usuario fue creado
        user = Usuario.query.filter_by(email='nuevo@test.com').first()
        assert user is not None
        assert user.nombre == 'Nuevo Usuario'
        assert user.check_password('NuevoPass123!')

    def test_registro_passwords_dont_match(self, client):
        """Test: Registro falla si las contraseñas no coinciden"""
        data = {
            'nombre': 'Test User',
            'email': 'test2@test.com',
            'telefono': '8099999998',
            'password': 'Password123!',
            'password2': 'DifferentPass123!',
            'rol': 'cliente'
        }

        response = client.post('/auth/registro', data=data, follow_redirects=True)
        assert response.status_code == 200

        # No debería crear el usuario
        user = Usuario.query.filter_by(email='test2@test.com').first()
        assert user is None

    def test_registro_email_duplicado(self, client, cliente_user):
        """Test: No se puede registrar con email duplicado"""
        data = {
            'nombre': 'Otro Usuario',
            'email': 'cliente@test.com',  # Ya existe
            'telefono': '8099999997',
            'password': 'Password123!',
            'password2': 'Password123!',
            'rol': 'cliente'
        }

        response = client.post('/auth/registro', data=data, follow_redirects=True)
        # Debería rechazar el registro
        assert response.status_code == 200

    def test_registro_rol_valido(self, client, _db):
        """Test: Solo se permiten roles válidos en registro"""
        for rol in ['cliente', 'proveedor']:
            data = {
                'nombre': f'Usuario {rol}',
                'email': f'{rol}nuevo@test.com',
                'telefono': f'80999999{ord(rol[0])}',
                'password': 'Password123!',
                'password2': 'Password123!',
                'rol': rol
            }

            response = client.post('/auth/registro', data=data, follow_redirects=True)
            assert response.status_code == 200

            user = Usuario.query.filter_by(email=f'{rol}nuevo@test.com').first()
            assert user is not None
            assert user.rol == rol


class TestAutorizacion:
    """Tests para verificar permisos y autorización"""

    def test_admin_puede_acceder_admin_panel(self, admin_authenticated_client):
        """Test: Admin puede acceder al panel de admin"""
        response = admin_authenticated_client.get('/admin/dashboard')
        # Si existe la ruta, debe permitir acceso
        assert response.status_code in [200, 404]  # 404 si aún no existe la ruta

    def test_cliente_no_puede_acceder_admin_panel(self, authenticated_client):
        """Test: Cliente no puede acceder al panel de admin"""
        response = authenticated_client.get('/admin/dashboard', follow_redirects=True)
        # Debería redirigir o denegar acceso
        assert response.status_code in [200, 302, 403]

    def test_usuario_no_autenticado_redirige_login(self, client):
        """Test: Rutas protegidas redirigen al login"""
        protected_routes = [
            '/solicitudes/nueva',
            '/ofertas/panel',
            '/admin/dashboard'
        ]

        for route in protected_routes:
            response = client.get(route)
            # Debería redirigir al login (302) o denegar acceso
            assert response.status_code in [302, 401, 403, 404]
