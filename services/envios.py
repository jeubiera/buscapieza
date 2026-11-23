"""
Envíos: el artículo siempre lo tiene el vendedor (o el proveedor).

Flujo:
  1. El comprador elige cómo recibirlo (tarifa) → el costo se suma al pago.
     Si la opción es "a cotizar" (fletes), el admin pone el precio antes de que pueda pagar.
  2. Al confirmarse el pago → "por despachar": se avisa al vendedor.
  3. El vendedor despacha: sube la foto del artículo y, si aplica, la empresa y el número de guía.
  4. El comprador confirma "lo recibí" (o se confirma solo pasadas N horas sin reclamo).
  5. Recién entonces el admin registra el pago al vendedor.

El vendedor nunca ve el teléfono del comprador: en la guía se pone el teléfono de BuscatodoRD.
"""
import re
from datetime import timedelta
from decimal import Decimal

from flask import current_app

from extensions import db
from models import Envio, TarifaEnvio, Transaccion, Configuracion, Provincia, Pago, ahora_utc


class ErrorEnvio(Exception):
    pass


NOMBRES_METODO = {
    'retiro': '🤝 Retiro en persona',
    'mensajero': '🛵 Mensajero',
    'agencia': '🚌 Encomienda en terminal',
    'courier': '📦 Courier a domicilio',
    'flete': '🚚 Flete',
}
NOMBRES_ESTADO = {
    'por_cotizar': ('badge-yellow', 'Cotizando envío'),
    'pendiente_pago': ('badge-gray', 'Pendiente de pago'),
    'por_despachar': ('badge-orange', 'Por despachar'),
    'despachado': ('badge-blue', 'En camino'),
    'entregado': ('badge-green', 'Entregado'),
    'reclamado': ('badge-red', 'Con reclamo'),
    'cancelado': ('badge-gray', 'Cancelado'),
}
# Precios orientativos: el admin los ajusta en Admin > Envíos > Tarifas
TARIFAS_INICIALES = [
    ('Retiro en persona', 'Coordinamos contigo el lugar y la hora para recogerlo.', 'retiro', '0', False),
    ('Mensajero — Gran Santo Domingo', 'Entrega en tu dirección, normalmente el mismo día o el siguiente.', 'mensajero', '250', True),
    ('Mensajero — Santiago', 'Entrega en tu dirección dentro de Santiago.', 'mensajero', '250', True),
    ('Encomienda a terminal de autobús', 'Lo retiras en la terminal de tu provincia (Caribe Pack, Metro Pac...).', 'agencia', '350', True),
    ('Courier a domicilio — todo el país', 'Entrega en tu puerta con número de rastreo.', 'courier', '500', True),
    ('Flete para artículos grandes', 'Neveras, motores, muebles... te cotizamos el traslado.', 'flete', None, True),
]
HORAS_CONFIRMACION_DEFECTO = 72


# ── Configuración y tarifas ───────────────────────────────────────────────────

def horas_confirmacion() -> int:
    fila = Configuracion.query.filter_by(clave='envio_horas_confirmacion').first()
    try:
        return max(12, min(720, int(fila.valor))) if fila and fila.valor else HORAS_CONFIRMACION_DEFECTO
    except ValueError:
        return HORAS_CONFIRMACION_DEFECTO


def guardar_horas_confirmacion(valor) -> str | None:
    try:
        horas = int(valor)
    except (TypeError, ValueError):
        return 'Indica las horas en número entero'
    if not 12 <= horas <= 720:
        return 'Las horas para confirmar deben estar entre 12 y 720'
    fila = Configuracion.query.filter_by(clave='envio_horas_confirmacion').first()
    if not fila:
        fila = Configuracion(clave='envio_horas_confirmacion')
        db.session.add(fila)
    fila.valor = str(horas)
    return None


def tarifas_activas():
    return TarifaEnvio.query.filter_by(activa=True).order_by(TarifaEnvio.orden, TarifaEnvio.id).all()


