"""
Fase 3: pagos en línea (transferencia, Azul, CardNet), ITBIS configurable y destacados.
"""
import hashlib
import hmac
import io
import re
from datetime import timedelta
from decimal import Decimal

import pytest

from extensions import db
from models import Pago, Transaccion, PlanDestacado, Interes, Publicacion, Configuracion, ahora_utc
from services import negociacion, pagos as svc
from services.pasarelas import azul, cardnet
from tests.conftest import crear_usuario, login
from tests.test_solicitudes import PNG_1PX
from tests.test_ventas import _vendedor, _publicar


# ── Preparación ───────────────────────────────────────────────────────────────

def _venta(client, app, tmp_path, precio_vendedor='20000', precio_final='23000'):
    """Publicación vendida a un comprador, pendiente de pago. Devuelve (vendedor, comprador, pub, trans)."""
    v = _vendedor(client, app, tmp_path)
    _publicar(client)
    pub = Publicacion.query.one()
    negociacion.publicar(pub, Decimal(precio_vendedor), Decimal('15'), True)
    comprador = crear_usuario('comprador@test.com', nombre='Ana Compradora')
    it = Interes(publicacion_id=pub.id, comprador_id=comprador.id)
    db.session.add(it)
    db.session.flush()
    trans = negociacion.registrar_venta(pub, it, Decimal(precio_final), Decimal(precio_vendedor))
    db.session.commit()
    return v, comprador, pub, trans


def _configurar_azul(app):
    app.config.update(AZUL_MERCHANT_ID='39038540035', AZUL_MERCHANT_NAME='BuscatodoRD', AZUL_MERCHANT_TYPE='E-Commerce',
                      AZUL_CURRENCY_CODE='$', AZUL_AUTH_KEY='clave-de-prueba-azul', AZUL_AMBIENTE='pruebas',
                      APP_URL='https://buscatodo.example.do')


def _configurar_cardnet(app):
    app.config.update(CARDNET_MERCHANT_NUMBER='349000000', CARDNET_MERCHANT_TERMINAL='58585858',
                      CARDNET_ACQUIRING_CODE='349', CARDNET_MERCHANT_TYPE='7997', CARDNET_AMBIENTE='pruebas',
                      CARDNET_URL_BASE='', APP_URL='https://buscatodo.example.do')


def _hmac_utf16(texto, clave):
    return hmac.new(clave.encode(), texto.encode('utf-16-le'), hashlib.sha512).hexdigest()


def _respuesta_azul(pago, iso='00', amount=None, clave='clave-de-prueba-azul'):
    p = {'OrderNumber': str(pago.id), 'Amount': amount or azul.formato_monto(pago.monto), 'AuthorizationCode': 'OK1234',
         'DateTime': '20261122153000', 'ResponseCode': 'ISO8583', 'IsoCode': iso,
         'ResponseMessage': 'APROBADA' if iso == '00' else 'DECLINADA', 'ErrorDescription': '', 'RRN': '123456789012',
         'AzulOrderId': '987654'}
    p['AuthHash'] = _hmac_utf16(''.join(p[k] for k in azul.CAMPOS_HASH_RESPUESTA) + clave, clave)
    return p


# ── ITBIS ─────────────────────────────────────────────────────────────────────

class TestItbis:

    def test_por_defecto_cero(self, client, app, tmp_path):
        *_, trans = _venta(client, app, tmp_path)
        m = svc.montos_venta(trans)
        assert m == {'subtotal': Decimal('23000.00'), 'itbis': Decimal('0.00'), 'monto': Decimal('23000.00')}

    def test_sobre_la_comision(self, client, app, tmp_path):
        *_, trans = _venta(client, app, tmp_path)
        assert svc.config_svc.guardar_itbis('18') is None
        m = svc.montos_venta(trans)
        assert m['itbis'] == Decimal('540.00')                 # 18% de la comisión de 3,000
        assert m['monto'] == Decimal('23540.00')
        assert svc.montos_destacado(Decimal('300'))['itbis'] == Decimal('54.00')

    def test_validacion(self, app):
        assert svc.config_svc.guardar_itbis('abc')
        assert svc.config_svc.guardar_itbis('150')


