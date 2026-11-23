"""
Envíos: el comprador elige la entrega → paga (precio + envío) → el vendedor despacha con foto y guía →
el comprador confirma (o se confirma solo) → el admin le paga al vendedor.
"""
import io
from datetime import timedelta
from decimal import Decimal

import pytest

from extensions import db
from models import Envio, TarifaEnvio, Pago, Interes, Publicacion, Provincia, AvisoAdmin, ahora_utc
from services import envios as svc, negociacion
from tests.conftest import crear_usuario, login
from tests.test_solicitudes import PNG_1PX
from tests.test_ventas import _vendedor, _publicar


def _venta(client, app, tmp_path):
    """Venta pendiente de pago, todavía sin forma de entrega."""
    v = _vendedor(client, app, tmp_path)
    _publicar(client)
    pub = Publicacion.query.one()
    negociacion.publicar(pub, Decimal('20000'), Decimal('15'), True)
    comprador = crear_usuario('comprador@test.com', nombre='Ana Compradora', telefono='8095551234')
    it = Interes(publicacion_id=pub.id, comprador_id=comprador.id)
    db.session.add(it)
    db.session.flush()
    trans = negociacion.registrar_venta(pub, it, Decimal('23000'), Decimal('20000'))
    db.session.commit()
    return v, comprador, trans


def _tarifa(metodo):
    return TarifaEnvio.query.filter_by(metodo=metodo).first()


def _elegir(client, trans, metodo='courier', **extra):
    datos = {'tarifa_id': _tarifa(metodo).id, 'destinatario': 'Ana Compradora', 'telefono': '809-555-1234',
             'provincia_id': Provincia.query.first().id, 'direccion': 'Calle Duarte 25, Centro', 'indicaciones': ''}
    datos.update(extra)
    return client.post(f'/envios/compra/{trans.id}/entrega', data=datos)


def _pagar_transferencia(client, admin, comprador, trans):
    login(client, comprador)
    client.post('/pagos/iniciar', data={'concepto': 'venta', 'id': trans.id, 'metodo': 'transferencia'})
    pago = Pago.query.filter_by(transaccion_id=trans.id).order_by(Pago.id.desc()).first()
    client.post(f'/pagos/{pago.referencia}/comprobante',
                data={'comprobante': (io.BytesIO(b'%PDF-1.4 recibo'), 'recibo.pdf')}, content_type='multipart/form-data')
    login(client, admin)
    client.post(f'/admin/pago/{pago.id}/aprobar')
    return pago


def _despachar(client, vendedor, env, **extra):
    login(client, vendedor)
    datos = {'empresa': 'Vimenpaq', 'guia': 'VP-123456', 'foto': (io.BytesIO(PNG_1PX), 'pieza.png')}
    datos.update(extra)
    return client.post(f'/envios/{env.id}/despachar', data=datos, content_type='multipart/form-data')


@pytest.fixture
def tarifas(_db):
    svc.sembrar_tarifas()
    db.session.commit()


