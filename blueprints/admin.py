from collections import OrderedDict
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps

from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify, abort, current_app
from flask_login import login_required, current_user
from sqlalchemy import func

from models import (db, Solicitud, Oferta, Usuario, Categoria, Provincia, Notificacion,
                    Transaccion, Rating, ahora_utc, ESTADOS_SOLICITUD, METODOS_PAGO)
from services import config_svc
from services.tareas import en_segundo_plano
from services.notificaciones import tarea_notificar_proveedores
from services.whatsapp_svc import notificar_cliente_oferta_disponible
from logging_config import log_transaction

admin_bp = Blueprint('admin', __name__)


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.rol != 'admin':
            flash('Acceso restringido al administrador', 'danger')
            return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return decorated


@admin_bp.before_request
@login_required
@admin_required
def _solo_admin():
    """Todas las rutas de este blueprint requieren admin."""
    return None


def _inicio_mes():
    return ahora_utc().replace(day=1, hour=0, minute=0, second=0, microsecond=0)


# ── Dashboard ─────────────────────────────────────────────────────────────────

@admin_bp.route('/dashboard')
def dashboard():
    stats = {
        'solicitudes_total'   : Solicitud.query.count(),
        'solicitudes_pending' : Solicitud.query.filter_by(estado='pendiente').count(),
        'solicitudes_gestion' : Solicitud.query.filter_by(estado='en_gestion').count(),
        'solicitudes_done'    : Solicitud.query.filter_by(estado='completada').count(),
        'ofertas_nuevas'      : Oferta.query.filter_by(estado='nueva').count(),
        'ofertas_total'       : Oferta.query.count(),
        'proveedores'         : Usuario.query.filter_by(rol='proveedor', activo=True).count(),
        'proveedores_pendientes': Usuario.query.filter_by(rol='proveedor', activo=True, verificado=False).count(),
        'clientes'            : Usuario.query.filter_by(rol='cliente', activo=True).count(),
        'transacciones_total' : Transaccion.query.filter(Transaccion.estado_pago != 'cancelado').count(),
        'transacciones_pagadas': Transaccion.query.filter_by(estado_pago='pagado').count(),
        'transacciones_pendientes': Transaccion.query.filter_by(estado_pago='pendiente').count(),
    }

    ingresos = db.session.query(func.sum(Transaccion.comision_broker))\
        .filter(Transaccion.estado_pago == 'pagado').scalar() or 0
    ingresos_mes = db.session.query(func.sum(Transaccion.comision_broker))\
        .filter(Transaccion.estado_pago == 'pagado')\
        .filter(Transaccion.fecha_pago >= _inicio_mes()).scalar() or 0
    por_cobrar = db.session.query(func.sum(Transaccion.comision_broker))\
        .filter(Transaccion.estado_pago == 'pendiente').scalar() or 0

    stats['ingresos_total'] = float(ingresos)
    stats['ingresos_mes'] = float(ingresos_mes)
    stats['comision_por_cobrar'] = float(por_cobrar)
    stats['solicitudes_semana'] = Solicitud.query.filter(
        Solicitud.created_at >= ahora_utc() - timedelta(days=7)).count()

    top_categorias = db.session.query(
        Categoria.nombre, func.count(Solicitud.id).label('total')
    ).join(Solicitud).group_by(Categoria.id, Categoria.nombre)\
     .order_by(func.count(Solicitud.id).desc()).limit(5).all()

    top_proveedores = db.session.query(
        Usuario.nombre, Usuario.empresa, Usuario.id,
        func.avg(Rating.calificacion_general).label('rating_promedio'),
        func.count(Rating.id).label('total'),
    ).join(Rating, Usuario.id == Rating.proveedor_id)\
     .filter(Rating.visible == True)\
     .group_by(Usuario.id, Usuario.nombre, Usuario.empresa)\
     .order_by(func.avg(Rating.calificacion_general).desc()).limit(5).all()  # noqa: E712

    solicitudes    = Solicitud.query.order_by(Solicitud.created_at.desc()).limit(20).all()
    ofertas_nuevas = Oferta.query.filter_by(estado='nueva')\
        .order_by(Oferta.created_at.desc()).limit(20).all()

    return render_template('admin/dashboard.html',
        stats=stats,
        solicitudes=solicitudes,
        ofertas_nuevas=ofertas_nuevas,
        top_categorias=top_categorias,
        top_proveedores=top_proveedores
    )