def sembrar_tarifas():
    if TarifaEnvio.query.first():
        return
    for i, (nombre, desc, metodo, precio, pide_dir) in enumerate(TARIFAS_INICIALES):
        db.session.add(TarifaEnvio(nombre=nombre, descripcion=desc, metodo=metodo,
                                   precio=Decimal(precio) if precio is not None else None,
                                   pide_direccion=pide_dir, activa=True, orden=i))


def costo_de(trans: Transaccion) -> Decimal:
    env = trans.envio
    return Decimal(env.costo) if env and env.costo is not None else Decimal('0')


# ── 1. El comprador elige cómo recibirlo ──────────────────────────────────────

def elegir(trans: Transaccion, usuario, tarifa: TarifaEnvio, datos: dict) -> Envio:
    if trans.cliente_id != usuario.id:
        raise ErrorEnvio('Esta compra no es tuya')
    if trans.estado_pago != 'pendiente':
        raise ErrorEnvio('La compra ya está pagada o cancelada: para cambiar la entrega escríbenos')
    if trans.pagos.filter(Pago.estado.in_(('en_revision', 'aprobado'))).first():
        raise ErrorEnvio('Ya enviaste el pago: para cambiar la entrega escríbenos')
    if not tarifa or not tarifa.activa:
        raise ErrorEnvio('Elige una forma de entrega')

    destinatario = (datos.get('destinatario') or '').strip()[:120]
    telefono = (datos.get('telefono') or '').strip()[:20]
    direccion = (datos.get('direccion') or '').strip()[:300]
    provincia = db.session.get(Provincia, int(datos.get('provincia_id') or 0) or 0)
    if not destinatario:
        raise ErrorEnvio('Indica quién recibe')
    if len(re.sub(r'\D', '', telefono)) < 10:
        raise ErrorEnvio('Indica un teléfono de contacto válido')
    if tarifa.pide_direccion and (not provincia or len(direccion) < 8):
        raise ErrorEnvio('Indica la provincia y la dirección de entrega')

    env = trans.envio or Envio(transaccion=trans)
    env.tarifa_id, env.metodo, env.nombre_opcion = tarifa.id, tarifa.metodo, tarifa.nombre
    env.costo = tarifa.precio
    env.estado = 'por_cotizar' if tarifa.a_cotizar else 'pendiente_pago'
    env.destinatario, env.telefono = destinatario, telefono
    env.provincia_id = provincia.id if provincia else None
    env.direccion = direccion or None
    env.indicaciones = (datos.get('indicaciones') or '').strip()[:300] or None
    if not env.id:
        db.session.add(env)
    # El total cambió: los pagos sin enviar quedan sin efecto
    for p in trans.pagos.filter(Pago.estado == 'pendiente').all():
        p.estado = 'cancelado'
    db.session.flush()
    return env


def cotizar(env: Envio, costo) -> Envio:
    """El admin pone (o corrige) el costo del envío antes del pago."""
    if env.estado not in ('por_cotizar', 'pendiente_pago'):
        raise ErrorEnvio('El costo solo se puede cambiar antes del pago')
    costo = Decimal(costo)
    if costo < 0:
        raise ErrorEnvio('El costo no puede ser negativo')
    env.costo, env.estado = costo, 'pendiente_pago'
    for p in env.transaccion.pagos.filter(Pago.estado == 'pendiente').all():
        p.estado = 'cancelado'
    return env


# ── 2. Pago confirmado ────────────────────────────────────────────────────────

def al_pagar(trans: Transaccion):
    """Se llama cuando la venta queda pagada (en línea o registrada por el admin)."""
    env = trans.envio
    if env and env.estado in ('pendiente_pago', 'por_cotizar'):
        env.estado, env.pagado_en = 'por_despachar', ahora_utc()
        return env
    return None


# ── 3. Despacho ───────────────────────────────────────────────────────────────

