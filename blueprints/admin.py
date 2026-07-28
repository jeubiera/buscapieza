from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from functools import wraps
from models import db, Solicitud, Oferta, Usuario, Categoria, Provincia, Notificacion, Configuracion, Transaccion, Rating
from services.whatsapp_svc import (
    notificar_proveedor_solicitud,
    notificar_cliente_oferta_disponible
)
from services.push_svc import enviar_push_a_todos_proveedores
from sqlalchemy import func
from datetime import datetime, timedelta

admin_bp = Blueprint('admin', __name__)

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.rol != 'admin':
            flash('Acceso restringido al administrador', 'danger')
            return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return decorated

# ── Dashboard ─────────────────────────────────────────────────────────────────

@admin_bp.route('/dashboard')
@login_required
@admin_required
def dashboard():
    # Estadísticas básicas
    stats = {
        'solicitudes_total'   : Solicitud.query.count(),
        'solicitudes_pending' : Solicitud.query.filter_by(estado='pendiente').count(),
        'solicitudes_gestion' : Solicitud.query.filter_by(estado='en_gestion').count(),
        'solicitudes_done'    : Solicitud.query.filter_by(estado='completada').count(),
        'ofertas_nuevas'      : Oferta.query.filter_by(estado='nueva').count(),
        'ofertas_total'       : Oferta.query.count(),
        'proveedores'         : Usuario.query.filter_by(rol='proveedor', activo=True).count(),
        'clientes'            : Usuario.query.filter_by(rol='cliente', activo=True).count(),
        'transacciones_total' : Transaccion.query.count(),
        'transacciones_pagadas': Transaccion.query.filter_by(estado_pago='pagado').count(),
    }

    # Calcular ingresos totales (comisiones)
    ingresos = db.session.query(func.sum(Transaccion.comision_broker))\
        .filter(Transaccion.estado_pago == 'pagado').scalar() or 0

    # Ingresos del mes actual
    inicio_mes = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    ingresos_mes = db.session.query(func.sum(Transaccion.comision_broker))\
        .filter(Transaccion.estado_pago == 'pagado')\
        .filter(Transaccion.fecha_pago >= inicio_mes).scalar() or 0

    # Solicitudes de los últimos 7 días
    hace_7_dias = datetime.now() - timedelta(days=7)
    solicitudes_semana = Solicitud.query.filter(Solicitud.created_at >= hace_7_dias).count()

    stats['ingresos_total'] = float(ingresos)
    stats['ingresos_mes'] = float(ingresos_mes)
    stats['solicitudes_semana'] = solicitudes_semana

    # Top 5 categorías más solicitadas
    top_categorias = db.session.query(
        Categoria.nombre, func.count(Solicitud.id).label('total')
    ).join(Solicitud).group_by(Categoria.id).order_by(func.count(Solicitud.id).desc()).limit(5).all()

    # Top 5 proveedores con mejores ratings
    top_proveedores = db.session.query(
        Usuario.nombre, Usuario.id, func.avg(Rating.calificacion_general).label('rating_promedio')
    ).join(Rating, Usuario.id == Rating.proveedor_id)\
    .filter(Rating.visible == True)\
    .group_by(Usuario.id).order_by(func.avg(Rating.calificacion_general).desc()).limit(5).all()

    solicitudes    = Solicitud.query.order_by(Solicitud.created_at.desc()).limit(20).all()
    ofertas_nuevas = Oferta.query.filter_by(estado='nueva')\
        .order_by(Oferta.created_at.desc()).all()

    return render_template('admin/dashboard.html',
        stats=stats,
        solicitudes=solicitudes,
        ofertas_nuevas=ofertas_nuevas,
        top_categorias=top_categorias,
        top_proveedores=top_proveedores
    )


# ── Analytics y KPIs Detallados ───────────────────────────────────────────────

