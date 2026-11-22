"""
Fase 2 de compraventa: negociación en el panel (vendedor y comprador) y coincidencias oferta ↔ demanda.
"""
from decimal import Decimal

from models import Publicacion, Propuesta, Interes, Transaccion, Coincidencia
from tests.conftest import crear_usuario, crear_solicitud, login
from tests.test_ventas import _vendedor, _publicar, _aprobar


def _pendiente(client, app, tmp_path, titulo='Nevera Samsung 18 pies'):
    v = _vendedor(client, app, tmp_path)
    _publicar(client, titulo=titulo)
    return v, Publicacion.query.filter_by(titulo=titulo).one()


def _proponer(client, admin, pub, monto='20000', porcentaje='15', mostrar=False, mensaje='Es el precio de mercado'):
    login(client, admin)
    data = {'monto': monto, 'porcentaje': porcentaje, 'mensaje': mensaje}
    if mostrar:
        data['mostrar_precio'] = '1'
    return client.post(f'/admin/publicacion/{pub.id}/proponer', data=data)


class TestNegociacionVendedor:

    def test_vendedor_acepta_y_se_publica_solo(self, client, app, tmp_path, admin_user):
        v, pub = _pendiente(client, app, tmp_path)
        _proponer(client, admin_user, pub, monto='20000', porcentaje='15', mostrar=False)
        prop = Propuesta.query.one()
        assert prop.tipo == 'vendedor' and prop.autor == 'admin' and prop.estado == 'pendiente'
        assert pub.estado == 'pendiente'

        login(client, v)
        html = client.get('/vender/mis-publicaciones').get_data(as_text=True)
        assert 'te propone recibir' in html and '20,000.00' in html and 'Es el precio de mercado' in html
        client.post(f'/vender/{pub.id}/responder', data={'accion': 'aceptar'})
        assert prop.estado == 'aceptada'
        assert pub.estado == 'publicada'
        assert pub.precio_vendedor == Decimal('20000.00') and pub.precio_publico == Decimal('23000')
        assert pub.mostrar_precio is False          # se respeta lo elegido al proponer
        # El vendedor ve lo que recibe, pero nunca el precio público oculto ni el margen
        html = client.get('/vender/mis-publicaciones').get_data(as_text=True)
        assert 'Recibirás RD$20,000.00' in html
        assert '23,000' not in html and '3,000' not in html

    def test_contrapropuesta_y_admin_acepta(self, client, app, tmp_path, admin_user):
        v, pub = _pendiente(client, app, tmp_path)
        _proponer(client, admin_user, pub, monto='18000', porcentaje='20', mostrar=True)
        login(client, v)
        client.post(f'/vender/{pub.id}/responder', data={'accion': 'contraofertar', 'monto': '21000',
                                                         'mensaje': 'Me costó más'})
        assert [p.estado for p in pub.propuestas_vendedor()] == ['contraofertada', 'pendiente']
        assert pub.propuesta_vendedor_pendiente().autor == 'usuario'
        assert b'Esperando respuesta' in client.get('/vender/mis-publicaciones').data

        login(client, admin_user)
        html = client.get(f'/admin/publicacion/{pub.id}').get_data(as_text=True)
        assert 'Vendedor pide' in html and 'Me costó más' in html
        client.post(f'/admin/publicacion/{pub.id}/aceptar-vendedor')
        assert pub.estado == 'publicada'
        assert pub.precio_vendedor == Decimal('21000.00')
        assert pub.porcentaje_margen == Decimal('20.00') and pub.mostrar_precio is True   # de la última propuesta
        assert pub.precio_publico == Decimal('25200')
        assert pub.propuesta_vendedor_pendiente() is None

    def test_solo_una_propuesta_pendiente(self, client, app, tmp_path, admin_user):
        v, pub = _pendiente(client, app, tmp_path)
        _proponer(client, admin_user, pub, monto='18000')
        login(client, v)
        client.post(f'/vender/{pub.id}/responder', data={'accion': 'contraofertar', 'monto': '22000'})
        _proponer(client, admin_user, pub, monto='20000')
        estados = [(p.autor, p.estado) for p in pub.propuestas_vendedor()]
        assert estados == [('admin', 'contraofertada'), ('usuario', 'contraofertada'), ('admin', 'pendiente')]

    def test_rechazo_del_vendedor(self, client, app, tmp_path, admin_user):
        v, pub = _pendiente(client, app, tmp_path)
        _proponer(client, admin_user, pub)
        login(client, v)
        client.post(f'/vender/{pub.id}/responder', data={'accion': 'rechazar'})
        assert Propuesta.query.one().estado == 'rechazada'
        assert pub.estado == 'pendiente'

    def test_otro_usuario_no_responde(self, client, app, tmp_path, admin_user):
        _, pub = _pendiente(client, app, tmp_path)
        _proponer(client, admin_user, pub)
        login(client, crear_usuario('intruso@test.com'))
        assert client.post(f'/vender/{pub.id}/responder', data={'accion': 'aceptar'}).status_code == 404
        assert pub.estado == 'pendiente'

    def test_sin_propuesta_no_se_puede_aceptar(self, client, app, tmp_path):
        v, pub = _pendiente(client, app, tmp_path)
        client.post(f'/vender/{pub.id}/responder', data={'accion': 'aceptar'})
        assert pub.estado == 'pendiente'

    def test_comision_fuera_de_rango(self, client, app, tmp_path, admin_user):
        _, pub = _pendiente(client, app, tmp_path)
        _proponer(client, admin_user, pub, porcentaje='90')
        assert Propuesta.query.count() == 0