class TestElegirEntrega:

    def test_pagar_pide_primero_la_entrega(self, client, app, tmp_path, tarifas):
        _, comprador, trans = _venta(client, app, tmp_path)
        login(client, comprador)
        r = client.get(f'/pagos/venta/{trans.id}')
        assert r.status_code == 302 and f'/envios/compra/{trans.id}/entrega' in r.headers['Location']
        assert 'Courier a domicilio' in client.get(r.headers['Location']).get_data(as_text=True)

    def test_no_se_puede_pagar_sin_entrega(self, client, app, tmp_path, tarifas):
        _, comprador, trans = _venta(client, app, tmp_path)
        login(client, comprador)
        client.post('/pagos/iniciar', data={'concepto': 'venta', 'id': trans.id, 'metodo': 'transferencia'})
        assert Pago.query.count() == 0

    def test_el_envio_se_suma_al_pago(self, client, app, tmp_path, tarifas):
        _, comprador, trans = _venta(client, app, tmp_path)
        login(client, comprador)
        r = _elegir(client, trans, 'courier')
        assert f'/pagos/venta/{trans.id}' in r.headers['Location']
        env = trans.envio
        assert env.estado == 'pendiente_pago' and env.costo == Decimal('500')
        html = client.get(f'/pagos/venta/{trans.id}').get_data(as_text=True)
        assert 'RD$23,500.00' in html
        client.post('/pagos/iniciar', data={'concepto': 'venta', 'id': trans.id, 'metodo': 'transferencia'})
        assert Pago.query.one().monto == Decimal('23500.00')

    def test_domicilio_exige_direccion(self, client, app, tmp_path, tarifas):
        _, comprador, trans = _venta(client, app, tmp_path)
        login(client, comprador)
        _elegir(client, trans, 'mensajero', direccion='')
        assert trans.envio is None

    def test_retiro_no_pide_direccion(self, client, app, tmp_path, tarifas):
        _, comprador, trans = _venta(client, app, tmp_path)
        login(client, comprador)
        _elegir(client, trans, 'retiro', direccion='', provincia_id='')
        assert trans.envio.costo == 0 and trans.envio.direccion is None

    def test_solo_el_comprador_elige(self, client, app, tmp_path, tarifas):
        v, _, trans = _venta(client, app, tmp_path)
        login(client, v)
        assert _elegir(client, trans).status_code == 404

    def test_cambiar_entrega_anula_pago_pendiente(self, client, app, tmp_path, tarifas):
        _, comprador, trans = _venta(client, app, tmp_path)
        login(client, comprador)
        _elegir(client, trans, 'retiro')
        client.post('/pagos/iniciar', data={'concepto': 'venta', 'id': trans.id, 'metodo': 'transferencia'})
        pago = Pago.query.one()
        _elegir(client, trans, 'courier')
        assert pago.estado == 'cancelado' and trans.envio.metodo == 'courier'

    def test_flete_se_cotiza_antes_de_pagar(self, client, app, tmp_path, tarifas, admin_user):
        _, comprador, trans = _venta(client, app, tmp_path)
        login(client, comprador)
        _elegir(client, trans, 'flete')
        env = trans.envio
        assert env.estado == 'por_cotizar' and env.costo is None
        assert AvisoAdmin.query.filter(AvisoAdmin.titulo.like('Envío por cotizar%')).count() == 1
        assert '/envios/' in client.get(f'/pagos/venta/{trans.id}').headers['Location']
        login(client, admin_user)
        client.post(f'/admin/envio/{env.id}/cotizar', data={'costo': '2500'})
        assert env.estado == 'pendiente_pago' and env.costo == Decimal('2500')


