"""
Tests de compraventa: publicar → aprobar con precio y comisión → catálogo (precio visible u oculto)
→ interesados → venta negociada → pago. Incluye privacidad del vendedor y del precio oculto.
"""
import io
from decimal import Decimal

from models import Publicacion, PublicacionFoto, Interes, Transaccion, Categoria
from tests.conftest import crear_usuario, login
from tests.test_solicitudes import PNG_1PX


def _datos(**override):
    d = {
        'titulo': 'Nevera Samsung 18 pies',
        'descripcion': 'Nevera en buen estado, 3 años de uso, enfría perfecto.',
        'categoria_id': str(Categoria.query.first().id),
        'condicion': 'usado',
        'precio_pedido': '25000',
    }
    d.update(override)
    return d


def _publicar(client, **override):
    data = _datos(**override)
    data.setdefault('fotos', [(io.BytesIO(PNG_1PX), 'nevera.png')])
    return client.post('/vender/nueva', data=data, content_type='multipart/form-data')


def _vendedor(client, app, tmp_path):
    app.config['UPLOAD_FOLDER'] = str(tmp_path)
    v = crear_usuario('vendedor@test.com', nombre='Pedro Vendedor', telefono='8095557777')
    login(client, v)
    return v


def _aprobar(client, admin, pub, precio='20000', porcentaje='15', mostrar=True):
    login(client, admin)
    data = {'precio_vendedor': precio, 'porcentaje': porcentaje}
    if mostrar:
        data['mostrar_precio'] = '1'
    return client.post(f'/admin/publicacion/{pub.id}/aprobar', data=data)


class TestPublicar:

    def test_publicar(self, client, app, tmp_path):
        v = _vendedor(client, app, tmp_path)
        assert client.get('/vender/nueva').status_code == 200
        r = _publicar(client)
        assert r.status_code == 302
        pub = Publicacion.query.one()
        assert pub.vendedor_id == v.id
        assert pub.estado == 'pendiente'
        assert pub.codigo.startswith('BV-')
        assert pub.precio_pedido == Decimal('25000.00')
        assert len(pub.fotos) == 1 and pub.fotos[0].es_principal
        assert b'Nevera Samsung' in client.get('/vender/mis-publicaciones').data

    def test_requiere_foto_valida(self, client, app, tmp_path):
        _vendedor(client, app, tmp_path)
        r = _publicar(client, fotos=[(io.BytesIO(b'<script>x</script>'), 'falsa.jpg')])
        assert r.status_code == 400
        assert Publicacion.query.count() == 0

    def test_validaciones(self, client, app, tmp_path):
        _vendedor(client, app, tmp_path)
        assert _publicar(client, titulo='').status_code == 400
        assert _publicar(client, precio_pedido='abc').status_code == 400
        assert _publicar(client, precio_pedido='0').status_code == 400
        assert _publicar(client, categoria_id='').status_code == 400
        assert Publicacion.query.count() == 0

    def test_requiere_login(self, client):
        r = client.get('/vender/nueva')
        assert r.status_code == 302 and '/auth/login' in r.headers['Location']

    def test_pendiente_no_sale_en_catalogo(self, client, app, tmp_path):
        _vendedor(client, app, tmp_path)
        _publicar(client)
        pub = Publicacion.query.one()
        client.get('/auth/logout')
        assert b'Nevera Samsung' not in client.get('/catalogo').data
        assert client.get(f'/catalogo/{pub.id}').status_code == 404

    def test_otro_usuario_no_edita(self, client, app, tmp_path):
        _vendedor(client, app, tmp_path)
        _publicar(client)
        pub = Publicacion.query.one()
        login(client, crear_usuario('otro@test.com'))
        assert client.get(f'/vender/{pub.id}/editar').status_code == 404
        client.post(f'/vender/{pub.id}/retirar')
        assert pub.estado == 'pendiente'