@admin_bp.route('/analytics')
@login_required
@admin_required
def analytics():
    """Dashboard de analytics detallado con gráficas y KPIs"""

    # Rango de fechas (últimos 30 días por defecto)
    fecha_fin = datetime.now()
    fecha_inicio = fecha_fin - timedelta(days=30)

    # Solicitudes por estado (para gráfica de pie)
    solicitudes_por_estado = db.session.query(
        Solicitud.estado, func.count(Solicitud.id).label('total')
    ).group_by(Solicitud.estado).all()

    # Solicitudes por día (últimos 30 días)
    solicitudes_por_dia = db.session.query(
        func.date(Solicitud.created_at).label('fecha'),
        func.count(Solicitud.id).label('total')
    ).filter(Solicitud.created_at >= fecha_inicio)\
     .group_by(func.date(Solicitud.created_at))\
     .order_by(func.date(Solicitud.created_at)).all()

    # Ingresos por mes (últimos 6 meses)
    hace_6_meses = fecha_fin - timedelta(days=180)
    ingresos_por_mes = db.session.query(
        func.date_format(Transaccion.fecha_pago, '%Y-%m').label('mes'),
        func.sum(Transaccion.comision_broker).label('total')
    ).filter(Transaccion.estado_pago == 'pagado')\
     .filter(Transaccion.fecha_pago >= hace_6_meses)\
     .group_by(func.date_format(Transaccion.fecha_pago, '%Y-%m'))\
     .order_by(func.date_format(Transaccion.fecha_pago, '%Y-%m')).all()

    # Categorías más populares
    categorias_populares = db.session.query(
        Categoria.nombre, Categoria.icono, Categoria.color,
        func.count(Solicitud.id).label('total')
    ).join(Solicitud)\
     .group_by(Categoria.id)\
     .order_by(func.count(Solicitud.id).desc()).all()

    # Provincias con más actividad
    provincias_activas = db.session.query(
        Provincia.nombre, func.count(Solicitud.id).label('total')
    ).join(Solicitud)\
     .group_by(Provincia.id)\
     .order_by(func.count(Solicitud.id).desc())\
     .limit(10).all()

    # Tasa de conversión (solicitudes que terminan en transacción)
    total_solicitudes = Solicitud.query.count()
    total_transacciones = Transaccion.query.count()
    tasa_conversion = (total_transacciones / total_solicitudes * 100) if total_solicitudes > 0 else 0

    # Tiempo promedio de respuesta (primera oferta)
    # (Este cálculo es aproximado, necesitaría optimización en producción)

    # Rating promedio general
    rating_promedio_general = db.session.query(
        func.avg(Rating.calificacion_general)
    ).filter(Rating.visible == True).scalar() or 0

    # Proveedores más activos
    proveedores_activos = db.session.query(
        Usuario.nombre, Usuario.id, func.count(Oferta.id).label('total_ofertas')
    ).join(Oferta, Usuario.id == Oferta.proveedor_id)\
     .group_by(Usuario.id)\
     .order_by(func.count(Oferta.id).desc())\
     .limit(10).all()

    # Clientes más activos
    clientes_activos = db.session.query(
        Usuario.nombre, Usuario.id, func.count(Solicitud.id).label('total_solicitudes')
    ).join(Solicitud, Usuario.id == Solicitud.cliente_id)\
     .group_by(Usuario.id)\
     .order_by(func.count(Solicitud.id).desc())\
     .limit(10).all()

    return render_template('admin/analytics.html',
        solicitudes_por_estado=solicitudes_por_estado,
        solicitudes_por_dia=solicitudes_por_dia,
        ingresos_por_mes=ingresos_por_mes,
        categorias_populares=categorias_populares,
        provincias_activas=provincias_activas,
        tasa_conversion=round(tasa_conversion, 2),
        rating_promedio_general=round(float(rating_promedio_general), 2),
        proveedores_activos=proveedores_activos,
        clientes_activos=clientes_activos
    )


# ── Solicitud individual ───────────────────────────────────────────────────────

@admin_bp.route('/solicitud/<int:sid>')
@login_required
@admin_required
def ver_solicitud(sid):
    sol    = Solicitud.query.get_or_404(sid)
    ofertas = Oferta.query.filter_by(solicitud_id=sid)\
        .order_by(Oferta.created_at.desc()).all()
    return render_template('admin/ver_solicitud.html', sol=sol, ofertas=ofertas)

@admin_bp.route('/solicitud/<int:sid>/estado', methods=['POST'])
@login_required
@admin_required
def cambiar_estado(sid):
    sol             = Solicitud.query.get_or_404(sid)
    sol.estado      = request.form.get('estado', sol.estado)
    sol.notas_admin = request.form.get('notas_admin', '')
    db.session.commit()
    flash(f'Estado actualizado: {sol.estado}', 'success')
    return redirect(url_for('admin.ver_solicitud', sid=sid))

# ── Ofertas ───────────────────────────────────────────────────────────────────

@admin_bp.route('/oferta/<int:oid>/estado', methods=['POST'])
@login_required
@admin_required
def cambiar_estado_oferta(oid):
    oferta              = Oferta.query.get_or_404(oid)
    oferta.estado       = request.form.get('estado', 'vista')
    oferta.notas_broker = request.form.get('notas', '')
    db.session.commit()
    flash('Oferta actualizada', 'success')
    return redirect(url_for('admin.ver_solicitud', sid=oferta.solicitud_id))

# ── Notificar proveedores ─────────────────────────────────────────────────────

@admin_bp.route('/notificar-proveedores/<int:sid>', methods=['POST'])
@login_required
@admin_required
def notificar_proveedores(sid):
    """
    Broker envía la solicitud manualmente a proveedores activos.
    WhatsApp + Push.
    """
    sol        = Solicitud.query.get_or_404(sid)
    proveedores = Usuario.query.filter_by(rol='proveedor', activo=True, verificado=True).all()

    wa_ok = 0
    for prov in proveedores:
        try:
            if notificar_proveedor_solicitud(prov, sol):
                wa_ok += 1
        except Exception as e:
            pass

    push_ok = 0
    try:
        push_ok = enviar_push_a_todos_proveedores(
            titulo = f"🔍 {sol.titulo[:50]}",
            cuerpo = f"Nueva solicitud {sol.codigo} — ¿Tienes esta pieza?",
            url    = f"/ofertas/hacer/{sol.id}"
        )
    except Exception:
        pass

    sol.estado = 'en_gestion'
    db.session.commit()

    flash(f'✅ Enviado por WhatsApp a {wa_ok} proveedores · Push a {push_ok} dispositivos', 'success')
    return redirect(url_for('admin.ver_solicitud', sid=sid))

