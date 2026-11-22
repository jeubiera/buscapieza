"""
Tests para el módulo de solicitudes
"""
import io

from models import Solicitud, Categoria, Provincia, SolicitudFoto
from tests.conftest import crear_usuario, crear_solicitud, login


def _datos(**override):
    data = {
        'titulo': 'Busco alternador',
        'descripcion': 'Necesito alternador para Toyota Corolla 2015',
        'categoria_id': Categoria.query.first().id,
        'provincia_id': Provincia.query.first().id,
        'presupuesto': '5000',
        'urgencia': 'urgente',
    }
    data.update(override)
    return data


PNG_1PX = (b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00'
           b'\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00'
           b'\x00\x00\x00IEND\xaeB`\x82')


class TestCrearSolicitud:

    def test_acceso_formulario_nueva_solicitud(self, authenticated_client):
        assert authenticated_client.get('/solicitudes/nueva').status_code == 200

    def test_crear_solicitud_basica(self, authenticated_client, cliente_user):
        response = authenticated_client.post('/solicitudes/nueva', data=_datos())
        assert response.status_code == 302
        sol = Solicitud.query.filter_by(titulo='Busco alternador').first()
        assert sol is not None
        assert sol.cliente_id == cliente_user.id
        assert sol.estado == 'pendiente'
        assert sol.urgencia == 'urgente'
        assert sol.codigo.startswith('BP-')
        assert float(sol.presupuesto) == 5000

    def test_solicitud_sin_presupuesto(self, authenticated_client):
        authenticated_client.post('/solicitudes/nueva', data=_datos(presupuesto=''))
        assert Solicitud.query.first().presupuesto is None

    def test_urgencia_invalida_usa_normal(self, authenticated_client):
        authenticated_client.post('/solicitudes/nueva', data=_datos(urgencia='media'))
        assert Solicitud.query.first().urgencia == 'normal'

    def test_titulo_requerido(self, authenticated_client):
        response = authenticated_client.post('/solicitudes/nueva', data=_datos(titulo=''))
        assert response.status_code == 400
        assert Solicitud.query.count() == 0

    def test_presupuesto_invalido(self, authenticated_client):
        response = authenticated_client.post('/solicitudes/nueva', data=_datos(presupuesto='abc'))
        assert response.status_code == 400
        assert Solicitud.query.count() == 0

    def test_proveedor_no_puede_publicar(self, proveedor_client):
        proveedor_client.post('/solicitudes/nueva', data=_datos())
        assert Solicitud.query.count() == 0

    def test_foto_valida_se_guarda_y_falsa_se_rechaza(self, authenticated_client, app, tmp_path):
        app.config['UPLOAD_FOLDER'] = str(tmp_path)
        data = _datos()
        data['fotos'] = [
            (io.BytesIO(PNG_1PX), 'pieza.png'),
            (io.BytesIO(b'<html><script>alert(1)</script>'), 'falsa.jpg'),
        ]
        authenticated_client.post('/solicitudes/nueva', data=data, content_type='multipart/form-data')
        fotos = SolicitudFoto.query.all()
        assert len(fotos) == 1
        assert fotos[0].es_principal


class TestListarSolicitudes:

    def test_cliente_ve_sus_solicitudes(self, authenticated_client, solicitud):
        response = authenticated_client.get('/solicitudes/mis-solicitudes')
        assert response.status_code == 200
        assert solicitud.codigo.encode() in response.data

    def test_home_publica(self, client, solicitud):
        assert client.get('/').status_code == 200

    def test_buscar_publico(self, client, solicitud):
        response = client.get('/solicitudes/buscar?q=alternador')
        assert response.status_code == 200
        assert b'Busco alternador' in response.data
        # No expone datos del cliente
        assert b'cliente@test.com' not in response.data

    def test_buscar_oculta_cerradas_al_publico(self, client, cliente_user):
        crear_solicitud(cliente_user, titulo='Cerrada vieja', estado='completada')
        response = client.get('/solicitudes/buscar?estado=completada')
        assert b'Cerrada vieja' not in response.data

    def test_buscar_admin_filtra_por_estado(self, admin_authenticated_client, cliente_user):
        crear_solicitud(cliente_user, titulo='Cerrada vieja', estado='completada')
        response = admin_authenticated_client.get('/solicitudes/buscar?estado=completada')
        assert b'Cerrada vieja' in response.data


class TestDetalleSolicitud:

    def test_ver_detalle_solicitud(self, authenticated_client, solicitud):
        response = authenticated_client.get(f'/solicitudes/{solicitud.id}')
        assert response.status_code == 200
        assert solicitud.codigo.encode() in response.data

    def test_otro_cliente_no_ve_detalle(self, client, solicitud):
        otro = crear_usuario('otro@test.com')
        login(client, otro)
        response = client.get(f'/solicitudes/{solicitud.id}')
        assert response.status_code == 302


class TestEstadosSolicitud:

    def test_solicitud_nueva_estado_pendiente(self, solicitud):
        assert solicitud.estado == 'pendiente'
        assert solicitud.acepta_ofertas

    def test_admin_cambia_estado(self, admin_authenticated_client, solicitud):
        admin_authenticated_client.post(f'/admin/solicitud/{solicitud.id}/estado',
                                        data={'estado': 'cancelada', 'notas_admin': 'x'})
        assert solicitud.estado == 'cancelada'
        assert not solicitud.acepta_ofertas

    def test_admin_estado_invalido_rechazado(self, admin_authenticated_client, solicitud):
        admin_authenticated_client.post(f'/admin/solicitud/{solicitud.id}/estado', data={'estado': 'hackeado'})
        assert solicitud.estado == 'pendiente'
