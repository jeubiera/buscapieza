"""
Tests para modelos de datos
"""
import pytest
from models import Usuario, Solicitud, Oferta, Categoria, Provincia
from extensions import db


class TestUsuario:
    """Tests para el modelo Usuario"""

    def test_crear_usuario(self, _db):
        """Test: Crear un usuario básico"""
        user = Usuario(
            nombre='Test User',
            email='test@example.com',
            telefono='8091234567',
            rol='cliente'
        )
        user.set_password('password123')
        _db.session.add(user)
        _db.session.commit()

        assert user.id is not None
        assert user.email == 'test@example.com'
        assert user.check_password('password123')
        assert not user.check_password('wrongpassword')

    def test_password_hashing(self, _db):
        """Test: La contraseña se hashea correctamente"""
        user = Usuario(
            nombre='Test User',
            email='hash@test.com',
            telefono='8091111111',
            rol='cliente'
        )
        user.set_password('mysecretpassword')
        _db.session.add(user)
        _db.session.commit()

        # La contraseña no se guarda en texto plano
        assert user.password_hash != 'mysecretpassword'
        # Pero se puede verificar
        assert user.check_password('mysecretpassword')

    def test_roles_validos(self, _db):
        """Test: Solo se aceptan roles válidos"""
        for rol in ['cliente', 'proveedor', 'admin']:
            user = Usuario(
                nombre=f'User {rol}',
                email=f'{rol}@test.com',
                telefono=f'80911111{ord(rol[0])}',
                rol=rol
            )
            user.set_password('pass123')
            _db.session.add(user)

        _db.session.commit()
        assert Usuario.query.count() >= 3

    def test_email_unico(self, _db):
        """Test: El email debe ser único"""
        user1 = Usuario(
            nombre='User 1',
            email='duplicate@test.com',
            telefono='8091111111',
            rol='cliente'
        )
        user1.set_password('pass123')
        _db.session.add(user1)
        _db.session.commit()

        user2 = Usuario(
            nombre='User 2',
            email='duplicate@test.com',  # Email duplicado
            telefono='8091111112',
            rol='cliente'
        )
        user2.set_password('pass123')
        _db.session.add(user2)

        with pytest.raises(Exception):
            _db.session.commit()
        _db.session.rollback()


class TestSolicitud:
    """Tests para el modelo Solicitud"""

    def test_crear_solicitud(self, _db, cliente_user):
        """Test: Crear una solicitud básica"""
        categoria = Categoria.query.first()
        provincia = Provincia.query.first()

        solicitud = Solicitud(
            titulo='Busco alternador Toyota',
            descripcion='Necesito alternador para Corolla 2015',
            categoria_id=categoria.id,
            provincia_id=provincia.id,
            presupuesto=5000.00,
            usuario_id=cliente_user.id
        )
        _db.session.add(solicitud)
        _db.session.commit()

        assert solicitud.id is not None
        assert solicitud.codigo is not None
        assert solicitud.codigo.startswith('BP-')
        assert solicitud.estado == 'pendiente'

    def test_generar_codigo_unico(self, _db, cliente_user):
        """Test: Cada solicitud tiene un código único"""
        categoria = Categoria.query.first()
        provincia = Provincia.query.first()

        sol1 = Solicitud(
            titulo='Solicitud 1',
            descripcion='Desc 1',
            categoria_id=categoria.id,
            provincia_id=provincia.id,
            usuario_id=cliente_user.id
        )
        sol2 = Solicitud(
            titulo='Solicitud 2',
            descripcion='Desc 2',
            categoria_id=categoria.id,
            provincia_id=provincia.id,
            usuario_id=cliente_user.id
        )

        _db.session.add(sol1)
        _db.session.add(sol2)
        _db.session.commit()

        assert sol1.codigo != sol2.codigo


class TestOferta:
    """Tests para el modelo Oferta"""

    def test_crear_oferta(self, _db, cliente_user, proveedor_user):
        """Test: Crear una oferta básica"""
        categoria = Categoria.query.first()
        provincia = Provincia.query.first()

        solicitud = Solicitud(
            titulo='Busco pieza',
            descripcion='Descripción',
            categoria_id=categoria.id,
            provincia_id=provincia.id,
            usuario_id=cliente_user.id
        )
        _db.session.add(solicitud)
        _db.session.commit()

        oferta = Oferta(
            solicitud_id=solicitud.id,
            proveedor_id=proveedor_user.id,
            precio=1500.00,
            tiempo_entrega='2-3 días',
            incluye_envio=True,
            comentario='Tengo la pieza disponible'
        )
        _db.session.add(oferta)
        _db.session.commit()

        assert oferta.id is not None
        assert oferta.precio == 1500.00
        assert oferta.estado == 'pendiente'


class TestCategoria:
    """Tests para el modelo Categoria"""

    def test_categorias_existen(self, _db):
        """Test: Las categorías de seed existen"""
        categorias = Categoria.query.all()
        assert len(categorias) > 0

    def test_categoria_tiene_campos_requeridos(self, _db):
        """Test: Categoría tiene todos los campos"""
        cat = Categoria.query.first()
        assert cat.nombre is not None
        assert cat.icono is not None
        assert cat.color is not None


class TestProvincia:
    """Tests para el modelo Provincia"""

    def test_provincias_existen(self, _db):
        """Test: Las provincias de seed existen"""
        provincias = Provincia.query.all()
        assert len(provincias) > 0

    def test_provincia_nombre_unico(self, _db):
        """Test: El nombre de provincia debe ser único"""
        prov1 = Provincia(nombre='Provincia Test')
        _db.session.add(prov1)
        _db.session.commit()

        prov2 = Provincia(nombre='Provincia Test')  # Duplicado
        _db.session.add(prov2)

        with pytest.raises(Exception):
            _db.session.commit()
        _db.session.rollback()