# ── Notificar cliente ─────────────────────────────────────────────────────────

@admin_bp.route('/notificar-cliente/<int:sid>', methods=['POST'])
@login_required
@admin_required
def notificar_cliente(sid):
    """Broker notifica al cliente que tiene respuesta (sin revelar proveedor)."""
    sol = Solicitud.query.get_or_404(sid)
    try:
        ok = notificar_cliente_oferta_disponible(sol)
        if ok:
            flash('✅ Cliente notificado por WhatsApp', 'success')
        else:
            flash('⚠️ WhatsApp no configurado o número inválido', 'warning')
    except Exception as e:
        flash(f'Error: {e}', 'danger')
    return redirect(url_for('admin.ver_solicitud', sid=sid))

# ── Proveedores ───────────────────────────────────────────────────────────────

@admin_bp.route('/proveedores')
@login_required
@admin_required
def proveedores():
    lista = Usuario.query.filter_by(rol='proveedor')\
        .order_by(Usuario.created_at.desc()).all()
    return render_template('admin/proveedores.html', proveedores=lista)

@admin_bp.route('/proveedor/<int:uid>/toggle', methods=['POST'])
@login_required
@admin_required
def toggle_proveedor(uid):
    u = Usuario.query.get_or_404(uid)
    u.activo     = not u.activo
    u.verificado = u.activo
    db.session.commit()
    flash(f'Proveedor {"activado" if u.activo else "desactivado"}', 'success')
    return redirect(url_for('admin.proveedores'))

# ── Log de notificaciones ─────────────────────────────────────────────────────

@admin_bp.route('/notificaciones')
@login_required
@admin_required
def notificaciones():
    logs = Notificacion.query.order_by(Notificacion.created_at.desc()).limit(100).all()
    return render_template('admin/notificaciones.html', logs=logs)

# ── Configuración ─────────────────────────────────────────────────────────────

@admin_bp.route('/configuracion', methods=['GET', 'POST'])
@login_required
@admin_required
def configuracion():
    if request.method == 'POST':
        campos = [
            'GREEN_API_INSTANCE', 'GREEN_API_TOKEN',
            'BROKER_WHATSAPP', 'BROKER_NOMBRE',
            'CLOUDINARY_CLOUD_NAME', 'CLOUDINARY_API_KEY', 'CLOUDINARY_API_SECRET',
            'FIREBASE_SERVER_KEY', 'FIREBASE_VAPID_PUBLIC', 'FIREBASE_VAPID_PRIVATE',
        ]
        for campo in campos:
            valor = request.form.get(campo, '').strip()
            cfg   = Configuracion.query.filter_by(clave=campo).first()
            if cfg:
                cfg.valor = valor
            else:
                db.session.add(Configuracion(clave=campo, valor=valor))
        db.session.commit()

        # Recargar en la config de Flask
        _recargar_config()
        flash('✅ Configuración guardada', 'success')
        return redirect(url_for('admin.configuracion'))

    # Cargar valores actuales
    cfg_dict = {c.clave: c.valor for c in Configuracion.query.all()}
    return render_template('admin/configuracion.html', cfg=cfg_dict)

@admin_bp.route('/configuracion/test-whatsapp', methods=['POST'])
@login_required
@admin_required
def test_whatsapp():
    """Envía mensaje de prueba al broker para verificar la integración."""
    from services.whatsapp_svc import _enviar, _cfg
    instance, token = _cfg()
    broker_wa = request.form.get('numero', '').strip()
    if not instance or not token:
        return jsonify({'ok': False, 'msg': 'Green API no configurada'})
    if not broker_wa:
        return jsonify({'ok': False, 'msg': 'Número requerido'})
    ok = _enviar(broker_wa, '✅ *BuscaPieza RD* — Conexión WhatsApp verificada correctamente 🎉')
    return jsonify({'ok': ok, 'msg': 'Mensaje enviado' if ok else 'Error al enviar'})

def _recargar_config():
    """Recarga las claves de la BD en la config de Flask."""
    from flask import current_app
    from models import Configuracion
    for c in Configuracion.query.all():
        current_app.config[c.clave] = c.valor

# ── Push token (API) ──────────────────────────────────────────────────────────

@admin_bp.route('/push-token', methods=['POST'])
@login_required
def guardar_push_token():
    """Recibe token FCM desde el frontend y lo guarda."""
    from models import PushToken
    data  = request.get_json()
    token = data.get('token', '').strip()
    if not token:
        return jsonify({'ok': False})

    existente = PushToken.query.filter_by(
        usuario_id=current_user.id, token=token).first()
    if not existente:
        db.session.add(PushToken(usuario_id=current_user.id, token=token))
        db.session.commit()

    return jsonify({'ok': True})