class TestNegociacionComprador:

    def _publicada(self, client, app, tmp_path, admin_user, mostrar=False):
        v, pub = _pendiente(client, app, tmp_path)
        _aprobar(client, admin_user, pub, precio='20000', porcentaje='15', mostrar=mostrar)
        return v, pub

    def _interesado(self, client, pub, email='ana@test.com', oferta=None):
        c = crear_usuario(email, nombre=email.split('@')[0].title())
        login(client, c)
        data = {'mensaje': '¿Cuánto?'}
        if oferta:
            data['oferta'] = oferta
        client.post(f'/catalogo/{pub.id}/interes', data=data)
        return c, Interes.query.filter_by(comprador_id=c.id).one()

    def test_oferta_inicial_es_propuesta(self, client, app, tmp_path, admin_user):
        _, pub = self._publicada(client, app, tmp_path, admin_user)
        _, it = self._interesado(client, pub, oferta='19000')
        prop = it.propuesta_pendiente()
        assert prop.autor == 'usuario' and prop.monto == Decimal('19000.00')

    def test_cotizacion_privada_y_aceptacion(self, client, app, tmp_path, admin_user):
        v, pub = self._publicada(client, app, tmp_path, admin_user, mostrar=False)
        ana, it_ana = self._interesado(client, pub, 'ana@test.com')
        luis, it_luis = self._interesado(client, pub, 'luis@test.com')

        login(client, admin_user)
        client.post(f'/admin/interes/{it_ana.id}/cotizar', data={'monto': '22000', 'mensaje': 'Precio especial'})
        client.post(f'/admin/interes/{it_luis.id}/cotizar', data={'monto': '23500'})
        assert it_ana.estado == 'contactado'

        # Cada comprador ve solo su precio; el catálogo no muestra ninguno
        login(client, luis)
        html = client.get('/catalogo/mis-consultas').get_data(as_text=True)
        assert '23,500.00' in html and '22,000' not in html
        for url in ('/catalogo', f'/catalogo/{pub.id}', '/'):
            assert '22,000' not in client.get(url).get_data(as_text=True)
        login(client, ana)
        html = client.get('/catalogo/mis-consultas').get_data(as_text=True)
        assert 'Precio para ti' in html and '22,000.00' in html and '23,500' not in html

        client.post(f'/catalogo/consulta/{it_ana.id}/responder', data={'accion': 'aceptar'})
        t = Transaccion.query.one()
        assert t.cliente_id == ana.id and t.precio_cliente == Decimal('22000.00')
        assert t.precio_proveedor == Decimal('20000.00') and t.comision_broker == Decimal('2000.00')
        assert pub.estado == 'reservada' and it_ana.estado == 'convertido'
        # La cotización abierta de Luis queda cerrada
        assert it_luis.propuestas[-1].estado == 'retirada'
        assert b'Trato hecho' in client.get('/catalogo/mis-consultas').data

        # Luis ya no puede comprar
        login(client, luis)
        client.post(f'/catalogo/consulta/{it_luis.id}/responder', data={'accion': 'aceptar'})
        assert Transaccion.query.count() == 1

    def test_contraoferta_y_admin_acepta(self, client, app, tmp_path, admin_user):
        _, pub = self._publicada(client, app, tmp_path, admin_user)
        ana, it = self._interesado(client, pub)
        login(client, admin_user)
        client.post(f'/admin/interes/{it.id}/cotizar', data={'monto': '23000'})
        login(client, ana)
        client.post(f'/catalogo/consulta/{it.id}/responder', data={'accion': 'contraofertar', 'monto': '21000'})
        assert it.propuesta_pendiente().autor == 'usuario'
        assert b'Esperando respuesta a tu oferta' in client.get('/catalogo/mis-consultas').data

        login(client, admin_user)
        html = client.get(f'/admin/publicacion/{pub.id}').get_data(as_text=True)
        assert 'Aceptar RD$21,000' in html and 'comisión RD$1,000' in html
        client.post(f'/admin/interes/{it.id}/aceptar-oferta')
        t = Transaccion.query.one()
        assert t.precio_cliente == Decimal('21000.00') and t.comision_broker == Decimal('1000.00')

    def test_no_se_cotiza_por_debajo_del_vendedor(self, client, app, tmp_path, admin_user):
        _, pub = self._publicada(client, app, tmp_path, admin_user)
        _, it = self._interesado(client, pub)
        login(client, admin_user)
        client.post(f'/admin/interes/{it.id}/cotizar', data={'monto': '19999'})
        assert it.propuesta_pendiente() is None

    def test_no_se_acepta_oferta_por_debajo_del_vendedor(self, client, app, tmp_path, admin_user):
        _, pub = self._publicada(client, app, tmp_path, admin_user)
        _, it = self._interesado(client, pub, oferta='15000')
        login(client, admin_user)
        client.post(f'/admin/interes/{it.id}/aceptar-oferta')
        assert Transaccion.query.count() == 0 and pub.estado == 'publicada'

    def test_comprador_no_responde_consulta_ajena(self, client, app, tmp_path, admin_user):
        _, pub = self._publicada(client, app, tmp_path, admin_user)
        _, it = self._interesado(client, pub)
        login(client, admin_user)
        client.post(f'/admin/interes/{it.id}/cotizar', data={'monto': '22000'})
        login(client, crear_usuario('otro@test.com'))
        assert client.post(f'/catalogo/consulta/{it.id}/responder', data={'accion': 'aceptar'}).status_code == 404
        assert Transaccion.query.count() == 0

    def test_cancelar_venta_permite_negociar_de_nuevo(self, client, app, tmp_path, admin_user):
        _, pub = self._publicada(client, app, tmp_path, admin_user)
        ana, it = self._interesado(client, pub)
        login(client, admin_user)
        client.post(f'/admin/interes/{it.id}/cotizar', data={'monto': '22000'})
        login(client, ana)
        client.post(f'/catalogo/consulta/{it.id}/responder', data={'accion': 'aceptar'})
        t = Transaccion.query.one()
        login(client, admin_user)
        client.post(f'/admin/transaccion/{t.id}/cancelar')
        assert pub.estado == 'publicada'
        _, it2 = self._interesado(client, pub, 'luis@test.com')
        login(client, admin_user)
        client.post(f'/admin/interes/{it2.id}/cotizar', data={'monto': '23000'})
        assert it2.propuesta_pendiente() is not None