# ── Analytics ─────────────────────────────────────────────────────────────────

@admin_bp.route('/analytics')
def analytics():
    """KPIs de los últimos 30 días / 6 meses (consultas portables PostgreSQL/SQLite)."""
    fecha_fin = ahora_utc()
    fecha_inicio = fecha_fin - timedelta(days=30)

    solicitudes_por_estado = dict(db.session.query(
        Solicitud.estado, func.count(Solicitud.id)
    ).group_by(Solicitud.estado).all())

    # Solicitudes por día: se agrupa en Python para no depender de funciones de fecha del motor
    por_dia = OrderedDict(((fecha_inicio + timedelta(days=i)).date(), 0) for i in range(1, 31))
    for (creada,) in db.session.query(Solicitud.created_at).filter(Solicitud.created_at >= fecha_inicio):
        if creada and creada.date() in por_dia:
            por_dia[creada.date()] += 1
    solicitudes_por_dia = list(por_dia.items())

    # Ingresos (comisiones cobradas) por mes, últimos 6 meses
    meses = OrderedDict()
    año, mes = fecha_fin.year, fecha_fin.month
    for _ in range(6):
        meses[f"{año}-{mes:02d}"] = Decimal('0')
        mes -= 1
        if mes == 0:
            año, mes = año - 1, 12
    meses = OrderedDict(reversed(list(meses.items())))
    pagos = db.session.query(Transaccion.fecha_pago, Transaccion.comision_broker)\
        .filter(Transaccion.estado_pago == 'pagado', Transaccion.fecha_pago.isnot(None)).all()
    for fecha_pago, comision in pagos:
        clave = f"{fecha_pago.year}-{fecha_pago.month:02d}"
        if clave in meses:
            meses[clave] += comision or 0
    ingresos_por_mes = list(meses.items())

    categorias_populares = db.session.query(
        Categoria.nombre, Categoria.icono, Categoria.color,
        func.count(Solicitud.id).label('total')
    ).join(Solicitud)\
     .group_by(Categoria.id, Categoria.nombre, Categoria.icono, Categoria.color)\
     .order_by(func.count(Solicitud.id).desc()).all()

    provincias_activas = db.session.query(
        Provincia.nombre, func.count(Solicitud.id).label('total')
    ).join(Solicitud)\
     .group_by(Provincia.id, Provincia.nombre)\
     .order_by(func.count(Solicitud.id).desc())\
     .limit(10).all()

    total_solicitudes = Solicitud.query.count()
    total_pagadas = Transaccion.query.filter_by(estado_pago='pagado').count()
    tasa_conversion = (total_pagadas / total_solicitudes * 100) if total_solicitudes else 0

    rating_promedio_general = db.session.query(
        func.avg(Rating.calificacion_general)
    ).filter(Rating.visible == True).scalar() or 0  # noqa: E712

    proveedores_activos = db.session.query(
        Usuario.nombre, Usuario.empresa, Usuario.id, func.count(Oferta.id).label('total_ofertas')
    ).join(Oferta, Usuario.id == Oferta.proveedor_id)\
     .group_by(Usuario.id, Usuario.nombre, Usuario.empresa)\
     .order_by(func.count(Oferta.id).desc())\
     .limit(10).all()

    clientes_activos = db.session.query(
        Usuario.nombre, Usuario.id, func.count(Solicitud.id).label('total_solicitudes')
    ).join(Solicitud, Usuario.id == Solicitud.cliente_id)\
     .group_by(Usuario.id, Usuario.nombre)\
     .order_by(func.count(Solicitud.id).desc())\
     .limit(10).all()

    return render_template('admin/analytics.html',
        solicitudes_por_estado=solicitudes_por_estado,
        solicitudes_por_dia=solicitudes_por_dia,
        max_dia=max([n for _, n in solicitudes_por_dia] + [1]),
        ingresos_por_mes=ingresos_por_mes,
        max_ingreso=max([v for _, v in ingresos_por_mes] + [Decimal('1')]),
        categorias_populares=categorias_populares,
        provincias_activas=provincias_activas,
        total_solicitudes=total_solicitudes,
        tasa_conversion=round(tasa_conversion, 2),
        rating_promedio_general=round(float(rating_promedio_general), 2),
        proveedores_activos=proveedores_activos,
        clientes_activos=clientes_activos
    )


# ── Listados ──────────────────────────────────────────────────────────────────

