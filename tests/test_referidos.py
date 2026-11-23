"""
Programa de referidos: comisiones por compras de la red (mecánica del motor de AmbarERP).
"""
from datetime import datetime
from decimal import Decimal

import pytest

from extensions import db
from models import Usuario, Transaccion, ComisionReferido, CierreReferido, Interes, Publicacion, Pago
from services import referidos as svc
from tests.conftest import crear_usuario, login


# ── Utilidades ────────────────────────────────────────────────────────────────

def _activar(app, niveles='10,5,3', base='comision', meta='0', meses='2', minimo='500'):
    data = {'activo': '1', 'niveles': niveles, 'base': base, 'meta': meta, 'meses_arrastre': meses, 'minimo_pago': minimo}
    assert svc.guardar_config(data) is None


def _cadena():
    """a ← b ← c ← d  (d fue invitado por c, c por b, b por a)."""
    a = crear_usuario('a@test.com', nombre='Ana Alfa', telefono='8090000001')
    b = crear_usuario('b@test.com', nombre='Beto Beta', telefono='8090000002')
    c = crear_usuario('c@test.com', nombre='Carla Gama', telefono='8090000003')
    d = crear_usuario('d@test.com', nombre='Dani Delta', telefono='8090000004')
    for hijo, padre in ((b, a), (c, b), (d, c)):
        assert svc.asignar_patrocinador(hijo, svc.asegurar_codigo(padre))
    db.session.commit()
    return a, b, c, d


def _compra(comprador, vendedor=None, precio='23000', costo='20000', fecha=None, pagada=True):
    vendedor = vendedor or Usuario.query.filter_by(email='vendedor@test.com').first() or \
        crear_usuario('vendedor@test.com', nombre='Vendedor Uno')
    t = Transaccion(cliente_id=comprador.id, proveedor_id=vendedor.id, precio_proveedor=Decimal(costo),
                    precio_cliente=Decimal(precio), comision_broker=0, estado_pago='pagado' if pagada else 'pendiente',
                    fecha_pago=fecha or datetime(2026, 9, 15))
    t.calcular_comision()
    db.session.add(t)
    db.session.flush()
    return t


# ── Inscripción ───────────────────────────────────────────────────────────────

class TestInscripcion:

    def test_registro_por_enlace(self, client):
        a = crear_usuario('a@test.com', nombre='Ana Alfa')
        codigo = svc.asegurar_codigo(a)
        db.session.commit()
        client.get(f'/?ref={codigo.lower()}')                    # visita cualquier página con el enlace
        html = client.get('/auth/registro').get_data(as_text=True)
        assert 'Te invitó' in html and 'Ana A.' in html
        client.post('/auth/registro', data={'nombre': 'Nuevo Usuario', 'email': 'nuevo@test.com',
                                            'telefono': '809-555-0000', 'password': 'Clave12345',
                                            'password2': 'Clave12345', 'rol': 'cliente'})
        nuevo = Usuario.query.filter_by(email='nuevo@test.com').one()
        assert nuevo.patrocinador_id == a.id and nuevo.codigo_referido

    def test_codigo_invalido_o_propio(self, client, _db):
        u = crear_usuario('u@test.com')
        assert svc.asignar_patrocinador(u, 'NOEXISTE') is False
        assert svc.asignar_patrocinador(u, svc.asegurar_codigo(u)) is False
        assert u.patrocinador_id is None

    def test_sin_ciclos_y_una_sola_vez(self, _db):
        a, b, c, d = _cadena()
        assert svc.asignar_patrocinador(a, d.codigo_referido) is False   # a quedaría debajo de su propia red
        otro = crear_usuario('otro@test.com')
        assert svc.asignar_patrocinador(d, svc.asegurar_codigo(otro)) is False   # ya tiene patrocinador
        assert d.patrocinador_id == c.id

    def test_admin_no_patrocina(self, _db, admin_user):
        u = crear_usuario('u@test.com')
        assert svc.asignar_patrocinador(u, svc.asegurar_codigo(admin_user)) is False


# ── Generación ────────────────────────────────────────────────────────────────

