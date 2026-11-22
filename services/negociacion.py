"""
Reglas de negocio de la compraventa: publicar, negociar con vendedor y comprador, registrar ventas.

Las usan tanto las rutas del admin como las del vendedor/comprador, para que las reglas sean
idénticas. Cada función devuelve (ok: bool, mensaje: str) y deja la sesión con commit hecho
solo si ok es True.
"""
from decimal import Decimal

from flask import current_app

from extensions import db
from models import Propuesta, Transaccion, ahora_utc
from services import config_svc


class ErrorNegocio(Exception):
    pass


def _validar_porcentaje(porcentaje):
    com = config_svc.comisiones()
    porcentaje = Decimal(str(porcentaje if porcentaje is not None else com['comision_default']))
    if not (com['comision_minima'] <= porcentaje <= com['comision_maxima']):
        raise ErrorNegocio(f"La comisión debe estar entre {com['comision_minima']}% y {com['comision_maxima']}%")
    return porcentaje


def _cerrar_pendientes(consulta, nuevo_estado):
    for p in consulta.filter_by(estado='pendiente').all():
        p.estado, p.respondida_en = nuevo_estado, ahora_utc()


# ── Publicar ──────────────────────────────────────────────────────────────────

def publicar(pub, precio_vendedor, porcentaje, mostrar_precio):
    """Fija precios y deja la publicación visible. Devuelve True si acaba de publicarse."""
    if pub.estado not in ('pendiente', 'rechazada', 'publicada', 'retirada'):
        raise ErrorNegocio('Con una venta en curso no se pueden cambiar los precios')
    porcentaje = _validar_porcentaje(porcentaje)
    era_nueva = pub.estado != 'publicada'
    pub.fijar_precio(precio_vendedor, porcentaje)
    pub.mostrar_precio = bool(mostrar_precio)
    pub.estado, pub.motivo_rechazo = 'publicada', None
    if not pub.publicada_en:
        pub.publicada_en = ahora_utc()
    # Cualquier negociación de precio con el vendedor queda cerrada
    _cerrar_pendientes(pub.propuestas.filter_by(tipo='vendedor'), 'retirada')
    return era_nueva


# ── Negociación con el VENDEDOR (cuánto recibe) ───────────────────────────────

def proponer_a_vendedor(pub, monto, porcentaje, mostrar_precio, mensaje=None):
    if pub.estado not in ('pendiente', 'publicada'):
        raise ErrorNegocio('Solo se negocia el precio de publicaciones pendientes o publicadas')
    porcentaje = _validar_porcentaje(porcentaje)
    _cerrar_pendientes(pub.propuestas.filter_by(tipo='vendedor'), 'contraofertada')
    prop = Propuesta(tipo='vendedor', publicacion_id=pub.id, autor='admin', monto=monto,
                     porcentaje=porcentaje, mostrar_precio=bool(mostrar_precio), mensaje=mensaje)
    db.session.add(prop)
    return prop


def _ultima_propuesta_admin_vendedor(pub):
    return (pub.propuestas.filter_by(tipo='vendedor', autor='admin')
            .order_by(Propuesta.created_at.desc()).first())


def vendedor_responde(pub, accion, monto=None, mensaje=None):
    """El vendedor acepta, contrapropone o rechaza la propuesta pendiente del admin."""
    prop = pub.propuesta_vendedor_pendiente()
    if not prop or prop.autor != 'admin':
        raise ErrorNegocio('No hay ninguna propuesta pendiente de responder')
    prop.respondida_en = ahora_utc()
    if accion == 'aceptar':
        prop.estado = 'aceptada'
        publicar(pub, prop.monto, prop.porcentaje, prop.mostrar_precio)
        prop.estado = 'aceptada'   # publicar() retira pendientes; esta ya está resuelta
        return prop, 'aceptada'
    if accion == 'contraofertar':
        if monto is None:
            raise ErrorNegocio('Indica cuánto quieres recibir')
        prop.estado = 'contraofertada'
        nueva = Propuesta(tipo='vendedor', publicacion_id=pub.id, autor='usuario', monto=monto, mensaje=mensaje)
        db.session.add(nueva)
        return nueva, 'contraofertada'
    if accion == 'rechazar':
        prop.estado = 'rechazada'
        if mensaje:
            db.session.add(Propuesta(tipo='vendedor', publicacion_id=pub.id, autor='usuario', monto=prop.monto,
                                     mensaje=mensaje, estado='rechazada', respondida_en=ahora_utc()))
        return prop, 'rechazada'
    raise ErrorNegocio('Acción no válida')


def admin_acepta_vendedor(pub):
    """El admin acepta la contrapropuesta del vendedor y publica con la comisión de su última propuesta."""
    prop = pub.propuesta_vendedor_pendiente()
    if not prop or prop.autor != 'usuario':
        raise ErrorNegocio('No hay contrapropuesta del vendedor pendiente')
    previa = _ultima_propuesta_admin_vendedor(pub)
    porcentaje = previa.porcentaje if previa else None
    mostrar = previa.mostrar_precio if previa and previa.mostrar_precio is not None else pub.mostrar_precio
    prop.estado, prop.respondida_en = 'aceptada', ahora_utc()
    publicar(pub, prop.monto, porcentaje, mostrar)
    prop.estado = 'aceptada'
    return prop


