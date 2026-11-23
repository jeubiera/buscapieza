"""
Kit de promoción de la red: QR, frases e imágenes, y seguimiento de qué material trajo a cada registro.
"""
import io

import pytest

from extensions import db
from models import PromoPlantilla, Usuario
from services import promo
from services import referidos as svc
from tests.conftest import crear_usuario, login


def _registro(client, url='/auth/registro', **extra):
    data = {'nombre': 'Invitada Nueva', 'email': 'invitada@test.com', 'telefono': '809-555-1234',
            'password': 'NuevoPass123!', 'password2': 'NuevoPass123!', 'rol': 'cliente'}
    data.update(extra)
    return client.post(url, data=data)


class TestQR:

    def test_qr_es_png_con_el_enlace(self, client, cliente_user):
        login(client, cliente_user)
        r = client.get('/referidos/qr.png?p=qr')
        assert r.status_code == 200 and r.mimetype == 'image/png'
        assert r.data.startswith(b'\x89PNG')
        assert cliente_user.codigo_referido   # se generó el código al pedir el QR

    def test_qr_descargable(self, client, cliente_user):
        login(client, cliente_user)
        r = client.get('/referidos/qr.png?descargar=1')
        assert 'attachment' in r.headers['Content-Disposition']
        assert cliente_user.codigo_referido in r.headers['Content-Disposition']

    def test_qr_requiere_sesion(self, client):
        assert client.get('/referidos/qr.png').status_code == 302

    def test_qr_contiene_enlace_valido(self, app, cliente_user):
        with app.test_request_context():
            enlace = promo.enlace(cliente_user, 'qr')
        assert enlace.endswith(f'/auth/registro?ref={cliente_user.codigo_referido}&p=qr')

    def test_mi_red_muestra_qr_y_kit(self, client, cliente_user):
        login(client, cliente_user)
        html = client.get('/referidos').get_data(as_text=True)
        assert '/referidos/qr.png' in html and '/referidos/kit' in html


class TestKit:

    def test_kit_personaliza_frases(self, client, runner, cliente_user):
        runner.invoke(args=['seed'])
        login(client, cliente_user)
        html = client.get('/referidos/kit').get_data(as_text=True)
        codigo = cliente_user.codigo_referido
        assert '{link}' not in html and '{codigo}' not in html
        assert f'ref={codigo}&amp;p=f' in html       # las frases llevan su propio seguimiento
        assert 'Recomienda y gana' in html           # imágenes sembradas

    def test_kit_oculta_material_inactivo(self, client, cliente_user):
        PromoPlantilla.query.delete()
        db.session.add(PromoPlantilla(tipo='frase', texto='Visible {link}', activa=True))
        db.session.add(PromoPlantilla(tipo='frase', texto='Escondida {link}', activa=False))
        db.session.commit()
        login(client, cliente_user)
        html = client.get('/referidos/kit').get_data(as_text=True)
        assert 'Visible' in html and 'Escondida' not in html

    def test_personalizar(self, app, cliente_user):
        cliente_user.nombre = 'María Pérez'
        with app.test_request_context():
            txt = promo.personalizar('Hola, soy {nombre} ({codigo}): {link}', cliente_user, 'f3')
        assert txt.startswith('Hola, soy María (')
        assert txt.endswith(f'?ref={cliente_user.codigo_referido}&p=f3')

    def test_ref_valida(self):
        assert promo.ref_valida('F12') == 'f12'
        assert promo.ref_valida('<script>') is None
        assert promo.ref_valida('') is None

    def test_seed_promo_idempotente(self, runner):
        PromoPlantilla.query.delete()
        db.session.commit()
        runner.invoke(args=['seed'])
        n = PromoPlantilla.query.count()
        assert n == len(promo.FRASES_INICIALES) + len(promo.IMAGENES_INICIALES)
        runner.invoke(args=['seed'])
        assert PromoPlantilla.query.count() == n