class TestGeneracion:

    def test_desactivado_no_genera(self, _db):
        a, b, c, d = _cadena()
        assert svc.generar_comisiones(_compra(d)) == []

    def test_tres_niveles_sobre_la_comision(self, app, _db):
        _activar(app)
        a, b, c, d = _cadena()
        t = _compra(d)                                   # comisión de BuscatodoRD: 3,000
        creadas = svc.generar_comisiones(t)
        db.session.commit()
        montos = {x.beneficiario_id: (x.nivel, x.monto) for x in creadas}
        assert montos == {c.id: (1, Decimal('300.00')), b.id: (2, Decimal('150.00')), a.id: (3, Decimal('90.00'))}
        assert all(x.periodo == '2026-09' and x.vence_periodo == '2026-11' for x in creadas)
        assert svc.generar_comisiones(t) == []           # idempotente

    def test_base_precio_y_niveles_configurables(self, app, _db):
        _activar(app, niveles='3,2,1', base='precio')
        a, b, c, d = _cadena()
        creadas = svc.generar_comisiones(_compra(d))
        assert sorted(x.monto for x in creadas) == [Decimal('230.00'), Decimal('460.00'), Decimal('690.00')]

    def test_vendedor_e_inactivos_no_cobran(self, app, _db):
        _activar(app)
        a, b, c, d = _cadena()
        b.activo = False
        creadas = svc.generar_comisiones(_compra(d, vendedor=c))     # c es el vendedor
        assert [x.beneficiario_id for x in creadas] == [a.id]

    def test_sin_red_ni_pago_no_genera(self, app, _db):
        _activar(app)
        a, b, c, d = _cadena()
        assert svc.generar_comisiones(_compra(a)) == []                    # a no tiene patrocinador
        assert svc.generar_comisiones(_compra(d, pagada=False)) == []

    def test_validacion_config(self, app, _db):
        assert svc.guardar_config({'niveles': '60,50', 'base': 'comision'})
        assert svc.guardar_config({'niveles': '20,15', 'base': 'precio'})
        assert svc.guardar_config({'niveles': '1,1,1,1,1,1'})
        assert svc.guardar_config({'niveles': 'abc'})
        assert svc.config()['activo'] is False


# ── Integración con los pagos ─────────────────────────────────────────────────

class TestIntegracionPagos:

    def test_pago_por_transferencia_genera(self, client, app, tmp_path, admin_user):
        from services import negociacion, pagos
        from tests.test_ventas import _vendedor, _publicar
        _activar(app)
        a, b, c, d = _cadena()
        _vendedor(client, app, tmp_path)
        _publicar(client)
        pub = Publicacion.query.one()
        negociacion.publicar(pub, Decimal('20000'), Decimal('15'), True)
        it = Interes(publicacion_id=pub.id, comprador_id=d.id)
        db.session.add(it)
        db.session.flush()
        trans = negociacion.registrar_venta(pub, it, Decimal('23000'), Decimal('20000'))
        from models import Envio
        db.session.add(Envio(transaccion=trans, metodo='retiro', nombre_opcion='Retiro', costo=Decimal('0'),
                             destinatario='Dani', telefono='8090000004'))
        pago = pagos.crear_pago_venta(trans, d, 'transferencia')
        db.session.commit()
        login(client, admin_user)
        client.post(f'/admin/pago/{pago.id}/aprobar')
        assert trans.estado_pago == 'pagado'
        assert ComisionReferido.query.filter_by(transaccion_id=trans.id).count() == 3

    def test_pago_manual_del_admin_genera(self, client, app, admin_user):
        _activar(app)
        a, b, c, d = _cadena()
        t = _compra(d, pagada=False)
        db.session.commit()
        login(client, admin_user)
        client.post(f'/admin/transaccion/{t.id}/pagar', data={'metodo_pago': 'efectivo'})
        assert ComisionReferido.query.filter_by(transaccion_id=t.id).count() == 3


# ── Cierre mensual ────────────────────────────────────────────────────────────

class TestCierre:

    def test_sin_meta_todo_disponible(self, app, _db, admin_user):
        _activar(app)
        a, b, c, d = _cadena()
        svc.generar_comisiones(_compra(d))
        cierre = svc.cerrar_periodo('2026-09', admin_user)
        db.session.commit()
        assert cierre.disponibles == 3 and ComisionReferido.query.filter_by(estado='disponible').count() == 3
        with pytest.raises(svc.ErrorReferidos):
            svc.cerrar_periodo('2026-09')                        # no dos veces
        with pytest.raises(svc.ErrorReferidos):
            svc.cerrar_periodo(svc.periodo_de(None))             # ni el mes en curso

    def test_meta_arrastre_y_vencimiento(self, app, _db):
        _activar(app, meta='4000', meses='2')
        a, b, c, d = _cadena()
        svc.generar_comisiones(_compra(d, fecha=datetime(2026, 6, 10)))     # comisiones de junio (vencen en agosto)
        _compra(c, precio='5000', costo='4500', fecha=datetime(2026, 6, 20))  # c compra RD$5,000 en junio: califica
        db.session.commit()

        svc.cerrar_periodo('2026-06')
        estados = {x.beneficiario_id: x.estado for x in ComisionReferido.query.all()}
        assert estados == {c.id: 'disponible', b.id: 'acumulada', a.id: 'acumulada'}

        _compra(b, precio='4000', costo='3500', fecha=datetime(2026, 7, 5))   # b califica en julio
        db.session.commit()
        svc.cerrar_periodo('2026-07')
        estados = {x.beneficiario_id: x.estado for x in ComisionReferido.query.all()}
        assert estados[b.id] == 'disponible' and estados[a.id] == 'acumulada'

        svc.cerrar_periodo('2026-08')                                         # a nunca calificó: vence
        assert ComisionReferido.query.filter_by(beneficiario_id=a.id).one().estado == 'vencida'

    def test_cli(self, app, runner):
        _activar(app)
        a, b, c, d = _cadena()
        svc.generar_comisiones(_compra(d))
        db.session.commit()
        r = runner.invoke(args=['cerrar-referidos', '--periodo', '2026-09'])
        assert '3 disponibles' in r.output
        assert CierreReferido.query.filter_by(periodo='2026-09').one()