class TestAprobacionYCatalogo:

    def test_aprobar_precio_visible(self, client, app, tmp_path, admin_user):
        _vendedor(client, app, tmp_path)
        _publicar(client)
        pub = Publicacion.query.one()
        _aprobar(client, admin_user, pub, precio='20000', porcentaje='15')
        assert pub.estado == 'publicada'
        assert pub.precio_vendedor == Decimal('20000.00')
        assert pub.precio_publico == Decimal('23000')
        assert pub.comision_estimada == Decimal('3000.00')
        assert pub.publicada_en is not None

        client.get('/auth/logout')
        html = client.get('/catalogo').get_data(as_text=True)
        assert 'Nevera Samsung' in html and 'RD$23,000' in html
        detalle = client.get(f'/catalogo/{pub.id}').get_data(as_text=True)
        assert 'RD$23,000' in detalle and 'Me interesa' in detalle
        assert 'RD$23,000' in client.get('/').get_data(as_text=True)

    def test_precio_oculto_no_aparece_en_ningun_sitio(self, client, app, tmp_path, admin_user):
        _vendedor(client, app, tmp_path)
        _publicar(client)
        pub = Publicacion.query.one()
        _aprobar(client, admin_user, pub, precio='20000', porcentaje='15', mostrar=False)
        assert pub.mostrar_precio is False and pub.precio_publico == Decimal('23000')

        client.get('/auth/logout')
        comprador = crear_usuario('comprador@test.com')
        for c in (client, login(app.test_client(), comprador)):
            for url in ('/', '/catalogo', '/catalogo?orden=precio_asc', f'/catalogo/{pub.id}'):
                html = c.get(url).get_data(as_text=True)
                for fuga in ('23,000', '23000', '20,000', '20000', '25,000', '25000'):
                    assert fuga not in html, (url, fuga)
            assert 'Consultar precio' in c.get(f'/catalogo/{pub.id}').get_data(as_text=True) or c is client

    def test_datos_del_vendedor_son_privados(self, client, app, tmp_path, admin_user):
        _vendedor(client, app, tmp_path)
        _publicar(client)
        pub = Publicacion.query.one()
        _aprobar(client, admin_user, pub)
        login(client, crear_usuario('comprador@test.com'))
        for url in ('/', '/catalogo', f'/catalogo/{pub.id}'):
            html = client.get(url).get_data(as_text=True)
            for dato in ('Pedro Vendedor', '8095557777', 'vendedor@test.com'):
                assert dato not in html, (url, dato)

    def test_orden_por_precio_no_revela_ocultos(self, client, app, tmp_path, admin_user):
        _vendedor(client, app, tmp_path)
        for titulo, precio in (('Oculto caro', '90000'), ('Visible barato', '1000'), ('Oculto barato', '500')):
            _publicar(client, titulo=titulo)
        pubs = {p.titulo: p for p in Publicacion.query.all()}
        _aprobar(client, admin_user, pubs['Oculto caro'], precio='90000', mostrar=False)
        _aprobar(client, admin_user, pubs['Visible barato'], precio='1000')
        _aprobar(client, admin_user, pubs['Oculto barato'], precio='500', mostrar=False)
        client.get('/auth/logout')
        for orden in ('precio_asc', 'precio_desc'):
            html = client.get(f'/catalogo?orden={orden}').get_data(as_text=True)
            # El visible va primero; los ocultos después, sin ordenarse por su precio real
            assert html.index('Visible barato') < html.index('Oculto caro')
            assert html.index('Visible barato') < html.index('Oculto barato')

    def test_comision_fuera_de_rango(self, client, app, tmp_path, admin_user):
        _vendedor(client, app, tmp_path)
        _publicar(client)
        pub = Publicacion.query.one()
        _aprobar(client, admin_user, pub, porcentaje='80')
        assert pub.estado == 'pendiente' and pub.precio_publico is None

    def test_rechazar_y_reenviar(self, client, app, tmp_path, admin_user):
        v = _vendedor(client, app, tmp_path)
        _publicar(client)
        pub = Publicacion.query.one()
        login(client, admin_user)
        client.post(f'/admin/publicacion/{pub.id}/rechazar', data={'motivo': ''})
        assert pub.estado == 'pendiente'          # sin motivo no se rechaza
        client.post(f'/admin/publicacion/{pub.id}/rechazar', data={'motivo': 'Fotos borrosas'})
        assert pub.estado == 'rechazada' and pub.motivo_rechazo == 'Fotos borrosas'

        login(client, v)
        assert b'Fotos borrosas' in client.get('/vender/mis-publicaciones').data
        r = client.post(f'/vender/{pub.id}/editar', data=_datos(titulo='Nevera Samsung 18p (fotos nuevas)'),
                        content_type='multipart/form-data')
        assert r.status_code == 302
        assert pub.estado == 'pendiente' and pub.motivo_rechazo is None
        assert pub.titulo.endswith('(fotos nuevas)')
        assert len(pub.fotos) == 1                # conserva la foto existente

    def test_editar_no_deja_sin_fotos(self, client, app, tmp_path):
        _vendedor(client, app, tmp_path)
        _publicar(client)
        pub = Publicacion.query.one()
        foto_id = pub.fotos[0].id
        r = client.post(f'/vender/{pub.id}/editar', data={**_datos(), 'borrar_foto': str(foto_id)},
                        content_type='multipart/form-data')
        assert r.status_code == 400
        assert PublicacionFoto.query.count() == 1