class TestDespachoYEntrega:

    def _pagada(self, client, app, tmp_path, admin):
        v, comprador, trans = _venta(client, app, tmp_path)
        login(client, comprador)
        _elegir(client, trans, 'courier')
        _pagar_transferencia(client, admin, comprador, trans)
        return v, comprador, trans, trans.envio

    def test_al_pagar_queda_por_despachar(self, client, app, tmp_path, tarifas, admin_user):
        *_, trans, env = self._pagada(client, app, tmp_path, admin_user)
        assert trans.estado_pago == 'pagado' and env.estado == 'por_despachar' and env.pagado_en

    def test_vendedor_no_ve_el_envio_antes_del_pago(self, client, app, tmp_path, tarifas):
        v, comprador, trans = _venta(client, app, tmp_path)
        login(client, comprador)
        _elegir(client, trans, 'courier')
        login(client, v)
        assert client.get(f'/envios/{trans.envio.id}').status_code == 404

    def test_vendedor_no_ve_telefono_del_comprador(self, client, app, tmp_path, tarifas, admin_user):
        v, _, _, env = self._pagada(client, app, tmp_path, admin_user)
        login(client, v)
        html = client.get(f'/envios/{env.id}').get_data(as_text=True)
        assert 'Ana Compradora' in html and 'Calle Duarte' in html
        assert '809-555-1234' not in html and '8095551234' not in html

    def test_otro_usuario_no_ve_el_envio(self, client, app, tmp_path, tarifas, admin_user):
        *_, env = self._pagada(client, app, tmp_path, admin_user)
        login(client, crear_usuario('curioso@test.com'))
        assert client.get(f'/envios/{env.id}').status_code == 404

    def test_despacho_exige_foto_y_guia(self, client, app, tmp_path, tarifas, admin_user):
        v, _, _, env = self._pagada(client, app, tmp_path, admin_user)
        _despachar(client, v, env, foto=(io.BytesIO(b''), ''))
        assert env.estado == 'por_despachar'
        _despachar(client, v, env, guia='')
        assert env.estado == 'por_despachar'
        _despachar(client, v, env)
        assert env.estado == 'despachado' and env.guia == 'VP-123456' and env.foto_url and env.despachado_en

    def test_comprador_confirma_y_se_paga_al_vendedor(self, client, app, tmp_path, tarifas, admin_user):
        v, comprador, trans, env = self._pagada(client, app, tmp_path, admin_user)
        login(client, admin_user)
        client.post(f'/admin/transaccion/{trans.id}/pagar-vendedor', data={'metodo': 'transferencia'})
        assert trans.vendedor_pagado_en is None          # todavía no lo recibe nadie
        _despachar(client, v, env)
        login(client, comprador)
        client.post(f'/envios/{env.id}/recibido')
        assert env.estado == 'entregado' and env.confirmado_por == 'comprador'
        assert AvisoAdmin.query.filter(AvisoAdmin.titulo.like('Entregado%')).count() == 1
        login(client, admin_user)
        assert 'Pagar al vendedor' in client.get('/admin/envios?estado=por_pagar').get_data(as_text=True)
        client.post(f'/admin/transaccion/{trans.id}/pagar-vendedor', data={'metodo': 'transferencia', 'referencia': 'TRF-1'})
        assert trans.vendedor_pagado_en and trans.vendedor_pago_ref == 'TRF-1'
        client.post(f'/admin/transaccion/{trans.id}/pagar-vendedor', data={'metodo': 'transferencia'})
        assert trans.vendedor_pago_ref == 'TRF-1'        # no se paga dos veces

    def test_pago_forzado_al_vendedor(self, client, app, tmp_path, tarifas, admin_user):
        *_, trans, _ = self._pagada(client, app, tmp_path, admin_user)
        login(client, admin_user)
        client.post(f'/admin/transaccion/{trans.id}/pagar-vendedor', data={'metodo': 'efectivo', 'forzar': '1'})
        assert trans.vendedor_pagado_en is not None

    def test_reclamo_retiene_el_pago(self, client, app, tmp_path, tarifas, admin_user):
        v, comprador, trans, env = self._pagada(client, app, tmp_path, admin_user)
        _despachar(client, v, env)
        login(client, comprador)
        client.post(f'/envios/{env.id}/reclamar', data={'reclamo': 'corto'})
        assert env.estado == 'despachado'
        client.post(f'/envios/{env.id}/reclamar', data={'reclamo': 'Llegó una pieza distinta a la publicada'})
        assert env.estado == 'reclamado'
        assert not svc.puede_pagar_vendedor(trans)
        assert client.post(f'/envios/{env.id}/recibido').status_code == 302 and env.estado == 'reclamado'
        login(client, admin_user)
        client.post(f'/admin/envio/{env.id}/resolver', data={'resolucion': 'El vendedor cambió la pieza', 'accion': 'entregar'})
        assert env.estado == 'entregado' and env.confirmado_por == 'admin' and svc.puede_pagar_vendedor(trans)

    def test_reclamo_con_devolucion(self, client, app, tmp_path, tarifas, admin_user):
        v, comprador, trans, env = self._pagada(client, app, tmp_path, admin_user)
        _despachar(client, v, env)
        login(client, comprador)
        client.post(f'/envios/{env.id}/reclamar', data={'reclamo': 'Nunca llegó el paquete a la terminal'})
        login(client, admin_user)
        client.post(f'/admin/envio/{env.id}/resolver', data={'resolucion': 'Se devolvió el dinero', 'accion': 'cancelar'})
        assert env.estado == 'cancelado' and not svc.puede_pagar_vendedor(trans)

    def test_confirmacion_automatica(self, client, app, tmp_path, tarifas, admin_user):
        v, _, trans, env = self._pagada(client, app, tmp_path, admin_user)
        _despachar(client, v, env)
        assert svc.confirmar_vencidos() == []
        env.despachado_en = ahora_utc() - timedelta(hours=svc.horas_confirmacion() + 1)
        db.session.commit()
        assert svc.confirmar_vencidos() == [env]
        assert env.estado == 'entregado' and env.confirmado_por == 'automatico'

    def test_pago_manual_del_admin_tambien_activa_el_despacho(self, client, app, tmp_path, tarifas, admin_user):
        _, comprador, trans = _venta(client, app, tmp_path)
        login(client, comprador)
        _elegir(client, trans, 'retiro')
        login(client, admin_user)
        client.post(f'/admin/transaccion/{trans.id}/pagar', data={'metodo_pago': 'efectivo'})
        assert trans.envio.estado == 'por_despachar'

    def test_pendientes_en_la_campanita(self, client, app, tmp_path, tarifas, admin_user):
        self._pagada(client, app, tmp_path, admin_user)
        textos = {t: n for _, t, n, _ in __import__('services.avisos', fromlist=['x']).pendientes()}
        assert textos['venta(s) por despachar'] == 1

    def test_mis_envios(self, client, app, tmp_path, tarifas, admin_user):
        v, comprador, _, _ = self._pagada(client, app, tmp_path, admin_user)
        login(client, v)
        assert 'Despachar' in client.get('/envios/mis-envios').get_data(as_text=True)
        login(client, comprador)
        assert 'Por despachar' in client.get('/envios/mis-envios').get_data(as_text=True)