@admin_bp.route('/solicitudes')
def solicitudes():
    estado = request.args.get('estado', '')
    cat_id = request.args.get('categoria', type=int)
    query = Solicitud.query
    if estado in ESTADOS_SOLICITUD:
        query = query.filter_by(estado=estado)
    else:
        estado = ''
    if cat_id:
        query = query.filter_by(categoria_id=cat_id)
    page = request.args.get('page', 1, type=int)
    pag = query.order_by(Solicitud.created_at.desc()).paginate(page=page, per_page=25, error_out=False)
    return render_template('admin/solicitudes.html',
        solicitudes=pag, estado=estado, cat_id=cat_id or '',
        categorias=Categoria.query.order_by(Categoria.nombre).all())


@admin_bp.route('/clientes')
def clientes():
    page = request.args.get('page', 1, type=int)
    pag = Usuario.query.filter_by(rol='cliente')\
        .order_by(Usuario.created_at.desc()).paginate(page=page, per_page=25, error_out=False)
    return render_template('admin/clientes.html', clientes=pag)


@admin_bp.route('/transacciones')
def transacciones():
    estado = request.args.get('estado', '')
    query = Transaccion.query
    if estado in ('pendiente', 'pagado', 'cancelado'):
        query = query.filter_by(estado_pago=estado)
    else:
        estado = ''
    page = request.args.get('page', 1, type=int)
    pag = query.order_by(Transaccion.created_at.desc()).paginate(page=page, per_page=25, error_out=False)
    return render_template('admin/transacciones.html', transacciones=pag, estado=estado)


# ── Solicitud individual ───────────────────────────────────────────────────────

@admin_bp.route('/solicitud/<int:sid>')
def ver_solicitud(sid):
    sol    = db.get_or_404(Solicitud, sid)
    ofertas = Oferta.query.filter_by(solicitud_id=sid)\
        .order_by(Oferta.precio.asc(), Oferta.created_at.asc()).all()
    trans = sol.transaccion_activa()
    return render_template('admin/ver_solicitud.html', sol=sol, ofertas=ofertas, trans=trans,
                           comisiones=config_svc.comisiones(), metodos_pago=METODOS_PAGO)


@admin_bp.route('/solicitud/<int:sid>/estado', methods=['POST'])
def cambiar_estado(sid):
    sol    = db.get_or_404(Solicitud, sid)
    estado = request.form.get('estado', sol.estado)
    if estado not in ESTADOS_SOLICITUD:
        flash('Estado no válido', 'danger')
        return redirect(url_for('admin.ver_solicitud', sid=sid))

    trans = sol.transaccion_activa()
    if estado == 'cancelada' and trans and trans.estado_pago == 'pendiente':
        trans.estado_pago = 'cancelado'
        trans.oferta.estado = 'vista'
    sol.estado      = estado
    sol.notas_admin = request.form.get('notas_admin', '').strip()[:5000]
    db.session.commit()
    flash(f'Estado actualizado: {sol.estado}', 'success')
    return redirect(url_for('admin.ver_solicitud', sid=sid))


# ── Ofertas ───────────────────────────────────────────────────────────────────

@admin_bp.route('/oferta/<int:oid>/estado', methods=['POST'])
def cambiar_estado_oferta(oid):
    """Marcar como vista o rechazar. Para aceptar se usa aceptar_oferta (calcula la comisión)."""
    oferta = db.get_or_404(Oferta, oid)
    estado = request.form.get('estado', 'vista')
    if estado not in ('vista', 'rechazada'):
        flash('Acción no válida', 'danger')
        return redirect(url_for('admin.ver_solicitud', sid=oferta.solicitud_id))
    if oferta.estado == 'aceptada':
        flash('Esa oferta está aceptada; cancela primero su transacción', 'warning')
        return redirect(url_for('admin.ver_solicitud', sid=oferta.solicitud_id))
    oferta.estado = estado
    notas = request.form.get('notas')
    if notas is not None:
        oferta.notas_broker = notas.strip()[:2000]
    db.session.commit()
    flash('Oferta actualizada', 'success')
    return redirect(url_for('admin.ver_solicitud', sid=oferta.solicitud_id))