class TestInteresadosYVenta:

    def _publicada(self, client, app, tmp_path, admin_user, mostrar=True):
        v = _vendedor(client, app, tmp_path)
        _publicar(client)
        pub = Publicacion.query.one()
        _aprobar(client, admin_user, pub, precio='20000', porcentaje='15', mostrar=mostrar)
        return v, pub

    def test_interes_y_venta_completa(self, client, app, tmp_path, admin_user):
        v, pub = self._publicada(client, app, tmp_path, admin_user, mostrar=False)
        comprador = crear_usuario('comprador@test.com', nombre='Ana Compradora')
        login(client, comprador)
        r = client.post(f'/catalogo/{pub.id}/interes', data={'mensaje': '¿Precio?', 'oferta': '21000'})
        assert r.status_code == 302
        it = Interes.query.one()
        assert it.comprador_id == comprador.id and it.oferta_comprador == Decimal('21000.00')
        # Repetir no duplica: actualiza
        client.post(f'/catalogo/{pub.id}/interes', data={'oferta': '21500'})
        assert Interes.query.count() == 1 and it.oferta_comprador == Decimal('21500.00')
        assert b'Mis consultas' in client.get('/catalogo/mis-consultas').data

        login(client, admin_user)
        html = client.get(f'/admin/publicacion/{pub.id}').get_data(as_text=True)
        assert 'Ana Compradora' in html and 'Pedro Vendedor' in html
        # Venta negociada por debajo del precio de lista: la comisión es la diferencia real
        client.post(f'/admin/publicacion/{pub.id}/vender',
                    data={'interes_id': it.id, 'precio_final': '22000', 'precio_vendedor': '20000'})
        t = Transaccion.query.one()
        assert t.publicacion_id == pub.id and t.solicitud_id is None
        assert t.cliente_id == comprador.id and t.proveedor_id == v.id
        assert t.comision_broker == Decimal('2000.00') and t.porcentaje_comision == Decimal('10.00')
        assert pub.estado == 'reservada' and it.estado == 'convertido'

        client.get('/auth/logout')
        assert b'Reservado' in client.get('/catalogo').data

        login(client, admin_user)
        client.post(f'/admin/transaccion/{t.id}/pagar', data={'metodo_pago': 'transferencia'})
        assert t.estado_pago == 'pagado' and pub.estado == 'vendida'
        assert b'RD$2,000' in client.get('/admin/dashboard').data
        ventas = client.get('/admin/transacciones').get_data(as_text=True)
        assert pub.codigo in ventas
        client.get('/auth/logout')
        assert b'Nevera Samsung' not in client.get('/catalogo').data

    def test_cancelar_venta_vuelve_al_catalogo(self, client, app, tmp_path, admin_user):
        _, pub = self._publicada(client, app, tmp_path, admin_user)
        login(client, crear_usuario('comprador@test.com'))
        client.post(f'/catalogo/{pub.id}/interes', data={})
        it = Interes.query.one()
        login(client, admin_user)
        client.post(f'/admin/publicacion/{pub.id}/vender',
                    data={'interes_id': it.id, 'precio_final': '23000', 'precio_vendedor': '20000'})
        t = Transaccion.query.one()
        client.post(f'/admin/transaccion/{t.id}/cancelar')
        assert t.estado_pago == 'cancelado' and pub.estado == 'publicada'

    def test_venta_por_debajo_del_vendedor_rechazada(self, client, app, tmp_path, admin_user):
        _, pub = self._publicada(client, app, tmp_path, admin_user)
        login(client, crear_usuario('comprador@test.com'))
        client.post(f'/catalogo/{pub.id}/interes', data={})
        login(client, admin_user)
        client.post(f'/admin/publicacion/{pub.id}/vender',
                    data={'interes_id': Interes.query.one().id, 'precio_final': '19000', 'precio_vendedor': '20000'})
        assert Transaccion.query.count() == 0 and pub.estado == 'publicada'

    def test_vendedor_no_puede_interesarse_en_lo_suyo(self, client, app, tmp_path, admin_user):
        v, pub = self._publicada(client, app, tmp_path, admin_user)
        login(client, v)
        client.post(f'/catalogo/{pub.id}/interes', data={})
        assert Interes.query.count() == 0

    def test_interes_requiere_login(self, client, app, tmp_path, admin_user):
        _, pub = self._publicada(client, app, tmp_path, admin_user)
        client.get('/auth/logout')
        r = client.post(f'/catalogo/{pub.id}/interes', data={})
        assert r.status_code == 302 and '/auth/login' in r.headers['Location']

    def test_retirar_por_vendedor(self, client, app, tmp_path, admin_user):
        v, pub = self._publicada(client, app, tmp_path, admin_user)
        login(client, v)
        client.post(f'/vender/{pub.id}/retirar')
        assert pub.estado == 'retirada'
        client.get('/auth/logout')
        assert client.get(f'/catalogo/{pub.id}').status_code == 404

    def test_paginas_admin(self, client, app, tmp_path, admin_user):
        _, pub = self._publicada(client, app, tmp_path, admin_user)
        login(client, admin_user)
        for url in ('/admin/publicaciones', '/admin/publicaciones?estado=publicada',
                    f'/admin/publicacion/{pub.id}', '/admin/dashboard', '/admin/transacciones', '/admin/analytics'):
            assert client.get(url).status_code == 200, url

    def test_cliente_no_entra_al_admin_de_publicaciones(self, client, app, tmp_path, admin_user):
        _, pub = self._publicada(client, app, tmp_path, admin_user)
        login(client, crear_usuario('cliente2@test.com'))
        assert client.get('/admin/publicaciones').status_code == 302
        client.post(f'/admin/publicacion/{pub.id}/rechazar', data={'motivo': 'x'})
        assert pub.estado == 'publicada'