class TestTarifas:

    def test_sembradas(self, tarifas):
        assert TarifaEnvio.query.count() == len(svc.TARIFAS_INICIALES)
        assert _tarifa('flete').a_cotizar

    def test_crear_editar_ocultar(self, admin_authenticated_client, tarifas):
        c = admin_authenticated_client
        c.post('/admin/envios/tarifas', data={'nombre': 'Mensajero — La Romana', 'metodo': 'mensajero', 'precio': '300',
                                              'pide_direccion': '1'})
        t = TarifaEnvio.query.filter_by(nombre='Mensajero — La Romana').one()
        assert t.precio == Decimal('300') and t.activa and t.pide_direccion
        c.post('/admin/envios/tarifas', data={'id': t.id, 'nombre': 'Mensajero — La Romana', 'metodo': 'mensajero',
                                              'a_cotizar': '1'})
        assert t.a_cotizar
        c.post('/admin/envios/tarifas', data={'id': t.id, 'accion': 'alternar'})
        assert not t.activa and t not in svc.tarifas_activas()

    def test_horas_de_confirmacion(self, admin_authenticated_client, tarifas):
        admin_authenticated_client.post('/admin/envios/tarifas', data={'accion': 'horas', 'horas': '48'})
        assert svc.horas_confirmacion() == 48
        admin_authenticated_client.post('/admin/envios/tarifas', data={'accion': 'horas', 'horas': '2'})
        assert svc.horas_confirmacion() == 48

    def test_cliente_no_entra(self, authenticated_client):
        assert authenticated_client.get('/admin/envios').status_code == 302