def despachar(env: Envio, por_admin: bool, empresa='', guia='', foto=None, nota=''):
    """foto = (url, public_id). La foto es obligatoria para el vendedor (prueba de lo que se envió)."""
    if env.estado not in ('por_despachar', 'despachado'):
        raise ErrorEnvio('Este envío no está listo para despacharse')
    empresa, guia = (empresa or '').strip()[:80], (guia or '').strip()[:80]
    if env.metodo in ('agencia', 'courier') and not guia and not por_admin:
        raise ErrorEnvio('Indica el número de guía que te dio la agencia o el courier')
    if not foto and not env.foto_url and not por_admin:
        raise ErrorEnvio('Sube una foto del artículo antes de empacarlo')
    if foto:
        env.foto_url, env.foto_public_id = foto
    env.empresa, env.guia = empresa or env.empresa, guia or env.guia
    env.nota_despacho = (nota or '').strip()[:300] or env.nota_despacho
    primera_vez = env.estado == 'por_despachar'
    env.estado = 'despachado'
    if primera_vez:
        env.despachado_en = ahora_utc()
    return primera_vez


# ── 4. Recepción y reclamos ───────────────────────────────────────────────────

def confirmar_recepcion(env: Envio, por: str):
    if env.estado == 'entregado':
        return False
    if env.estado not in ('despachado', 'reclamado') or (env.estado == 'reclamado' and por != 'admin'):
        raise ErrorEnvio('Este envío no se puede confirmar ahora')
    env.estado, env.entregado_en, env.confirmado_por = 'entregado', ahora_utc(), por
    return True


def reclamar(env: Envio, texto: str):
    if env.estado != 'despachado':
        raise ErrorEnvio('Solo puedes reportar un problema mientras el envío está en camino')
    texto = (texto or '').strip()
    if len(texto) < 10:
        raise ErrorEnvio('Cuéntanos qué pasó (al menos 10 caracteres)')
    env.estado, env.reclamo, env.reclamado_en = 'reclamado', texto[:2000], ahora_utc()


def resolver_reclamo(env: Envio, resolucion: str, entregar: bool):
    """entregar=True: se da por recibido (se puede pagar al vendedor). False: se cancela (devolución)."""
    if env.estado != 'reclamado':
        raise ErrorEnvio('Este envío no tiene un reclamo abierto')
    env.resolucion = (resolucion or '').strip()[:2000] or None
    if entregar:
        confirmar_recepcion(env, 'admin')
    else:
        env.estado = 'cancelado'


def limite_confirmacion(env: Envio):
    return env.despachado_en + timedelta(hours=horas_confirmacion()) if env.despachado_en else None


def confirmar_vencidos() -> list:
    """Da por recibidos los envíos en camino sin reclamo pasado el plazo. Devuelve los confirmados."""
    limite = ahora_utc() - timedelta(hours=horas_confirmacion())
    vencidos = Envio.query.filter(Envio.estado == 'despachado', Envio.despachado_en <= limite).all()
    for env in vencidos:
        confirmar_recepcion(env, 'automatico')
    if vencidos:
        db.session.commit()
        from services.tareas import en_segundo_plano
        from services.notificaciones import tarea_envio
        for env in vencidos:
            en_segundo_plano(tarea_envio, env.id, 'entregado')
    return vencidos


# ── 5. Pago al vendedor ───────────────────────────────────────────────────────

def puede_pagar_vendedor(trans: Transaccion) -> bool:
    if trans.estado_pago != 'pagado' or trans.vendedor_pagado_en:
        return False
    return trans.envio is None or trans.envio.estado == 'entregado'


