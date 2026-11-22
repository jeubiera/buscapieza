"""
Pagos en línea (Fase 3): ventas que paga el comprador y destacados que paga el vendedor.

Métodos: transferencia (el cliente sube el comprobante y el admin lo verifica), Azul y CardNet.
Todas las reglas viven aquí para que las rutas de usuario, admin y pasarelas se comporten igual.

ITBIS (configurable, 0 por defecto hasta que el contador lo confirme):
  venta     → se calcula sobre la comisión de BuscatodoRD y se suma al total del comprador
  destacado → se calcula sobre el precio del plan
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import current_app

from extensions import db
from models import Pago, Destacado, PlanDestacado, Transaccion, ahora_utc
from services import config_svc

CENTAVO = Decimal('0.01')


class ErrorPago(Exception):
    pass


def _redondear(d) -> Decimal:
    return Decimal(d).quantize(CENTAVO, ROUND_HALF_UP)


def calcular_itbis(base) -> Decimal:
    return _redondear(Decimal(base) * config_svc.itbis_porcentaje() / 100)


def montos_venta(trans: Transaccion) -> dict:
    subtotal = _redondear(trans.precio_cliente)
    itbis = calcular_itbis(trans.comision_broker or 0)
    return {'subtotal': subtotal, 'itbis': itbis, 'monto': subtotal + itbis}


def montos_destacado(precio) -> dict:
    subtotal = _redondear(precio)
    itbis = calcular_itbis(subtotal)
    return {'subtotal': subtotal, 'itbis': itbis, 'monto': subtotal + itbis}


def metodos_disponibles() -> list:
    from services.pasarelas import azul, cardnet
    metodos = ['transferencia']
    if azul.configurada():
        metodos.append('azul')
    if cardnet.configurada():
        metodos.append('cardnet')
    return metodos


def _cancelar_pendientes(consulta):
    for p in consulta.filter(Pago.estado == 'pendiente').all():
        p.estado = 'cancelado'


# ── Crear ─────────────────────────────────────────────────────────────────────

def crear_pago_venta(trans: Transaccion, usuario, metodo: str) -> Pago:
    if trans.cliente_id != usuario.id:
        raise ErrorPago('Esta compra no es tuya')
    if trans.estado_pago != 'pendiente':
        raise ErrorPago('Esta compra ya está pagada o cancelada')
    if metodo not in metodos_disponibles():
        raise ErrorPago('Forma de pago no disponible')
    if trans.pagos.filter(Pago.estado == 'en_revision').first():
        raise ErrorPago('Ya enviaste un comprobante; lo estamos revisando')
    _cancelar_pendientes(trans.pagos)
    pago = Pago(concepto='venta', transaccion=trans, usuario_id=usuario.id, metodo=metodo, **montos_venta(trans))
    db.session.add(pago)
    db.session.flush()
    pago.generar_referencia()
    return pago


def crear_pago_destacado(pub, plan: PlanDestacado, usuario, metodo: str) -> Pago:
    if pub.vendedor_id != usuario.id:
        raise ErrorPago('Esta publicación no es tuya')
    if pub.estado != 'publicada':
        raise ErrorPago('Solo se pueden destacar artículos publicados')
    if not plan or not plan.activo:
        raise ErrorPago('Ese plan no está disponible')
    if metodo not in metodos_disponibles():
        raise ErrorPago('Forma de pago no disponible')
    # Un destacado pendiente anterior de esta publicación se cancela (y su pago pendiente)
    for d in pub.destacados.filter_by(estado='pendiente').all():
        if d.pagos.filter(Pago.estado == 'en_revision').first():
            raise ErrorPago('Ya hay un pago de destacado en revisión para este artículo')
        _cancelar_pendientes(d.pagos)
        d.estado = 'cancelado'
    dest = Destacado(publicacion=pub, plan_id=plan.id, usuario_id=usuario.id, nombre_plan=plan.nombre,
                     dias=plan.dias, precio=plan.precio)
    db.session.add(dest)
    pago = Pago(concepto='destacado', destacado=dest, usuario_id=usuario.id, metodo=metodo,
                **montos_destacado(plan.precio))
    db.session.add(pago)
    db.session.flush()
    pago.generar_referencia()
    return pago


# ── Transferencia ─────────────────────────────────────────────────────────────

def registrar_comprobante(pago: Pago, url: str, public_id: str):
    if pago.metodo != 'transferencia':
        raise ErrorPago('Este pago no es por transferencia')
    if pago.estado not in ('pendiente', 'rechazado'):
        raise ErrorPago('Este pago ya no admite comprobantes')
    pago.comprobante_url, pago.comprobante_public_id = url, public_id
    pago.estado, pago.motivo_rechazo = 'en_revision', None


# ── Aprobar / rechazar ────────────────────────────────────────────────────────

def aprobar(pago: Pago, autorizacion=None, respuesta=None, revisado_por=None, monto_confirmado=None):
    """
    Aprueba el pago y aplica su efecto. Idempotente: aprobar dos veces no duplica nada.
    Si la pasarela informa el monto cobrado, debe coincidir con el del pago.
    """
    if pago.estado == 'aprobado':
        return False
    if pago.estado == 'cancelado':
        raise ErrorPago('El pago estaba cancelado')
    if monto_confirmado is not None and _redondear(monto_confirmado) != _redondear(pago.monto):
        raise ErrorPago(f'El monto cobrado ({monto_confirmado}) no coincide con el del pago ({pago.monto})')

    pago.estado, pago.pagado_en = 'aprobado', ahora_utc()
    pago.autorizacion = (autorizacion or pago.autorizacion or '')[:60] or None
    if respuesta:
        pago.respuesta = respuesta
    if revisado_por is not None:
        pago.revisado_por_id = revisado_por.id

    if pago.concepto == 'venta':
        _aplicar_venta(pago)
    else:
        _aplicar_destacado(pago)
    return True


def _aplicar_venta(pago: Pago):
    trans = pago.transaccion
    if trans.estado_pago == 'pagado':
        return
    trans.estado_pago = 'pagado'
    trans.fecha_pago = pago.pagado_en
    trans.metodo_pago = 'transferencia' if pago.metodo == 'transferencia' else 'tarjeta'
    nota = f'Pago en línea {pago.referencia} ({pago.metodo})'
    trans.notas = f'{trans.notas}\n{nota}' if trans.notas else nota
    if trans.solicitud:
        trans.solicitud.estado = 'completada'
    if trans.publicacion:
        trans.publicacion.estado = 'vendida'
    from logging_config import log_transaction
    log_transaction(current_app, trans, f'pagada en línea ({pago.metodo})')


def _aplicar_destacado(pago: Pago):
    dest = pago.destacado
    if dest.estado == 'activo':
        return
    pub = dest.publicacion
    ahora = ahora_utc()
    # Si ya estaba destacada, el nuevo periodo empieza cuando termina el actual
    inicio = pub.destacado_hasta if pub.destacado_hasta and pub.destacado_hasta > ahora else ahora
    dest.estado, dest.inicio, dest.fin = 'activo', inicio, inicio + timedelta(days=dest.dias)
    pub.destacado_hasta = dest.fin


def rechazar(pago: Pago, motivo: str, revisado_por=None, respuesta=None):
    if pago.estado == 'aprobado':
        raise ErrorPago('No se puede rechazar un pago ya aprobado')
    pago.estado, pago.motivo_rechazo = 'rechazado', (motivo or '')[:1000]
    if respuesta:
        pago.respuesta = respuesta
    if revisado_por is not None:
        pago.revisado_por_id = revisado_por.id


def cancelar(pago: Pago):
    if pago.estado in ('pendiente',):
        pago.estado = 'cancelado'
        if pago.destacado and pago.destacado.estado == 'pendiente':
            pago.destacado.estado = 'cancelado'


# ── Planes por defecto ────────────────────────────────────────────────────────

PLANES_INICIALES = [('Destacado 7 días', 7, '300'), ('Destacado 15 días', 15, '500'), ('Destacado 30 días', 30, '900')]


def sembrar_planes():
    if PlanDestacado.query.first():
        return
    for i, (nombre, dias, precio) in enumerate(PLANES_INICIALES):
        db.session.add(PlanDestacado(nombre=nombre, dias=dias, precio=Decimal(precio), activo=True, orden=i))