# ── Transferencia ─────────────────────────────────────────────────────────────

class TestTransferencia:

    def test_flujo_completo(self, client, app, tmp_path, admin_user):
        app.config['TRANSFERENCIA_INSTRUCCIONES'] = 'Banco Popular · Cta 123-456789-0'
        v, comprador, pub, trans = _venta(client, app, tmp_path)
        login(client, comprador)
        assert b'Pagar ahora' in client.get('/catalogo/mis-consultas').data
        assert client.get(f'/pagos/venta/{trans.id}').status_code == 200
        r = client.post('/pagos/iniciar', data={'concepto': 'venta', 'id': trans.id, 'metodo': 'transferencia'})
        pago = Pago.query.one()
        assert r.status_code == 302 and pago.referencia in r.headers['Location']
        assert pago.estado == 'pendiente' and pago.monto == Decimal('23000.00') and pago.usuario_id == comprador.id
        html = client.get(f'/pagos/{pago.referencia}').get_data(as_text=True)
        assert 'Cta 123-456789-0' in html and pago.referencia in html

        # Archivo falso rechazado; imagen real aceptada
        client.post(f'/pagos/{pago.referencia}/comprobante',
                    data={'comprobante': (io.BytesIO(b'<script>'), 'x.jpg')}, content_type='multipart/form-data')
        assert pago.estado == 'pendiente'
        client.post(f'/pagos/{pago.referencia}/comprobante',
                    data={'comprobante': (io.BytesIO(PNG_1PX), 'comprobante.png')}, content_type='multipart/form-data')
        assert pago.estado == 'en_revision' and pago.comprobante_url

        login(client, admin_user)
        assert pago.referencia.encode() in client.get('/admin/pagos').data
        client.post(f'/admin/pago/{pago.id}/aprobar', data={'autorizacion': 'TRF-555'})
        assert pago.estado == 'aprobado' and pago.autorizacion == 'TRF-555' and pago.revisado_por_id == admin_user.id
        assert trans.estado_pago == 'pagado' and trans.metodo_pago == 'transferencia'
        assert pub.estado == 'vendida'

        login(client, comprador)
        recibo = client.get(f'/pagos/{pago.referencia}/recibo').get_data(as_text=True)
        assert 'RECIBO DE PAGO' in recibo and 'no es un comprobante fiscal' in recibo
        login(client, crear_usuario('intruso@test.com'))
        assert client.get(f'/pagos/{pago.referencia}').status_code == 404
        assert client.get(f'/pagos/{pago.referencia}/recibo').status_code == 404

    def test_comprobante_pdf_y_rechazo(self, client, app, tmp_path, admin_user):
        _, comprador, _, trans = _venta(client, app, tmp_path)
        login(client, comprador)
        client.post('/pagos/iniciar', data={'concepto': 'venta', 'id': trans.id, 'metodo': 'transferencia'})
        pago = Pago.query.one()
        client.post(f'/pagos/{pago.referencia}/comprobante',
                    data={'comprobante': (io.BytesIO(b'%PDF-1.4 recibo'), 'recibo.pdf')}, content_type='multipart/form-data')
        assert pago.estado == 'en_revision'
        login(client, admin_user)
        client.post(f'/admin/pago/{pago.id}/rechazar', data={'motivo': ''})
        assert pago.estado == 'en_revision'
        client.post(f'/admin/pago/{pago.id}/rechazar', data={'motivo': 'El monto no coincide'})
        assert pago.estado == 'rechazado' and trans.estado_pago == 'pendiente'
        login(client, comprador)
        assert b'El monto no coincide' in client.get(f'/pagos/{pago.referencia}').data
        client.post(f'/pagos/{pago.referencia}/comprobante',
                    data={'comprobante': (io.BytesIO(PNG_1PX), 'otro.png')}, content_type='multipart/form-data')
        assert pago.estado == 'en_revision'

    def test_no_se_paga_lo_ajeno_ni_dos_veces(self, client, app, tmp_path, admin_user):
        _, comprador, _, trans = _venta(client, app, tmp_path)
        login(client, crear_usuario('otro@test.com'))
        assert client.get(f'/pagos/venta/{trans.id}').status_code == 404
        client.post('/pagos/iniciar', data={'concepto': 'venta', 'id': trans.id, 'metodo': 'transferencia'})
        assert Pago.query.count() == 0
        login(client, comprador)
        client.post('/pagos/iniciar', data={'concepto': 'venta', 'id': trans.id, 'metodo': 'transferencia'})
        pago = Pago.query.one()
        svc.aprobar(pago)
        db.session.commit()
        client.post('/pagos/iniciar', data={'concepto': 'venta', 'id': trans.id, 'metodo': 'transferencia'})
        assert Pago.query.count() == 1
        assert svc.aprobar(pago) is False          # idempotente

    def test_metodo_no_configurado(self, client, app, tmp_path):
        _, comprador, _, trans = _venta(client, app, tmp_path)
        assert svc.metodos_disponibles() == ['transferencia']
        login(client, comprador)
        client.post('/pagos/iniciar', data={'concepto': 'venta', 'id': trans.id, 'metodo': 'azul'})
        assert Pago.query.count() == 0