# ── Liquidación y reversión ───────────────────────────────────────────────────

class TestLiquidacion:

    def _disponibles(self, app, admin_user):
        _activar(app, minimo='500')
        a, b, c, d = _cadena()
        svc.generar_comisiones(_compra(d))
        svc.generar_comisiones(_compra(d, precio='46000', costo='40000'))     # c gana 300 + 600
        svc.cerrar_periodo('2026-09', admin_user)
        db.session.commit()
        return a, b, c, d

    def test_liquidar_y_minimo(self, client, app, admin_user):
        a, b, c, d = self._disponibles(app, admin_user)
        assert svc.saldo(c.id)['disponible'] == Decimal('900.00')
        login(client, admin_user)
        html = client.get('/admin/referidos').get_data(as_text=True)
        assert 'Carla Gama' in html and '900.00' in html
        client.post(f'/admin/referidos/liquidar/{c.id}', data={'metodo': 'transferencia', 'referencia': 'TRF-1'})
        assert svc.saldo(c.id)['disponible'] == 0 and svc.saldo(c.id)['pagada'] == Decimal('900.00')
        # a tiene 270 < mínimo 500: no se paga salvo que se fuerce
        client.post(f'/admin/referidos/liquidar/{a.id}', data={'metodo': 'transferencia'})
        assert svc.saldo(a.id)['pagada'] == 0
        client.post(f'/admin/referidos/liquidar/{a.id}', data={'metodo': 'efectivo', 'forzar': '1'})
        assert svc.saldo(a.id)['pagada'] == Decimal('270.00')

    def test_reversar(self, client, app, admin_user):
        a, b, c, d = self._disponibles(app, admin_user)
        com = ComisionReferido.query.filter_by(beneficiario_id=b.id).first()
        login(client, admin_user)
        client.post(f'/admin/comision-referido/{com.id}/reversar')
        assert com.estado == 'reversada'
        svc.liquidar(c, admin_user)
        db.session.commit()
        pagada = ComisionReferido.query.filter_by(beneficiario_id=c.id).first()
        with pytest.raises(svc.ErrorReferidos):
            svc.reversar(pagada)


# ── Páginas ───────────────────────────────────────────────────────────────────

class TestPaginas:

    def test_mi_red_privacidad(self, client, app):
        _activar(app)
        a, b, c, d = _cadena()
        svc.generar_comisiones(_compra(d))
        db.session.commit()
        login(client, b)
        html = client.get('/referidos').get_data(as_text=True)
        assert b.codigo_referido in html and f'ref={b.codigo_referido}' in html
        assert 'Carla G.' in html and 'Dani D.' in html and 'Ana A.' in html      # red y patrocinador
        for privado in ('8090000003', '8090000004', 'c@test.com', 'd@test.com', 'Carla Gama'):
            assert privado not in html
        assert '150.00' in html

    def test_codigo_se_crea_al_entrar(self, client):
        u = crear_usuario('nuevo@test.com')
        assert u.codigo_referido is None
        login(client, u)
        assert client.get('/referidos').status_code == 200
        assert u.codigo_referido and len(u.codigo_referido) == 7

    def test_admin_config_por_formulario(self, app, admin_authenticated_client):
        r = admin_authenticated_client.post('/admin/referidos', data={'activo': '1', 'niveles': '8,4', 'base': 'comision',
                                                                      'meta': '0', 'meses_arrastre': '1', 'minimo_pago': '300'})
        assert r.status_code == 302
        cfg = svc.config()
        assert cfg['activo'] and cfg['niveles'] == [Decimal('8'), Decimal('4')] and cfg['minimo_pago'] == Decimal('300')
        assert admin_authenticated_client.get('/admin/referidos').status_code == 200
        assert admin_authenticated_client.get('/admin/dashboard').status_code == 200