@admin_bp.route('/oferta/<int:oid>/aceptar', methods=['POST'])
def aceptar_oferta(oid):
    """
    Acepta la oferta de un proveedor: aplica la comisión del broker, crea la
    transacción (pendiente de pago) y rechaza el resto de ofertas abiertas.
    """
    oferta = db.get_or_404(Oferta, oid)
    sol = oferta.solicitud
    volver = redirect(url_for('admin.ver_solicitud', sid=sol.id))

    if sol.transaccion_activa():
        flash('Esta solicitud ya tiene una transacción en curso', 'warning')
        return volver
    if sol.estado in ('completada', 'cancelada'):
        flash('La solicitud está cerrada', 'warning')
        return volver

    com = config_svc.comisiones()
    try:
        porcentaje = Decimal(request.form.get('porcentaje', '').strip() or str(com['comision_default']))
    except InvalidOperation:
        flash('Porcentaje de comisión no válido', 'danger')
        return volver
    if not (com['comision_minima'] <= porcentaje <= com['comision_maxima']):
        flash(f"La comisión debe estar entre {com['comision_minima']}% y {com['comision_maxima']}%", 'danger')
        return volver

    oferta.calcular_precio_cliente(porcentaje)
    oferta.estado = 'aceptada'
    for otra in sol.ofertas.filter(Oferta.id != oferta.id, Oferta.estado.in_(['nueva', 'vista'])):
        otra.estado = 'rechazada'

    trans = Transaccion(
        solicitud_id=sol.id, oferta_id=oferta.id,
        cliente_id=sol.cliente_id, proveedor_id=oferta.proveedor_id,
        precio_proveedor=oferta.precio, precio_cliente=oferta.precio_cliente,
        comision_broker=oferta.margen_broker, estado_pago='pendiente',
    )
    trans.calcular_comision()
    db.session.add(trans)
    sol.estado = 'en_gestion'
    db.session.commit()
    log_transaction(current_app, trans, 'creada')
    flash(f'✅ Oferta aceptada. Precio al cliente: RD${trans.precio_cliente:,.2f} '
          f'(comisión RD${trans.comision_broker:,.2f})', 'success')
    return volver


# ── Transacciones ─────────────────────────────────────────────────────────────

@admin_bp.route('/transaccion/<int:tid>/pagar', methods=['POST'])
def pagar_transaccion(tid):
    trans = db.get_or_404(Transaccion, tid)
    if trans.estado_pago != 'pendiente':
        flash('La transacción no está pendiente', 'warning')
        return redirect(url_for('admin.ver_solicitud', sid=trans.solicitud_id))
    metodo = request.form.get('metodo_pago', 'efectivo')
    trans.metodo_pago = metodo if metodo in METODOS_PAGO else 'otro'
    trans.estado_pago = 'pagado'
    trans.fecha_pago  = ahora_utc()
    trans.notas = request.form.get('notas', '').strip()[:2000] or trans.notas
    trans.solicitud.estado = 'completada'
    db.session.commit()
    log_transaction(current_app, trans, 'pagada')
    flash(f'💰 Pago registrado. Comisión ganada: RD${trans.comision_broker:,.2f}', 'success')
    return redirect(url_for('admin.ver_solicitud', sid=trans.solicitud_id))


@admin_bp.route('/transaccion/<int:tid>/cancelar', methods=['POST'])
def cancelar_transaccion(tid):
    """Cancela una venta pendiente y reabre la solicitud para aceptar otra oferta."""
    trans = db.get_or_404(Transaccion, tid)
    if trans.estado_pago != 'pendiente':
        flash('Solo se pueden cancelar transacciones pendientes', 'warning')
        return redirect(url_for('admin.ver_solicitud', sid=trans.solicitud_id))
    trans.estado_pago = 'cancelado'
    trans.oferta.estado = 'vista'
    trans.solicitud.estado = 'en_gestion'
    db.session.commit()
    log_transaction(current_app, trans, 'cancelada')
    flash('Transacción cancelada. Puedes aceptar otra oferta.', 'info')
    return redirect(url_for('admin.ver_solicitud', sid=trans.solicitud_id))


# ── Notificaciones manuales ───────────────────────────────────────────────────

@admin_bp.route('/notificar-proveedores/<int:sid>', methods=['POST'])
def notificar_proveedores(sid):
    """Envía la solicitud a los proveedores verificados (WhatsApp + Push) en segundo plano."""
    sol = db.get_or_404(Solicitud, sid)
    if not sol.acepta_ofertas:
        flash('Esta solicitud ya no recibe ofertas', 'warning')
        return redirect(url_for('admin.ver_solicitud', sid=sid))

    total = Usuario.query.filter_by(rol='proveedor', activo=True, verificado=True).count()
    if sol.estado == 'pendiente':
        sol.estado = 'en_gestion'
    db.session.commit()

    en_segundo_plano(tarea_notificar_proveedores, sol.id)
    flash(f'📤 Enviando a {total} proveedores verificados. '
          f'Revisa el resultado en el log de notificaciones.', 'success')
    return redirect(url_for('admin.ver_solicitud', sid=sid))