# ── Azul ──────────────────────────────────────────────────────────────────────

class TestAzul:

    def test_formato_monto_segun_documento(self):
        assert azul.formato_monto(Decimal('10.00')) == '1000'
        assert azul.formato_monto(Decimal('17483.21')) == '1748321'
        assert azul.formato_monto(0) == '000'

    def test_formulario_firmado(self, client, app, tmp_path):
        _configurar_azul(app)
        _, comprador, _, trans = _venta(client, app, tmp_path)
        login(client, comprador)
        html = client.post('/pagos/iniciar', data={'concepto': 'venta', 'id': trans.id, 'metodo': 'azul'}).get_data(as_text=True)
        assert 'action="https://pruebas.azul.com.do/PaymentPage/"' in html
        campos = dict(re.findall(r'name="([^"]+)" value="([^"]*)"', html))
        assert campos['Amount'] == '2300000' and campos['ITBIS'] == '000' and campos['MerchantId'] == '39038540035'
        assert campos['ApprovedUrl'] == 'https://buscatodo.example.do/pagos/azul/aprobado'
        cadena = ''.join(campos[k] for k in azul.CAMPOS_HASH_PETICION) + 'clave-de-prueba-azul'
        assert campos['AuthHash'] == _hmac_utf16(cadena, 'clave-de-prueba-azul')

    def test_vuelta_aprobada_sin_sesion(self, client, app, tmp_path):
        _configurar_azul(app)
        _, comprador, pub, trans = _venta(client, app, tmp_path)
        login(client, comprador)
        client.post('/pagos/iniciar', data={'concepto': 'venta', 'id': trans.id, 'metodo': 'azul'})
        pago = Pago.query.one()
        client.get('/auth/logout')
        r = client.get('/pagos/azul/aprobado', query_string=_respuesta_azul(pago))
        assert r.status_code == 200 and b'Pago confirmado' in r.data
        assert pago.estado == 'aprobado' and pago.autorizacion == 'OK1234' and pago.pasarela_ref == '987654'
        assert trans.estado_pago == 'pagado' and trans.metodo_pago == 'tarjeta' and pub.estado == 'vendida'
        # Repetir la vuelta no duplica nada
        client.get('/pagos/azul/aprobado', query_string=_respuesta_azul(pago))
        assert Pago.query.filter_by(estado='aprobado').count() == 1

    def test_respuesta_manipulada_se_ignora(self, client, app, tmp_path):
        _configurar_azul(app)
        _, comprador, _, trans = _venta(client, app, tmp_path)
        login(client, comprador)
        client.post('/pagos/iniciar', data={'concepto': 'venta', 'id': trans.id, 'metodo': 'azul'})
        pago = Pago.query.one()
        falsa = _respuesta_azul(pago)
        falsa['Amount'] = '100'                       # cambia el monto sin poder rehacer la firma
        client.get('/pagos/azul/aprobado', query_string=falsa)
        assert pago.estado == 'pendiente' and trans.estado_pago == 'pendiente'
        otra = _respuesta_azul(pago, clave='clave-equivocada')
        client.get('/pagos/azul/aprobado', query_string=otra)
        assert pago.estado == 'pendiente'

    def test_monto_distinto_firmado_no_aprueba(self, client, app, tmp_path):
        _configurar_azul(app)
        _, comprador, _, trans = _venta(client, app, tmp_path)
        login(client, comprador)
        client.post('/pagos/iniciar', data={'concepto': 'venta', 'id': trans.id, 'metodo': 'azul'})
        pago = Pago.query.one()
        client.get('/pagos/azul/aprobado', query_string=_respuesta_azul(pago, amount='100'))
        assert pago.estado == 'pendiente' and trans.estado_pago == 'pendiente'

    def test_declinada_y_cancelada(self, client, app, tmp_path):
        _configurar_azul(app)
        _, comprador, _, trans = _venta(client, app, tmp_path)
        login(client, comprador)
        client.post('/pagos/iniciar', data={'concepto': 'venta', 'id': trans.id, 'metodo': 'azul'})
        pago = Pago.query.one()
        client.get('/pagos/azul/declinado', query_string=_respuesta_azul(pago, iso='05'))
        assert pago.estado == 'rechazado' and pago.motivo_rechazo == 'DECLINADA'
        client.post('/pagos/iniciar', data={'concepto': 'venta', 'id': trans.id, 'metodo': 'azul'})
        pago2 = Pago.query.filter(Pago.id != pago.id).one()
        client.get(f'/pagos/azul/cancelado/{pago2.referencia}')
        assert pago2.estado == 'cancelado' and trans.estado_pago == 'pendiente'


