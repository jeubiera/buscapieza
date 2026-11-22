"""
Tests del flujo del broker: ofertas → aceptación con comisión → pago → calificación,
configuración cifrada y páginas de administración.
"""
from decimal import Decimal

from models import Oferta, Transaccion, Rating, Configuracion, PushToken
from tests.conftest import crear_usuario, crear_solicitud, login


def _ofertar(client, sid, precio='1000', tiempo='1-2 días'):
    return client.post(f'/ofertas/hacer/{sid}', data={
        'precio': precio, 'tiempo_entrega': tiempo, 'descripcion': 'Original', 'incluye_envio': 'on'})


class TestOfertas:

    def test_proveedor_verificado_oferta(self, proveedor_client, solicitud, proveedor_user):
        assert _ofertar(proveedor_client, solicitud.id).status_code == 302
        oferta = Oferta.query.one()
        assert oferta.precio == Decimal('1000.00')
        assert oferta.incluye_envio is True

    def test_proveedor_no_verificado_no_oferta(self, client, solicitud):
        prov = crear_usuario('pend@test.com', rol='proveedor', verificado=False)
        login(client, prov)
        _ofertar(client, solicitud.id)
        assert Oferta.query.count() == 0

    def test_precio_invalido(self, proveedor_client, solicitud):
        for malo in ['abc', '0', '-5', '']:
            assert _ofertar(proveedor_client, solicitud.id, precio=malo).status_code == 400
        assert Oferta.query.count() == 0

    def test_tiempo_entrega_invalido(self, proveedor_client, solicitud):
        assert _ofertar(proveedor_client, solicitud.id, tiempo='mañana tal vez').status_code == 400

    def test_no_oferta_en_solicitud_cerrada(self, proveedor_client, cliente_user):
        sol = crear_solicitud(cliente_user, estado='cancelada')
        _ofertar(proveedor_client, sol.id)
        assert Oferta.query.count() == 0

    def test_una_oferta_por_proveedor(self, proveedor_client, solicitud):
        _ofertar(proveedor_client, solicitud.id)
        _ofertar(proveedor_client, solicitud.id, precio='900')
        assert Oferta.query.count() == 1

    def test_cliente_no_puede_ofertar(self, authenticated_client, solicitud):
        _ofertar(authenticated_client, solicitud.id)
        assert Oferta.query.count() == 0

    def test_panel_proveedor(self, proveedor_client, solicitud):
        r = proveedor_client.get('/ofertas/mis-ofertas')
        assert r.status_code == 200
        assert solicitud.titulo.encode() in r.data


class TestFlujoBroker:

    def _preparar(self, client, solicitud, proveedor_user, admin_user):
        login(client, proveedor_user)
        _ofertar(client, solicitud.id, precio='1000')
        otro = crear_usuario('prov2@test.com', rol='proveedor')
        login(client, otro)
        _ofertar(client, solicitud.id, precio='1200')
        login(client, admin_user)
        return Oferta.query.filter_by(proveedor_id=proveedor_user.id).one()

    def test_aceptar_pagar_calificar(self, client, solicitud, proveedor_user, admin_user, cliente_user):
        oferta = self._preparar(client, solicitud, proveedor_user, admin_user)

        assert client.get(f'/admin/solicitud/{solicitud.id}').status_code == 200
        client.post(f'/admin/oferta/{oferta.id}/aceptar', data={'porcentaje': '20'})

        trans = Transaccion.query.one()
        assert trans.precio_proveedor == Decimal('1000.00')
        assert trans.precio_cliente == Decimal('1200.00')
        assert trans.comision_broker == Decimal('200.00')
        assert trans.estado_pago == 'pendiente'
        assert oferta.estado == 'aceptada'
        assert Oferta.query.filter_by(estado='rechazada').count() == 1
        assert solicitud.estado == 'en_gestion'
        assert not solicitud.acepta_ofertas

        # No se puede aceptar una segunda oferta
        otra = Oferta.query.filter(Oferta.id != oferta.id).one()
        client.post(f'/admin/oferta/{otra.id}/aceptar', data={'porcentaje': '15'})
        assert Transaccion.query.count() == 1

        # El cliente ve el precio
        login(client, cliente_user)
        assert b'1,200.00' in client.get(f'/solicitudes/{solicitud.id}').data
        # No puede calificar todavía
        client.post(f'/solicitudes/{solicitud.id}/calificar', data={
            'calidad_producto': 5, 'tiempo_entrega': 5, 'atencion_cliente': 5, 'precio_justo': 5})
        assert Rating.query.count() == 0

        login(client, admin_user)
        client.post(f'/admin/transaccion/{trans.id}/pagar', data={'metodo_pago': 'transferencia'})
        assert trans.estado_pago == 'pagado'
        assert trans.metodo_pago == 'transferencia'
        assert solicitud.estado == 'completada'

        r = client.get('/admin/dashboard')
        assert r.status_code == 200
        assert b'RD$200' in r.data

        login(client, cliente_user)
        client.post(f'/solicitudes/{solicitud.id}/calificar', data={
            'calidad_producto': 5, 'tiempo_entrega': 4, 'atencion_cliente': 5, 'precio_justo': 5,
            'comentario': 'Excelente'})
        rating = Rating.query.one()
        assert rating.proveedor_id == proveedor_user.id
        assert rating.calificacion_general == 5
        # Solo una calificación por compra
        client.post(f'/solicitudes/{solicitud.id}/calificar', data={
            'calidad_producto': 1, 'tiempo_entrega': 1, 'atencion_cliente': 1, 'precio_justo': 1})
        assert Rating.query.count() == 1

        login(client, admin_user)
        client.post(f'/admin/rating/{rating.id}/visibilidad')
        assert rating.visible is False

    def test_comision_fuera_de_rango(self, client, solicitud, proveedor_user, admin_user):
        oferta = self._preparar(client, solicitud, proveedor_user, admin_user)
        client.post(f'/admin/oferta/{oferta.id}/aceptar', data={'porcentaje': '90'})
        assert Transaccion.query.count() == 0

    def test_cancelar_venta_reabre(self, client, solicitud, proveedor_user, admin_user):
        oferta = self._preparar(client, solicitud, proveedor_user, admin_user)
        client.post(f'/admin/oferta/{oferta.id}/aceptar', data={})
        trans = Transaccion.query.one()
        assert trans.porcentaje_comision == Decimal('15.00')
        client.post(f'/admin/transaccion/{trans.id}/cancelar')
        assert trans.estado_pago == 'cancelado'
        assert oferta.estado == 'vista'
        assert solicitud.acepta_ofertas

    def test_notificar_proveedores_sin_whatsapp_configurado(self, admin_authenticated_client, solicitud):
        r = admin_authenticated_client.post(f'/admin/notificar-proveedores/{solicitud.id}')
        assert r.status_code == 302
        assert solicitud.estado == 'en_gestion'