class TestCoincidencias:

    def test_publicar_detecta_solicitud_y_ofrecer(self, client, app, tmp_path, admin_user):
        cliente = crear_usuario('busca@test.com', nombre='Carlos Busca')
        sol = crear_solicitud(cliente, titulo='Busco nevera Samsung', descripcion='Nevera Samsung de 18 pies o más')
        otra = crear_solicitud(cliente, titulo='Busco alternador Corolla 2015', descripcion='Alternador original')
        _, pub = _pendiente(client, app, tmp_path)
        _aprobar(client, admin_user, pub)

        c = Coincidencia.query.one()
        assert c.solicitud_id == sol.id and c.publicacion_id == pub.id and c.estado == 'nueva'
        assert 'nevera' in c.palabras and 'samsung' in c.palabras
        assert otra.coincidencias.count() == 0

        login(client, admin_user)
        assert b'Busco nevera Samsung' in client.get('/admin/coincidencias').data
        assert b'Clientes que buscan esto' in client.get(f'/admin/publicacion/{pub.id}').data
        assert b'En venta en BuscatodoRD' in client.get(f'/admin/solicitud/{sol.id}').data

        client.post(f'/admin/coincidencia/{c.id}/ofrecer')
        assert c.estado == 'ofrecida'
        it = Interes.query.one()
        assert it.comprador_id == cliente.id and it.publicacion_id == pub.id and it.estado == 'contactado'
        # Desde aquí se negocia como con cualquier interesado
        client.post(f'/admin/interes/{it.id}/cotizar', data={'monto': '22000'})
        assert it.propuesta_pendiente().monto == Decimal('22000.00')

    def test_solicitud_nueva_detecta_articulo_en_venta(self, client, app, tmp_path, admin_user):
        _, pub = _pendiente(client, app, tmp_path, titulo='iPhone 13 128GB')
        _aprobar(client, admin_user, pub)
        assert Coincidencia.query.count() == 0
        cliente = crear_usuario('busca@test.com')
        login(client, cliente)
        from models import Categoria
        client.post('/solicitudes/nueva', data={'titulo': 'Necesito iPhone 13', 'descripcion': 'Que esté en buen estado',
                                                'categoria_id': Categoria.query.first().id, 'urgencia': 'normal'})
        c = Coincidencia.query.one()
        assert c.publicacion_id == pub.id

    def test_sin_duplicados_y_descartar(self, client, app, tmp_path, admin_user):
        cliente = crear_usuario('busca@test.com')
        crear_solicitud(cliente, titulo='Busco nevera Samsung', descripcion='Nevera Samsung')
        _, pub = _pendiente(client, app, tmp_path)
        _aprobar(client, admin_user, pub)
        login(client, admin_user)
        client.post('/admin/coincidencias/recalcular')
        client.post(f'/admin/publicacion/{pub.id}/aprobar', data={'precio_vendedor': '20000', 'porcentaje': '15'})
        assert Coincidencia.query.count() == 1
        c = Coincidencia.query.one()
        client.post(f'/admin/coincidencia/{c.id}/descartar')
        assert c.estado == 'descartada'
        assert b'Busco nevera Samsung' not in client.get('/admin/coincidencias').data   # filtro por defecto: nuevas

    def test_no_coincide_con_lo_propio(self, client, app, tmp_path, admin_user):
        v, pub = _pendiente(client, app, tmp_path)
        crear_solicitud(v, titulo='Busco nevera Samsung', descripcion='Nevera Samsung')
        _aprobar(client, admin_user, pub)
        assert Coincidencia.query.count() == 0

    def test_dashboard_muestra_contadores(self, client, app, tmp_path, admin_user):
        cliente = crear_usuario('busca@test.com')
        crear_solicitud(cliente, titulo='Busco nevera Samsung', descripcion='Nevera Samsung')
        _, pub = _pendiente(client, app, tmp_path)
        _aprobar(client, admin_user, pub)
        login(client, admin_user)
        html = client.get('/admin/dashboard').get_data(as_text=True)
        assert 'Coincidencias nuevas' in html