# ── CardNet ───────────────────────────────────────────────────────────────────

class _Resp:
    def __init__(self, datos, status=200):
        self._d, self.status_code = datos, status

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(str(self.status_code))

    def json(self):
        return self._d


class TestCardnet:

    def _preparar(self, client, app, tmp_path, monkeypatch, resultado):
        _configurar_cardnet(app)
        enviado = {}

        def falso_post(url, json=None, timeout=None):
            enviado['url'], enviado['json'] = url, json
            return _Resp({'SESSION': 'SES123', 'session-key': 'KEY456'})

        def falso_get(url, params=None, timeout=None):
            enviado['consulta'] = (url, params)
            return _Resp(resultado)

        monkeypatch.setattr(cardnet.requests, 'post', falso_post)
        monkeypatch.setattr(cardnet.requests, 'get', falso_get)
        _, comprador, pub, trans = _venta(client, app, tmp_path)
        login(client, comprador)
        html = client.post('/pagos/iniciar', data={'concepto': 'venta', 'id': trans.id, 'metodo': 'cardnet'}).get_data(as_text=True)
        return enviado, html, Pago.query.one(), trans, pub

    def test_aprobado(self, client, app, tmp_path, monkeypatch):
        enviado, html, pago, trans, pub = self._preparar(
            client, app, tmp_path, monkeypatch,
            {'ResponseCode': '00', 'AuthorizationCode': 'A77', 'Amount': '000002300000', 'CreditcardNumber': '4111111111111111'})
        assert enviado['url'] == 'https://labservicios.cardnet.com.do/sessions'
        datos = enviado['json']
        assert datos['Amount'] == '000002300000' and datos['Tax'] == '000000000000' and datos['CurrencyCode'] == '214'
        assert datos['ReturnUrl'] == f'https://buscatodo.example.do/pagos/cardnet/vuelta/{pago.referencia}'
        assert 'action="https://labservicios.cardnet.com.do/authorize"' in html and 'value="SES123"' in html
        assert pago.pasarela_ref == 'SES123' and pago.pasarela_clave == 'KEY456'

        client.get('/auth/logout')
        client.post(f'/pagos/cardnet/vuelta/{pago.referencia}')
        assert enviado['consulta'] == ('https://labservicios.cardnet.com.do/sessions/SES123', {'sk': 'KEY456'})
        assert pago.estado == 'aprobado' and pago.autorizacion == 'A77'
        assert trans.estado_pago == 'pagado' and pub.estado == 'vendida'
        assert '4111111111111111' not in pago.respuesta and '****1111' in pago.respuesta

    def test_declinado(self, client, app, tmp_path, monkeypatch):
        _, _, pago, trans, _ = self._preparar(client, app, tmp_path, monkeypatch,
                                              {'ResponseCode': '51', 'ResponseMessage': 'Fondos insuficientes'})
        client.get(f'/pagos/cardnet/vuelta/{pago.referencia}')
        assert pago.estado == 'rechazado' and 'Fondos insuficientes' in pago.motivo_rechazo
        assert trans.estado_pago == 'pendiente'

    def test_monto_distinto_no_aprueba(self, client, app, tmp_path, monkeypatch):
        _, _, pago, trans, _ = self._preparar(client, app, tmp_path, monkeypatch,
                                              {'ResponseCode': '00', 'Amount': '000000000100'})
        client.get(f'/pagos/cardnet/vuelta/{pago.referencia}')
        assert pago.estado == 'pendiente' and trans.estado_pago == 'pendiente'

    def test_cardnet_caido(self, client, app, tmp_path, monkeypatch):
        _configurar_cardnet(app)
        import requests

        def falla(*a, **k):
            raise requests.ConnectionError('sin red')
        monkeypatch.setattr(cardnet.requests, 'post', falla)
        _, comprador, _, trans = _venta(client, app, tmp_path)
        login(client, comprador)
        client.post('/pagos/iniciar', data={'concepto': 'venta', 'id': trans.id, 'metodo': 'cardnet'})
        assert Pago.query.one().estado == 'cancelado'