@admin_bp.route('/notificar-cliente/<int:sid>', methods=['POST'])
def notificar_cliente(sid):
    """Avisa al cliente que hay respuesta (sin revelar al proveedor)."""
    sol = db.get_or_404(Solicitud, sid)
    try:
        if notificar_cliente_oferta_disponible(sol):
            flash('✅ Cliente notificado por WhatsApp', 'success')
        else:
            flash('⚠️ WhatsApp no configurado o número inválido', 'warning')
    except Exception as e:
        flash(f'Error: {e}', 'danger')
    return redirect(url_for('admin.ver_solicitud', sid=sid))


# ── Proveedores ───────────────────────────────────────────────────────────────

@admin_bp.route('/proveedores')
def proveedores():
    lista = Usuario.query.filter_by(rol='proveedor')\
        .order_by(Usuario.verificado.asc(), Usuario.created_at.desc()).all()
    return render_template('admin/proveedores.html', proveedores=lista)


@admin_bp.route('/proveedor/<int:uid>/toggle', methods=['POST'])
def toggle_proveedor(uid):
    """accion = verificar | desactivar | activar"""
    u = db.get_or_404(Usuario, uid)
    if u.rol != 'proveedor':
        abort(404)
    accion = request.form.get('accion')
    if accion is None:   # compatibilidad con el formulario antiguo
        accion = 'desactivar' if u.activo else 'activar'

    if accion == 'verificar':
        u.activo, u.verificado = True, True
        msg = 'Proveedor verificado'
    elif accion == 'desactivar':
        u.activo = False
        msg = 'Proveedor desactivado'
    elif accion == 'activar':
        u.activo, u.verificado = True, True
        msg = 'Proveedor activado'
    else:
        flash('Acción no válida', 'danger')
        return redirect(url_for('admin.proveedores'))
    db.session.commit()
    flash(msg, 'success')
    return redirect(url_for('admin.proveedores'))


@admin_bp.route('/rating/<int:rid>/visibilidad', methods=['POST'])
def toggle_rating(rid):
    r = db.get_or_404(Rating, rid)
    r.visible = not r.visible
    db.session.commit()
    flash('Reseña ' + ('visible' if r.visible else 'oculta'), 'success')
    return redirect(request.referrer or url_for('admin.proveedores'))


# ── Log de notificaciones ─────────────────────────────────────────────────────

@admin_bp.route('/notificaciones')
def notificaciones():
    logs = Notificacion.query.order_by(Notificacion.created_at.desc()).limit(100).all()
    return render_template('admin/notificaciones.html', logs=logs)


# ── Configuración ─────────────────────────────────────────────────────────────

@admin_bp.route('/configuracion', methods=['GET', 'POST'])
def configuracion():
    if request.method == 'POST':
        error = config_svc.guardar_comisiones(request.form)
        if error:
            flash(error, 'danger')
            return redirect(url_for('admin.configuracion'))

        for secreto in config_svc.CLAVES_SECRETAS:
            if request.form.get(f'borrar_{secreto}'):
                config_svc.borrar_secreto(secreto)
        config_svc.guardar_config(request.form)

        from services.push_svc import reiniciar_firebase
        reiniciar_firebase()
        flash('✅ Configuración guardada', 'success')
        return redirect(url_for('admin.configuracion'))

    return render_template('admin/configuracion.html', cfg=config_svc.valores_para_formulario())


@admin_bp.route('/configuracion/test-whatsapp', methods=['POST'])
def test_whatsapp():
    """Envía mensaje de prueba para verificar la integración."""
    from services.whatsapp_svc import _enviar, _cfg
    instance, token = _cfg()
    numero = request.form.get('numero', '').strip()
    if not instance or not token:
        return jsonify({'ok': False, 'msg': 'Green API no configurada'})
    if not numero:
        return jsonify({'ok': False, 'msg': 'Número requerido'})
    ok = _enviar(numero, '✅ *BuscatodoRD* — Conexión WhatsApp verificada correctamente 🎉')
    return jsonify({'ok': ok, 'msg': 'Mensaje enviado' if ok else 'Error al enviar'})