class TestAdminPaginas:

    def test_paginas_cargan(self, admin_authenticated_client, solicitud, proveedor_user):
        for ruta in ['/admin/dashboard', '/admin/solicitudes', '/admin/solicitudes?estado=pendiente',
                     '/admin/clientes', '/admin/proveedores', '/admin/transacciones',
                     '/admin/analytics', '/admin/notificaciones', '/admin/configuracion']:
            assert admin_authenticated_client.get(ruta).status_code == 200, ruta

    def test_verificar_proveedor(self, admin_authenticated_client):
        prov = crear_usuario('pend@test.com', rol='proveedor', verificado=False)
        admin_authenticated_client.post(f'/admin/proveedor/{prov.id}/toggle', data={'accion': 'verificar'})
        assert prov.verificado and prov.activo
        admin_authenticated_client.post(f'/admin/proveedor/{prov.id}/toggle', data={'accion': 'desactivar'})
        assert not prov.activo


class TestConfiguracion:

    def _guardar(self, client, **campos):
        data = {'comision_default': '15', 'comision_minima': '5', 'comision_maxima': '30',
                'GREEN_API_INSTANCE': '123', 'GREEN_API_TOKEN': '', 'BROKER_WHATSAPP': '18095550000',
                'BROKER_NOMBRE': 'BuscaPieza RD', 'APP_URL': 'https://buscapieza.do/'}
        data.update(campos)
        return client.post('/admin/configuracion', data=data)

    def test_secretos_cifrados_y_no_expuestos(self, app, admin_authenticated_client):
        self._guardar(admin_authenticated_client, GREEN_API_TOKEN='token-super-secreto')
        fila = Configuracion.query.filter_by(clave='GREEN_API_TOKEN').one()
        assert fila.valor.startswith('enc:')
        assert 'token-super-secreto' not in fila.valor
        assert app.config['GREEN_API_TOKEN'] == 'token-super-secreto'
        assert app.config['APP_URL'] == 'https://buscapieza.do'
        html = admin_authenticated_client.get('/admin/configuracion').data
        assert b'token-super-secreto' not in html

        # Vacío = no cambiar
        self._guardar(admin_authenticated_client, GREEN_API_TOKEN='')
        assert app.config['GREEN_API_TOKEN'] == 'token-super-secreto'

    def test_config_bd_se_carga_al_arrancar(self, app, admin_authenticated_client):
        self._guardar(admin_authenticated_client, GREEN_API_TOKEN='persistente')
        from services.config_svc import cargar_config_bd
        app.config['GREEN_API_TOKEN'] = ''
        cargar_config_bd(app)
        assert app.config['GREEN_API_TOKEN'] == 'persistente'

    def test_comisiones_invalidas(self, admin_authenticated_client):
        self._guardar(admin_authenticated_client, comision_minima='40')
        assert Configuracion.query.filter_by(clave='comision_minima').one().valor == '5.00'


class TestPushToken:

    def test_guardar_token(self, proveedor_client, proveedor_user):
        r = proveedor_client.post('/push-token', json={'token': 'abc123'})
        assert r.status_code == 200
        assert PushToken.query.one().usuario_id == proveedor_user.id

    def test_sin_json(self, proveedor_client):
        assert proveedor_client.post('/push-token', data='x').status_code == 400