# ── Destacados ────────────────────────────────────────────────────────────────

class TestDestacados:

    def test_comprar_y_activar(self, client, app, tmp_path, admin_user):
        v = _vendedor(client, app, tmp_path)
        _publicar(client, titulo='Nevera Samsung')
        _publicar(client, titulo='Taladro DeWalt')
        nevera, taladro = (Publicacion.query.filter_by(titulo=t).one() for t in ('Nevera Samsung', 'Taladro DeWalt'))
        negociacion.publicar(nevera, Decimal('20000'), Decimal('15'), True)
        negociacion.publicar(taladro, Decimal('7000'), Decimal('15'), True)
        taladro.publicada_en = ahora_utc() + timedelta(minutes=1)    # el más reciente
        db.session.commit()
        plan = PlanDestacado.query.filter_by(dias=7).one()
        assert plan.precio == Decimal('300.00')

        login(client, v)
        assert b'Destacado 7' in client.get(f'/pagos/destacar/{nevera.id}').data
        client.post('/pagos/iniciar', data={'concepto': 'destacado', 'id': nevera.id, 'metodo': 'transferencia',
                                            'plan_id': plan.id})
        pago = Pago.query.one()
        assert pago.concepto == 'destacado' and pago.monto == Decimal('300.00')
        assert nevera.destacada is False

        login(client, admin_user)
        client.post(f'/admin/pago/{pago.id}/aprobar')
        assert nevera.destacada
        fin = nevera.destacado_hasta
        assert timedelta(days=6, hours=23) < fin - ahora_utc() <= timedelta(days=7)

        client.get('/auth/logout')
        html = client.get('/catalogo').get_data(as_text=True)
        assert html.index('Nevera Samsung') < html.index('Taladro DeWalt')   # destacado primero
        assert '⭐ Destacado' in html

        # Comprar otro plan extiende desde el fin actual
        login(client, v)
        client.post('/pagos/iniciar', data={'concepto': 'destacado', 'id': nevera.id, 'metodo': 'transferencia',
                                            'plan_id': plan.id})
        pago2 = Pago.query.filter(Pago.id != pago.id).one()
        svc.aprobar(pago2)
        db.session.commit()
        assert nevera.destacado_hasta == fin + timedelta(days=7)

    def test_solo_el_dueno_y_publicada(self, client, app, tmp_path):
        v = _vendedor(client, app, tmp_path)
        _publicar(client)
        pub = Publicacion.query.one()                    # pendiente
        plan = PlanDestacado.query.first()
        client.post('/pagos/iniciar', data={'concepto': 'destacado', 'id': pub.id, 'metodo': 'transferencia',
                                            'plan_id': plan.id})
        assert Pago.query.count() == 0
        negociacion.publicar(pub, Decimal('20000'), Decimal('15'), True)
        db.session.commit()
        login(client, crear_usuario('otro@test.com'))
        assert client.get(f'/pagos/destacar/{pub.id}').status_code == 404

    def test_destacado_vencido_no_cuenta(self, client, app, tmp_path):
        v = _vendedor(client, app, tmp_path)
        _publicar(client)
        pub = Publicacion.query.one()
        pub.destacado_hasta = ahora_utc() - timedelta(minutes=1)
        assert pub.destacada is False


