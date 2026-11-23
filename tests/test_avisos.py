"""
Campanita del admin: avisos de pagos, publicaciones nuevas, etc. y resumen de lo pendiente.
"""
import io
from datetime import timedelta

from extensions import db
from models import AvisoAdmin, Pago, Publicacion, ahora_utc
from services import avisos
from tests.conftest import crear_usuario, login
from tests.test_pagos import _venta
from tests.test_ventas import _vendedor, _publicar


class TestRegistroDeAvisos:

    def test_nueva_publicacion_genera_aviso(self, client, app, tmp_path):
        _vendedor(client, app, tmp_path)
        _publicar(client)
        pub = Publicacion.query.one()
        a = AvisoAdmin.query.filter_by(tipo='publicacion').one()
        assert pub.codigo in a.titulo and a.url == f'/admin/publicacion/{pub.id}'

    def test_comprobante_de_pago_genera_aviso(self, client, app, tmp_path):
        _, comprador, _, trans = _venta(client, app, tmp_path)
        login(client, comprador)
        client.post('/pagos/iniciar', data={'concepto': 'venta', 'id': trans.id, 'metodo': 'transferencia'})
        pago = Pago.query.one()
        client.post(f'/pagos/{pago.referencia}/comprobante',
                    data={'comprobante': (io.BytesIO(b'%PDF-1.4 recibo'), 'recibo.pdf')}, content_type='multipart/form-data')
        a = AvisoAdmin.query.filter_by(tipo='pago').one()
        assert pago.referencia in a.titulo and 'verificar' in a.titulo

    def test_pago_con_tarjeta_genera_aviso(self, client, app, tmp_path):
        from services.notificaciones import tarea_pago
        _, comprador, _, trans = _venta(client, app, tmp_path)
        pago = Pago(concepto='venta', transaccion_id=trans.id, usuario_id=comprador.id, metodo='azul',
                    subtotal=trans.precio_cliente, monto=trans.precio_cliente, estado='aprobado')
        db.session.add(pago)
        db.session.flush()
        pago.generar_referencia()
        db.session.commit()
        tarea_pago(pago.id, 'aprobado_pasarela')
        assert 'tarjeta aprobado' in AvisoAdmin.query.filter_by(tipo='pago').one().titulo

    def test_nuevo_proveedor_genera_aviso(self, client):
        client.post('/auth/registro', data={'nombre': 'Repuestos Juan', 'email': 'juan@test.com', 'telefono': '809-555-1111',
                                            'password': 'NuevoPass123!', 'password2': 'NuevoPass123!',
                                            'rol': 'proveedor', 'empresa': 'Repuestos Juan SRL'})
        a = AvisoAdmin.query.filter_by(tipo='proveedor').one()
        assert 'Repuestos Juan SRL' in a.detalle

    def test_registrar_no_rompe_si_falla(self, app, monkeypatch):
        monkeypatch.setattr(db.session, 'commit', lambda: (_ for _ in ()).throw(RuntimeError('bd caída')))
        avisos.registrar('x', '❗', 'Prueba')   # no lanza


class TestCampanita:

    def test_sin_ver_y_marcar_vistos(self, admin_user):
        avisos.registrar('pago', '🧾', 'Uno')
        avisos.registrar('pago', '🧾', 'Dos')
        assert avisos.sin_ver(admin_user) == 2
        avisos.marcar_vistos(admin_user)
        assert avisos.sin_ver(admin_user) == 0
        avisos.registrar('pago', '🧾', 'Tres')
        assert avisos.sin_ver(admin_user) == 1

    def test_avisos_viejos_no_cuentan(self, admin_user):
        db.session.add(AvisoAdmin(tipo='x', titulo='Viejo', created_at=ahora_utc() - timedelta(days=60)))
        db.session.commit()
        assert avisos.sin_ver(admin_user) == 0

    def test_pendientes(self, client, app, tmp_path):
        _vendedor(client, app, tmp_path)
        _publicar(client)
        crear_usuario('prov@test.com', rol='proveedor', verificado=False)
        textos = {texto: n for _, texto, n, _ in avisos.pendientes()}
        assert textos['publicación(es) por aprobar'] == 1
        assert textos['proveedor(es) por verificar'] == 1
        assert 'pago(s) por verificar' not in textos      # solo aparece lo que tiene algo

    def test_campanita_en_el_menu_del_admin(self, admin_authenticated_client):
        avisos.registrar('pago', '🧾', 'Comprobante por verificar PG-1')
        html = admin_authenticated_client.get('/admin/dashboard').get_data(as_text=True)
        assert 'id="campanitaBtn"' in html and 'id="campanitaNum" >1<' in html.replace('\n', '')

    def test_campanita_no_aparece_a_clientes(self, authenticated_client):
        html = authenticated_client.get('/solicitudes/mis-solicitudes').get_data(as_text=True)
        assert 'campanitaBtn' not in html

    def test_panel_resumen_y_vistos(self, admin_authenticated_client, admin_user):
        avisos.registrar('publicacion', '🏷️', 'Publicación por aprobar VT-1', 'Nevera', '/admin/publicacion/1')
        assert admin_authenticated_client.get('/admin/avisos/resumen').get_json()['sin_ver'] == 1
        html = admin_authenticated_client.get('/admin/avisos/panel').get_data(as_text=True)
        assert 'Publicación por aprobar VT-1' in html and 'nuevo' in html
        admin_authenticated_client.post('/admin/avisos/vistos')
        assert admin_authenticated_client.get('/admin/avisos/resumen').get_json()['sin_ver'] == 0

    def test_pagina_de_avisos(self, admin_authenticated_client, admin_user):
        avisos.registrar('pago', '💳', 'Pago con tarjeta aprobado PG-9')
        r = admin_authenticated_client.get('/admin/avisos')
        assert r.status_code == 200 and 'PG-9' in r.get_data(as_text=True)
        assert avisos.sin_ver(admin_user) == 0

    def test_cliente_no_accede(self, authenticated_client):
        assert authenticated_client.get('/admin/avisos/resumen').status_code == 302
