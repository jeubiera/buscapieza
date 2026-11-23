"""
Campanita del panel de administración.

Dos partes:
- Avisos (eventos): "pago recibido", "nueva publicación"... se guardan en avisos_admin cuando ocurren.
  Cada admin tiene su marca avisos_vistos_hasta: lo posterior cuenta como "sin ver".
- Pendientes (en vivo): lo que está esperando una acción del admin, contado directamente de la BD.
"""
from datetime import timedelta

from flask import current_app
from sqlalchemy import func

from extensions import db
from models import AvisoAdmin, ahora_utc

MAX_DIAS_SIN_VER = 30


def registrar(tipo: str, icono: str, titulo: str, detalle: str = '', url: str = '/admin/dashboard'):
    """Guarda un aviso. Nunca rompe el flujo que lo llama."""
    try:
        db.session.add(AvisoAdmin(tipo=tipo[:30], icono=icono[:10], titulo=titulo[:150],
                                  detalle=(detalle or '')[:300], url=(url or '')[:300]))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'No se pudo registrar el aviso "{titulo}": {e}')


def _desde(admin):
    limite = ahora_utc() - timedelta(days=MAX_DIAS_SIN_VER)
    visto = admin.avisos_vistos_hasta
    return max(visto, limite) if visto else limite


def sin_ver(admin) -> int:
    return AvisoAdmin.query.filter(AvisoAdmin.created_at > _desde(admin)).count()


def recientes(limite: int = 12):
    return AvisoAdmin.query.order_by(AvisoAdmin.created_at.desc(), AvisoAdmin.id.desc()).limit(limite).all()


def marcar_vistos(admin):
    admin.avisos_vistos_hasta = ahora_utc()
    db.session.commit()


def pendientes() -> list:
    """[(icono, texto, cantidad, url)] de lo que espera una acción del admin (solo lo que tiene algo)."""
    from models import (Publicacion, Pago, Propuesta, Interes, Coincidencia, Oferta, Solicitud, Usuario,
                        ComisionReferido, Envio)
    from services.envios import por_pagar_a_vendedores, confirmar_vencidos
    confirmar_vencidos()
    pagos_referidos = db.session.query(func.count(func.distinct(ComisionReferido.beneficiario_id)))\
        .filter(ComisionReferido.estado == 'disponible').scalar() or 0
    filas = [
        ('🧾', 'pago(s) por verificar', Pago.query.filter_by(estado='en_revision').count(), '/admin/pagos'),
        ('⚠️', 'reclamo(s) de envío', Envio.query.filter_by(estado='reclamado').count(), '/admin/envios?estado=reclamado'),
        ('🚚', 'envío(s) por cotizar', Envio.query.filter_by(estado='por_cotizar').count(), '/admin/envios?estado=por_cotizar'),
        ('📦', 'venta(s) por despachar', Envio.query.filter_by(estado='por_despachar').count(), '/admin/envios?estado=por_despachar'),
        ('💵', 'vendedor(es) por pagar', len(por_pagar_a_vendedores()), '/admin/envios?estado=por_pagar'),
        ('🏷️', 'publicación(es) por aprobar', Publicacion.query.filter_by(estado='pendiente').count(),
         '/admin/publicaciones?estado=pendiente'),
        ('💬', 'respuesta(s) de vendedores/compradores', Propuesta.query.filter_by(estado='pendiente', autor='usuario').count(),
         '/admin/publicaciones'),
        ('🛒', 'interesado(s) por atender', Interes.query.filter_by(estado='nuevo').count(), '/admin/publicaciones'),
        ('🎯', 'coincidencia(s) nuevas', Coincidencia.query.filter_by(estado='nueva').count(), '/admin/coincidencias'),
        ('🔍', 'búsqueda(s) pendientes', Solicitud.query.filter_by(estado='pendiente').count(),
         '/admin/solicitudes?estado=pendiente'),
        ('📦', 'oferta(s) de proveedores sin ver', Oferta.query.filter_by(estado='nueva').count(), '/admin/solicitudes'),
        ('🏪', 'proveedor(es) por verificar',
         Usuario.query.filter_by(rol='proveedor', activo=True, verificado=False).count(), '/admin/proveedores'),
        ('💸', 'referido(s) con comisiones por pagar', pagos_referidos, '/admin/referidos'),
    ]
    return [f for f in filas if f[2]]


def resumen(admin) -> dict:
    p = pendientes()
    return {'sin_ver': sin_ver(admin), 'pendientes': p, 'total_pendientes': sum(f[2] for f in p)}