def pagar_vendedor(trans: Transaccion, metodo: str, referencia: str, forzar=False):
    if trans.vendedor_pagado_en:
        raise ErrorEnvio('Al vendedor ya se le pagó esta venta')
    if trans.estado_pago != 'pagado':
        raise ErrorEnvio('El comprador todavía no ha pagado')
    if not puede_pagar_vendedor(trans) and not forzar:
        raise ErrorEnvio('El comprador todavía no ha confirmado que recibió el artículo')
    trans.vendedor_pagado_en = ahora_utc()
    trans.vendedor_pago_metodo = (metodo or 'transferencia')[:40]
    trans.vendedor_pago_ref = (referencia or '').strip()[:120] or None


def por_pagar_a_vendedores():
    return (Transaccion.query.join(Envio, Envio.transaccion_id == Transaccion.id)
            .filter(Transaccion.estado_pago == 'pagado', Transaccion.vendedor_pagado_en.is_(None),
                    Envio.estado == 'entregado')
            .order_by(Envio.entregado_en).all())


# ── Avisos por WhatsApp ───────────────────────────────────────────────────────

def _numero(u):
    return u.whatsapp or u.telefono


def notificar(env: Envio, evento: str):
    """Mensajes de WhatsApp a comprador / vendedor y avisos en la campanita del admin."""
    from services import whatsapp_svc as wa
    from services.avisos import registrar
    trans = env.transaccion
    marca = current_app.config.get('BROKER_NOMBRE', 'BuscatodoRD')
    titulo = f'{trans.codigo_origen} · {trans.titulo_origen}'[:90]
    comprador, vendedor = trans.cliente, trans.proveedor
    enlace = wa._url(f'/envios/{env.id}')

    if evento == 'por_cotizar':
        registrar('envio', '🚚', f'Envío por cotizar {trans.codigo_origen}',
                  f'{env.nombre_opcion} · {env.provincia.nombre if env.provincia else ""}', '/admin/envios?estado=por_cotizar')
    elif evento == 'cotizado':
        wa._enviar(_numero(comprador), f"🚚 *{marca}* — Ya cotizamos tu envío\n{titulo}\n"
                                       f"Envío: RD${env.costo:,.2f}\nPaga aquí: {wa._url(f'/pagos/venta/{trans.id}')}")
    elif evento == 'por_despachar':
        wa._enviar(_numero(vendedor), f"📦 *{marca}* — ¡Vendido y pagado!\n{titulo}\n"
                                      f"Despáchalo y sube la foto y la guía aquí: {enlace}")
    elif evento == 'despachado':
        registrar('envio', '📦', f'Despachado {trans.codigo_origen}',
                  f'{env.empresa or env.nombre_opcion}{" · guía " + env.guia if env.guia else ""}', f'/admin/envios')
        detalle = f"{env.empresa or ''} {('· Guía ' + env.guia) if env.guia else ''}".strip()
        wa._enviar(_numero(comprador), f"🚚 *{marca}* — Tu compra va en camino\n{titulo}\n{detalle}\n"
                                       f"Cuando la recibas confírmalo aquí: {enlace}")
    elif evento == 'entregado':
        registrar('envio', '✅', f'Entregado {trans.codigo_origen}: pagar al vendedor',
                  f'{vendedor.nombre} · RD${trans.precio_proveedor:,.2f}', '/admin/envios?estado=entregado')
        wa._enviar(_numero(vendedor), f"✅ *{marca}* — El comprador recibió el artículo\n{titulo}\n"
                                      f"Te transferiremos RD${trans.precio_proveedor:,.2f} en breve.")
    elif evento == 'reclamado':
        registrar('envio', '⚠️', f'Reclamo en {trans.codigo_origen}', (env.reclamo or '')[:200], f'/admin/envios?estado=reclamado')
    elif evento == 'vendedor_pagado':
        wa._enviar(_numero(vendedor), f"💸 *{marca}* — Te pagamos tu venta\n{titulo}\n"
                                      f"RD${trans.precio_proveedor:,.2f} · {trans.vendedor_pago_metodo}"
                                      f"{(' · Ref. ' + trans.vendedor_pago_ref) if trans.vendedor_pago_ref else ''}")
