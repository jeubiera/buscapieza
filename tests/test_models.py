"""
Tests para modelos de datos
"""
from decimal import Decimal

import pytest
from models import Usuario, Oferta, Categoria, Provincia, Transaccion, Rating
from tests.conftest import crear_usuario, crear_solicitud


class TestUsuario:

    def test_crear_usuario(self, _db):
        user = crear_usuario('test@example.com')
        assert user.id is not None
        assert user.check_password('TestPassword123!')
        assert not user.check_password('wrongpassword')

    def test_password_no_en_texto_plano(self, _db):
        user = crear_usuario('hash@test.com')
        assert 'TestPassword123!' not in user.password_hash

    def test_email_unico(self, _db):
        crear_usuario('duplicate@test.com')
        with pytest.raises(Exception):
            crear_usuario('duplicate@test.com')
        _db.session.rollback()


class TestSolicitud:

    def test_crear_solicitud_genera_codigo(self, cliente_user):
        sol = crear_solicitud(cliente_user)
        assert sol.codigo == f"BP-{sol.created_at.year}-{sol.id:04d}"
        assert sol.estado == 'pendiente'

    def test_generar_codigo_unico(self, cliente_user):
        s1 = crear_solicitud(cliente_user, titulo='Solicitud 1')
        s2 = crear_solicitud(cliente_user, titulo='Solicitud 2')
        assert s1.codigo != s2.codigo


class TestOferta:

    def test_calcular_precio_cliente(self, _db, solicitud, proveedor_user):
        oferta = Oferta(solicitud_id=solicitud.id, proveedor_id=proveedor_user.id, precio=Decimal('1500.00'))
        _db.session.add(oferta)
        _db.session.commit()
        assert oferta.estado == 'nueva'
        oferta.calcular_precio_cliente(Decimal('15'))
        assert oferta.margen_broker == Decimal('225.00')
        assert oferta.precio_cliente == Decimal('1725.00')

    def test_redondeo_a_centavos(self, _db, solicitud, proveedor_user):
        oferta = Oferta(solicitud_id=solicitud.id, proveedor_id=proveedor_user.id, precio=Decimal('999.99'))
        oferta.calcular_precio_cliente(Decimal('12.5'))
        assert oferta.margen_broker == Decimal('125.00')


class TestTransaccionYRating:

    def test_comision_y_rating(self, _db, solicitud, proveedor_user, cliente_user):
        oferta = Oferta(solicitud_id=solicitud.id, proveedor_id=proveedor_user.id, precio=Decimal('1000'))
        _db.session.add(oferta)
        _db.session.flush()
        t = Transaccion(solicitud_id=solicitud.id, oferta_id=oferta.id, cliente_id=cliente_user.id,
                        proveedor_id=proveedor_user.id, precio_proveedor=Decimal('1000'),
                        precio_cliente=Decimal('1200'), comision_broker=0, estado_pago='pagado')
        t.calcular_comision()
        _db.session.add(t)
        _db.session.flush()
        assert t.comision_broker == Decimal('200')
        assert t.porcentaje_comision == Decimal('20.00')

        r = Rating(transaccion_id=t.id, proveedor_id=proveedor_user.id, cliente_id=cliente_user.id,
                   calidad_producto=5, tiempo_entrega=4, atencion_cliente=5, precio_justo=4)
        r.calcular_promedio()
        _db.session.add(r)
        _db.session.commit()
        assert r.calificacion_general == 5  # 4.5 redondea hacia arriba
        assert proveedor_user.rating_promedio() == 5.0
        assert proveedor_user.total_transacciones() == 1
        assert solicitud.transaccion_activa() == t


class TestSeed:

    def test_categorias_y_provincias(self, _db):
        assert Categoria.query.count() == 10
        assert Provincia.query.count() == 32
        cat = Categoria.query.first()
        assert cat.nombre and cat.icono and cat.color

    def test_admin_inicial_sin_password_por_defecto(self, _db):
        admin = Usuario.query.filter_by(rol='admin').first()
        assert admin is not None
        assert not admin.check_password('Admin2024!')


class TestConfigBD:

    def test_url_postgres_de_hosting_se_normaliza(self, monkeypatch):
        import config
        monkeypatch.setenv('DATABASE_URL', 'postgres://u:p@host:5432/db')
        assert config._database_url() == 'postgresql+psycopg2://u:p@host:5432/db'
        monkeypatch.setenv('DATABASE_URL', 'postgresql://u:p@host/db')
        assert config._database_url() == 'postgresql+psycopg2://u:p@host/db'