# ── Negociación con el COMPRADOR (cuánto paga) ────────────────────────────────

def _validar_monto_comprador(pub, monto):
    if pub.estado != 'publicada':
        raise ErrorNegocio('El artículo ya no está disponible')
    if pub.precio_vendedor is None:
        raise ErrorNegocio('Primero fija el precio con el vendedor')
    if Decimal(monto) < Decimal(pub.precio_vendedor):
        raise ErrorNegocio(f'El precio al comprador no puede ser menor que lo que recibe el vendedor '
                           f'(RD${pub.precio_vendedor:,.2f}). Renegocia antes con el vendedor.')


def cotizar_a_comprador(interes, monto, mensaje=None):
    pub = interes.publicacion
    if interes.estado in ('descartado', 'convertido'):
        raise ErrorNegocio('Ese interesado está descartado o ya compró')
    _validar_monto_comprador(pub, monto)
    for p in interes.propuestas:
        if p.estado == 'pendiente':
            p.estado, p.respondida_en = 'contraofertada', ahora_utc()
    prop = Propuesta(tipo='comprador', publicacion=pub, interes=interes, autor='admin',
                     monto=monto, mensaje=mensaje)
    db.session.add(prop)
    interes.estado = 'contactado'
    return prop


def oferta_inicial_comprador(interes, monto, mensaje=None):
    """La cantidad que escribe el comprador al pedir precio se convierte en su propuesta."""
    for p in interes.propuestas:
        if p.estado == 'pendiente':
            p.estado, p.respondida_en = 'contraofertada', ahora_utc()
    prop = Propuesta(tipo='comprador', publicacion=interes.publicacion, interes=interes,
                     autor='usuario', monto=monto, mensaje=mensaje)
    db.session.add(prop)
    return prop


def comprador_responde(interes, accion, monto=None, mensaje=None):
    prop = interes.propuesta_pendiente()
    if not prop or prop.autor != 'admin':
        raise ErrorNegocio('No hay ninguna cotización pendiente de responder')
    prop.respondida_en = ahora_utc()
    if accion == 'aceptar':
        trans = registrar_venta(interes.publicacion, interes, prop.monto, interes.publicacion.precio_vendedor)
        prop.estado = 'aceptada'
        return prop, trans
    if accion == 'contraofertar':
        if monto is None:
            raise ErrorNegocio('Indica cuánto ofreces')
        prop.estado = 'contraofertada'
        nueva = Propuesta(tipo='comprador', publicacion=interes.publicacion, interes=interes,
                          autor='usuario', monto=monto, mensaje=mensaje)
        db.session.add(nueva)
        interes.oferta_comprador = monto
        return nueva, None
    if accion == 'rechazar':
        prop.estado = 'rechazada'
        return prop, None
    raise ErrorNegocio('Acción no válida')


def admin_acepta_comprador(interes):
    """El admin acepta la oferta pendiente del comprador → venta registrada."""
    prop = interes.propuesta_pendiente()
    if not prop or prop.autor != 'usuario':
        raise ErrorNegocio('No hay oferta del comprador pendiente')
    trans = registrar_venta(interes.publicacion, interes, prop.monto, interes.publicacion.precio_vendedor)
    prop.estado, prop.respondida_en = 'aceptada', ahora_utc()
    return trans


# ── Venta ─────────────────────────────────────────────────────────────────────

def registrar_venta(pub, interes, precio_final, precio_vendedor, notas=None):
    """Crea la transacción (pendiente de pago) y reserva el artículo."""
    if pub.estado != 'publicada' or pub.transaccion_activa():
        raise ErrorNegocio('La publicación no está disponible para registrar una venta')
    if interes.publicacion_id != pub.id:
        raise ErrorNegocio('Ese interesado no es de esta publicación')
    precio_final, precio_vendedor = Decimal(precio_final), Decimal(precio_vendedor)
    if precio_final < precio_vendedor:
        raise ErrorNegocio('El precio al comprador no puede ser menor que lo que recibe el vendedor')
    trans = Transaccion(publicacion_id=pub.id, cliente_id=interes.comprador_id, proveedor_id=pub.vendedor_id,
                        precio_proveedor=precio_vendedor, precio_cliente=precio_final,
                        comision_broker=0, estado_pago='pendiente', notas=notas)
    trans.calcular_comision()
    db.session.add(trans)
    pub.estado = 'reservada'
    interes.estado = 'convertido'
    # Las demás negociaciones abiertas de esta publicación se cierran
    for p in pub.propuestas.filter_by(estado='pendiente').all():
        if p.interes_id != interes.id:
            p.estado, p.respondida_en = 'retirada', ahora_utc()
    db.session.flush()
    from logging_config import log_transaction
    log_transaction(current_app, trans, 'creada')
    return trans