# ── Admin ─────────────────────────────────────────────────────────────────────

class TestAdminPagos:

    def test_planes_crud(self, admin_authenticated_client):
        c = admin_authenticated_client
        assert c.get('/admin/planes').status_code == 200
        c.post('/admin/planes', data={'nombre': 'Destacado 60 días', 'dias': '60', 'precio': '1500'})
        plan = PlanDestacado.query.filter_by(dias=60).one()
        assert plan.activo and plan.precio == Decimal('1500.00')
        c.post('/admin/planes', data={'id': plan.id, 'accion': 'alternar'})
        assert plan.activo is False
        c.post('/admin/planes', data={'nombre': 'x', 'dias': '0', 'precio': '10'})
        assert PlanDestacado.query.count() == 4

    def test_config_pagos(self, app, admin_authenticated_client):
        data = {'comision_default': '15', 'comision_minima': '5', 'comision_maxima': '30', 'itbis_porcentaje': '18',
                'AZUL_MERCHANT_ID': '123', 'AZUL_MERCHANT_NAME': 'BuscatodoRD', 'AZUL_AUTH_KEY': 'secreta-azul',
                'TRANSFERENCIA_INSTRUCCIONES': 'Banco BHD'}
        admin_authenticated_client.post('/admin/configuracion', data=data)
        assert svc.config_svc.itbis_porcentaje() == Decimal('18')
        fila = Configuracion.query.filter_by(clave='AZUL_AUTH_KEY').one()
        assert fila.valor.startswith('enc:') and 'secreta-azul' not in fila.valor
        assert app.config['AZUL_AUTH_KEY'] == 'secreta-azul' and azul.configurada()
        assert b'secreta-azul' not in admin_authenticated_client.get('/admin/configuracion').data

    def test_paginas(self, admin_authenticated_client):
        for url in ('/admin/pagos', '/admin/pagos?estado=todos', '/admin/planes', '/admin/dashboard'):
            assert admin_authenticated_client.get(url).status_code == 200, url


class TestCsrfEnVueltas:

    def test_cardnet_puede_volver_por_post_con_csrf_activo(self, client, app, tmp_path, monkeypatch):
        _configurar_cardnet(app)
        monkeypatch.setattr(cardnet.requests, 'post',
                            lambda url, json=None, timeout=None: _Resp({'SESSION': 'S1', 'session-key': 'K1'}))
        monkeypatch.setattr(cardnet.requests, 'get',
                            lambda url, params=None, timeout=None: _Resp({'ResponseCode': '00'}))
        _, comprador, _, trans = _venta(client, app, tmp_path)
        login(client, comprador)
        client.post('/pagos/iniciar', data={'concepto': 'venta', 'id': trans.id, 'metodo': 'cardnet'})
        pago = Pago.query.one()
        app.config['WTF_CSRF_ENABLED'] = True
        client.get('/auth/logout')
        r = client.post(f'/pagos/cardnet/vuelta/{pago.referencia}', data={'algo': '1'})
        assert r.status_code == 200 and pago.estado == 'aprobado'