class TestServicioEnMismaSesion:
    """Regresión: varias acciones seguidas en la misma sesión deben ver las propuestas recién creadas."""

    def test_cotizar_y_responder_sin_recargar(self, client, app, tmp_path, admin_user):
        from services import negociacion
        _, pub = _pendiente(client, app, tmp_path)
        negociacion.publicar(pub, Decimal('20000'), Decimal('15'), False)
        comprador = crear_usuario('ana@test.com')
        it = Interes(publicacion_id=pub.id, comprador_id=comprador.id)
        from extensions import db
        db.session.add(it)
        db.session.flush()
        negociacion.cotizar_a_comprador(it, Decimal('23000'))
        negociacion.comprador_responde(it, 'contraofertar', Decimal('21500'))
        negociacion.cotizar_a_comprador(it, Decimal('22500'))
        prop, trans = negociacion.comprador_responde(it, 'aceptar')
        db.session.commit()
        assert trans.precio_cliente == Decimal('22500') and pub.estado == 'reservada'
        assert [p.estado for p in it.propuestas] == ['contraofertada', 'contraofertada', 'aceptada']


class TestFormulariosSugeridos:

    def test_contrapropuesta_parte_de_lo_ultimo_negociado(self, client, app, tmp_path, admin_user):
        v, pub = _pendiente(client, app, tmp_path)
        _proponer(client, admin_user, pub, monto='28000', porcentaje='12', mostrar=True)
        login(client, v)
        client.post(f'/vender/{pub.id}/responder', data={'accion': 'contraofertar', 'monto': '31000'})
        login(client, admin_user)
        html = client.get(f'/admin/publicacion/{pub.id}').get_data(as_text=True)
        import re
        valores = re.findall(r'name="(monto|porcentaje|precio_vendedor)"[^>]*?value="([^"]*)"', html, re.S)
        assert valores == [('monto', '31000.00'), ('porcentaje', '12.00'),
                           ('precio_vendedor', '31000.00'), ('porcentaje', '12.00')]