class TestSeguimiento:

    def test_registro_guarda_material(self, client, cliente_user):
        codigo = svc.asegurar_codigo(cliente_user)
        db.session.commit()
        client.get(f'/auth/registro?ref={codigo}&p=i2')
        _registro(client)
        u = Usuario.query.filter_by(email='invitada@test.com').first()
        assert u.patrocinador_id == cliente_user.id
        assert u.plantilla_ref == 'i2'

    def test_material_sin_patrocinador_no_se_guarda(self, client):
        client.get('/auth/registro?ref=NOEXISTE&p=f1')
        _registro(client)
        u = Usuario.query.filter_by(email='invitada@test.com').first()
        assert u.patrocinador_id is None and u.plantilla_ref is None

    def test_material_invalido_se_ignora(self, client, cliente_user):
        codigo = svc.asegurar_codigo(cliente_user)
        db.session.commit()
        _registro(client, ref=codigo, p='<b>malo</b>')
        u = Usuario.query.filter_by(email='invitada@test.com').first()
        assert u.patrocinador_id == cliente_user.id and u.plantilla_ref is None

    def test_estadisticas(self, _db):
        crear_usuario('x1@test.com', plantilla_ref='qr')
        crear_usuario('x2@test.com', plantilla_ref='qr')
        crear_usuario('x3@test.com', plantilla_ref='f1')
        assert promo.estadisticas() == {'qr': 2, 'f1': 1}


class TestAdminPromo:

    @pytest.fixture(autouse=True)
    def _vacio(self, _db):
        PromoPlantilla.query.delete()
        db.session.commit()

    def test_lista(self, admin_authenticated_client, runner):
        runner.invoke(args=['seed'])
        r = admin_authenticated_client.get('/admin/promo')
        assert r.status_code == 200 and 'Recomienda y gana' in r.get_data(as_text=True)

    def test_cliente_no_entra(self, authenticated_client):
        assert authenticated_client.get('/admin/promo').status_code == 302

    def test_crear_frase(self, admin_authenticated_client):
        admin_authenticated_client.post('/admin/promo', data={'tipo': 'frase', 'categoria': 'vender',
                                                              'texto': 'Vende fácil: {link}'})
        p = PromoPlantilla.query.one()
        assert p.tipo == 'frase' and p.categoria == 'vender' and p.activa

    def test_frase_sin_link_rechazada(self, admin_authenticated_client):
        admin_authenticated_client.post('/admin/promo', data={'tipo': 'frase', 'texto': 'Sin enlace'})
        assert PromoPlantilla.query.count() == 0

    def test_crear_imagen_con_fondo(self, app, admin_authenticated_client, tmp_path):
        app.config['UPLOAD_FOLDER'] = str(tmp_path)
        png = promo.qr_png('x')
        admin_authenticated_client.post('/admin/promo', data={
            'tipo': 'imagen', 'titulo': 'Gran oferta', 'subtitulo': 'Sub', 'emoji': '🔥', 'color_ini': '#112233',
            'color_fin': 'rojo', 'con_qr': '1', 'categoria': 'xx', 'imagen': (io.BytesIO(png), 'fondo.png'),
        }, content_type='multipart/form-data')
        p = PromoPlantilla.query.one()
        assert p.tipo == 'imagen' and p.titulo == 'Gran oferta' and p.con_qr
        assert p.color_ini == '#112233' and p.color_fin == '#001838'   # color inválido → por defecto
        assert p.categoria == 'general'
        assert p.imagen_url

    def test_fondo_falso_rechazado(self, admin_authenticated_client):
        admin_authenticated_client.post('/admin/promo', data={
            'tipo': 'imagen', 'titulo': 'X', 'imagen': (io.BytesIO(b'no soy imagen'), 'fondo.png'),
        }, content_type='multipart/form-data')
        assert PromoPlantilla.query.count() == 0

    def test_editar_alternar_eliminar(self, admin_authenticated_client):
        p = PromoPlantilla(tipo='frase', texto='A {link}', activa=True)
        db.session.add(p)
        db.session.commit()
        admin_authenticated_client.post('/admin/promo', data={'id': p.id, 'tipo': 'imagen', 'texto': 'B {link}'})
        assert p.texto == 'B {link}' and p.tipo == 'frase'   # el tipo no cambia al editar
        admin_authenticated_client.post(f'/admin/promo/{p.id}/alternar')
        assert p.activa is False
        admin_authenticated_client.post(f'/admin/promo/{p.id}/eliminar')
        assert PromoPlantilla.query.count() == 0
