from collections import OrderedDict
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps

from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify, abort, current_app
from flask_login import login_required, current_user
from sqlalchemy import func

from models import (db, Solicitud, Oferta, Usuario, Categoria, Provincia, Notificacion,
                    Transaccion, Rating, Publicacion, Interes, Propuesta, Coincidencia, ahora_utc,
                    ESTADOS_SOLICITUD, ESTADOS_PUBLICACION, ESTADOS_INTERES, METODOS_PAGO)
from services import config_svc
from services.tareas import en_segundo_plano
from services.notificaciones import (tarea_notificar_proveedores, tarea_estado_publicacion, tarea_propuesta,
                                     tarea_coincidencias_publicacion, tarea_ofrecer_coincidencia)
from services import negociacion
from services.negociacion import ErrorNegocio
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
        'publicaciones_pendientes': Publicacion.query.filter_by(estado='pendiente').count(),
        'publicaciones_activas': Publicacion.query.filter_by(estado='publicada').count(),
        'intereses_nuevos': Interes.query.filter_by(estado='nuevo').count(),
        'coincidencias_nuevas': Coincidencia.query.filter_by(estado='nueva').count(),
        'respuestas_pendientes': Propuesta.query.filter_by(estado='pendiente', autor='usuario').count(),
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
    coincidencias = sol.coincidencias.filter(Coincidencia.estado != 'descartada')\
        .order_by(Coincidencia.puntaje.desc()).all()
    return render_template('admin/ver_solicitud.html', sol=sol, ofertas=ofertas, trans=trans,
                           coincidencias=coincidencias,
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

def _volver_a_origen(trans):
    if trans.publicacion_id:
        return redirect(url_for('admin.ver_publicacion', pid=trans.publicacion_id))
    return redirect(url_for('admin.ver_solicitud', sid=trans.solicitud_id))


@admin_bp.route('/transaccion/<int:tid>/pagar', methods=['POST'])
def pagar_transaccion(tid):
    trans = db.get_or_404(Transaccion, tid)
    if trans.estado_pago != 'pendiente':
        flash('La transacción no está pendiente', 'warning')
        return _volver_a_origen(trans)
    metodo = request.form.get('metodo_pago', 'efectivo')
    trans.metodo_pago = metodo if metodo in METODOS_PAGO else 'otro'
    trans.estado_pago = 'pagado'
    trans.fecha_pago  = ahora_utc()
    trans.notas = request.form.get('notas', '').strip()[:2000] or trans.notas
    if trans.solicitud:
        trans.solicitud.estado = 'completada'
    if trans.publicacion:
        trans.publicacion.estado = 'vendida'
    db.session.commit()
    log_transaction(current_app, trans, 'pagada')
    flash(f'💰 Pago registrado. Comisión ganada: RD${trans.comision_broker:,.2f}', 'success')
    return _volver_a_origen(trans)


@admin_bp.route('/transaccion/<int:tid>/cancelar', methods=['POST'])
def cancelar_transaccion(tid):
    """Cancela una venta pendiente y reabre la solicitud para aceptar otra oferta."""
    trans = db.get_or_404(Transaccion, tid)
    if trans.estado_pago != 'pendiente':
        flash('Solo se pueden cancelar transacciones pendientes', 'warning')
        return _volver_a_origen(trans)
    trans.estado_pago = 'cancelado'
    if trans.oferta:
        trans.oferta.estado = 'vista'
    if trans.solicitud:
        trans.solicitud.estado = 'en_gestion'
    if trans.publicacion:
        trans.publicacion.estado = 'publicada'
    db.session.commit()
    log_transaction(current_app, trans, 'cancelada')
    flash('Venta cancelada. ' + ('El artículo vuelve a estar publicado.' if trans.publicacion
                                 else 'Puedes aceptar otra oferta.'), 'info')
    return _volver_a_origen(trans)


# ── Compraventa ───────────────────────────────────────────────────────────────

@admin_bp.route('/publicaciones')
def publicaciones():
    estado = request.args.get('estado', '')
    query = Publicacion.query
    if estado in ESTADOS_PUBLICACION:
        query = query.filter_by(estado=estado)
    else:
        estado = ''
    # Primero lo que requiere acción: pendientes de revisar
    orden = db.case((Publicacion.estado == 'pendiente', 0), (Publicacion.estado == 'reservada', 1), else_=2)
    pag = query.order_by(orden, Publicacion.updated_at.desc()).paginate(
        page=request.args.get('page', 1, type=int), per_page=25, error_out=False)
    conteos = dict(db.session.query(Publicacion.estado, func.count(Publicacion.id)).group_by(Publicacion.estado).all())
    return render_template('admin/publicaciones.html', publicaciones=pag, estado=estado, conteos=conteos,
                           estados=ESTADOS_PUBLICACION)


@admin_bp.route('/publicacion/<int:pid>')
def ver_publicacion(pid):
    pub = db.get_or_404(Publicacion, pid)
    intereses = pub.intereses.order_by(Interes.created_at.desc()).all()
    coincidencias = pub.coincidencias.filter(Coincidencia.estado != 'descartada')\
        .order_by(Coincidencia.puntaje.desc()).all()
    comisiones = config_svc.comisiones()
    pendiente = pub.propuesta_vendedor_pendiente()
    ultima_admin = (pub.propuestas.filter_by(tipo='vendedor', autor='admin')
                    .order_by(Propuesta.created_at.desc()).first())
    # Los formularios parten de lo último negociado (no del precio pedido ni de la comisión por defecto)
    sugerido = {
        'monto': next(v for v in (pendiente.monto if pendiente else None,
                                  ultima_admin.monto if ultima_admin else None,
                                  pub.precio_vendedor, pub.precio_pedido) if v is not None),
        'porcentaje': next(v for v in (ultima_admin.porcentaje if ultima_admin else None,
                                       pub.porcentaje_margen, comisiones['comision_default']) if v is not None),
        'mostrar': ultima_admin.mostrar_precio if ultima_admin and ultima_admin.mostrar_precio is not None
                   else pub.mostrar_precio,
    }
    return render_template('admin/ver_publicacion.html', pub=pub, intereses=intereses,
                           trans=pub.transaccion_activa(), comisiones=comisiones,
                           metodos_pago=METODOS_PAGO, estados_interes=ESTADOS_INTERES,
                           propuestas_vendedor=pub.propuestas_vendedor(),
                           propuesta_vendedor=pendiente, sugerido=sugerido,
                           coincidencias=coincidencias)


def _decimal_form(nombre, minimo=Decimal('0.01')):
    try:
        d = Decimal((request.form.get(nombre) or '').replace(',', '').strip())
    except InvalidOperation:
        return None
    return d.quantize(Decimal('0.01')) if d >= minimo else None


@admin_bp.route('/publicacion/<int:pid>/aprobar', methods=['POST'])
def aprobar_publicacion(pid):
    """Publica directamente con el precio ya acordado (p. ej. por teléfono) o actualiza los precios."""
    pub = db.get_or_404(Publicacion, pid)
    volver = redirect(url_for('admin.ver_publicacion', pid=pid))
    precio_vendedor = _decimal_form('precio_vendedor')
    if precio_vendedor is None:
        flash('Indica el precio acordado con el vendedor', 'danger')
        return volver
    try:
        porcentaje = Decimal(request.form.get('porcentaje', '').strip() or str(config_svc.comisiones()['comision_default']))
        era_nueva = negociacion.publicar(pub, precio_vendedor, porcentaje, request.form.get('mostrar_precio'))
    except InvalidOperation:
        flash('Porcentaje de comisión no válido', 'danger')
        return volver
    except ErrorNegocio as e:
        db.session.rollback()
        flash(str(e), 'danger')
        return volver
    pub.notas_admin = request.form.get('notas_admin', '').strip()[:5000] or pub.notas_admin
    db.session.commit()
    if era_nueva:
        en_segundo_plano(tarea_estado_publicacion, pub.id)
    en_segundo_plano(tarea_coincidencias_publicacion, pub.id)
    flash(f"✅ {'Publicada' if era_nueva else 'Precios actualizados'}: RD${pub.precio_publico:,.0f} al público "
          f"(vendedor RD${pub.precio_vendedor:,.2f}, comisión RD${pub.comision_estimada:,.2f}) · "
          f"precio {'visible' if pub.mostrar_precio else 'oculto'}", 'success')
    return volver


@admin_bp.route('/publicacion/<int:pid>/proponer', methods=['POST'])
def proponer_a_vendedor(pid):
    """Envía al vendedor una propuesta de cuánto recibirá (con la comisión y visibilidad ya decididas)."""
    pub = db.get_or_404(Publicacion, pid)
    volver = redirect(url_for('admin.ver_publicacion', pid=pid))
    monto = _decimal_form('monto')
    if monto is None:
        flash('Indica cuánto recibiría el vendedor', 'danger')
        return volver
    try:
        porcentaje = Decimal(request.form.get('porcentaje', '').strip() or str(config_svc.comisiones()['comision_default']))
        prop = negociacion.proponer_a_vendedor(pub, monto, porcentaje, request.form.get('mostrar_precio'),
                                               request.form.get('mensaje', '').strip()[:1000] or None)
        db.session.commit()
    except InvalidOperation:
        flash('Porcentaje de comisión no válido', 'danger')
        return volver
    except ErrorNegocio as e:
        db.session.rollback()
        flash(str(e), 'danger')
        return volver
    en_segundo_plano(tarea_propuesta, prop.id, 'nueva')
    flash(f'📨 Propuesta enviada al vendedor: recibe RD${monto:,.2f}. Se publicará sola si acepta.', 'success')
    return volver


@admin_bp.route('/publicacion/<int:pid>/aceptar-vendedor', methods=['POST'])
def aceptar_contrapropuesta_vendedor(pid):
    pub = db.get_or_404(Publicacion, pid)
    try:
        prop = negociacion.admin_acepta_vendedor(pub)
        db.session.commit()
    except ErrorNegocio as e:
        db.session.rollback()
        flash(str(e), 'danger')
        return redirect(url_for('admin.ver_publicacion', pid=pid))
    en_segundo_plano(tarea_estado_publicacion, pub.id)
    en_segundo_plano(tarea_coincidencias_publicacion, pub.id)
    flash(f'✅ Aceptaste RD${prop.monto:,.2f} para el vendedor. Publicada a RD${pub.precio_publico:,.0f}.', 'success')
    return redirect(url_for('admin.ver_publicacion', pid=pid))


@admin_bp.route('/publicacion/<int:pid>/rechazar', methods=['POST'])
def rechazar_publicacion(pid):
    pub = db.get_or_404(Publicacion, pid)
    motivo = request.form.get('motivo', '').strip()[:2000]
    if not motivo:
        flash('Escribe el motivo: el vendedor lo recibirá para corregir la publicación', 'danger')
    elif pub.estado not in ('pendiente', 'publicada'):
        flash('Solo se pueden rechazar publicaciones pendientes o publicadas sin venta en curso', 'warning')
    else:
        pub.estado, pub.motivo_rechazo = 'rechazada', motivo
        db.session.commit()
        en_segundo_plano(tarea_estado_publicacion, pub.id)
        flash('Publicación rechazada; se avisó al vendedor', 'info')
    return redirect(url_for('admin.ver_publicacion', pid=pid))


@admin_bp.route('/publicacion/<int:pid>/estado', methods=['POST'])
def estado_publicacion(pid):
    """Retirar del catálogo o reactivar."""
    pub = db.get_or_404(Publicacion, pid)
    accion = request.form.get('accion')
    if accion == 'retirar' and pub.estado in ('pendiente', 'publicada', 'rechazada'):
        pub.estado = 'retirada'
        flash('Publicación retirada del catálogo', 'info')
    elif accion == 'reactivar' and pub.estado == 'retirada':
        pub.estado = 'publicada' if pub.precio_publico is not None else 'pendiente'
        flash('Publicación reactivada', 'success')
    else:
        flash('Acción no válida para el estado actual', 'warning')
        return redirect(url_for('admin.ver_publicacion', pid=pid))
    db.session.commit()
    return redirect(url_for('admin.ver_publicacion', pid=pid))


@admin_bp.route('/interes/<int:iid>', methods=['POST'])
def actualizar_interes(iid):
    it = db.get_or_404(Interes, iid)
    estado = request.form.get('estado')
    if estado in ESTADOS_INTERES:
        it.estado = estado
    notas = request.form.get('notas_admin')
    if notas is not None:
        it.notas_admin = notas.strip()[:2000]
    db.session.commit()
    flash('Interesado actualizado', 'success')
    return redirect(url_for('admin.ver_publicacion', pid=it.publicacion_id))


@admin_bp.route('/publicacion/<int:pid>/vender', methods=['POST'])
def vender_publicacion(pid):
    """
    Registra a mano la venta negociada con un interesado: precio final al comprador y lo que
    recibe el vendedor. La comisión es la diferencia real. Queda pendiente de pago.
    """
    pub = db.get_or_404(Publicacion, pid)
    volver = redirect(url_for('admin.ver_publicacion', pid=pid))
    it = db.session.get(Interes, request.form.get('interes_id', type=int) or 0)
    precio_final = _decimal_form('precio_final')
    precio_vendedor = _decimal_form('precio_vendedor')
    if not it:
        flash('Elige al comprador entre los interesados', 'danger')
        return volver
    if precio_final is None or precio_vendedor is None:
        flash('Indica el precio final al comprador y lo que recibe el vendedor', 'danger')
        return volver
    try:
        trans = negociacion.registrar_venta(pub, it, precio_final, precio_vendedor,
                                            request.form.get('notas', '').strip()[:2000] or None)
        db.session.commit()
    except ErrorNegocio as e:
        db.session.rollback()
        flash(str(e), 'danger')
        return volver
    flash(f'🤝 Venta registrada con {it.comprador.nombre}: RD${trans.precio_cliente:,.2f} '
          f'(comisión RD${trans.comision_broker:,.2f}). Pendiente de pago.', 'success')
    return volver


@admin_bp.route('/interes/<int:iid>/cotizar', methods=['POST'])
def cotizar_interes(iid):
    """Envía un precio privado a un interesado (solo lo ve esa persona)."""
    it = db.get_or_404(Interes, iid)
    volver = redirect(url_for('admin.ver_publicacion', pid=it.publicacion_id))
    monto = _decimal_form('monto')
    if monto is None:
        flash('Indica el precio para este comprador', 'danger')
        return volver
    try:
        prop = negociacion.cotizar_a_comprador(it, monto, request.form.get('mensaje', '').strip()[:1000] or None)
        db.session.commit()
    except ErrorNegocio as e:
        db.session.rollback()
        flash(str(e), 'danger')
        return volver
    en_segundo_plano(tarea_propuesta, prop.id, 'nueva')
    flash(f'📨 Precio enviado a {it.comprador.nombre}: RD${monto:,.2f}', 'success')
    return volver


@admin_bp.route('/interes/<int:iid>/aceptar-oferta', methods=['POST'])
def aceptar_oferta_comprador(iid):
    it = db.get_or_404(Interes, iid)
    try:
        trans = negociacion.admin_acepta_comprador(it)
        db.session.commit()
    except ErrorNegocio as e:
        db.session.rollback()
        flash(str(e), 'danger')
        return redirect(url_for('admin.ver_publicacion', pid=it.publicacion_id))
    flash(f'🤝 Oferta aceptada: venta a {it.comprador.nombre} por RD${trans.precio_cliente:,.2f} '
          f'(comisión RD${trans.comision_broker:,.2f}). Pendiente de pago.', 'success')
    return redirect(url_for('admin.ver_publicacion', pid=it.publicacion_id))


# ── Coincidencias (oferta ↔ demanda) ─────────────────────────────────────────

@admin_bp.route('/coincidencias')
def coincidencias():
    estado = request.args.get('estado', 'nueva')
    query = Coincidencia.query.join(Publicacion).join(Solicitud)
    if estado in ('nueva', 'ofrecida', 'descartada'):
        query = query.filter(Coincidencia.estado == estado)
    else:
        estado = ''
    lista = query.order_by(Coincidencia.created_at.desc(), Coincidencia.puntaje.desc()).limit(200).all()
    conteos = dict(db.session.query(Coincidencia.estado, func.count(Coincidencia.id)).group_by(Coincidencia.estado).all())
    return render_template('admin/coincidencias.html', coincidencias=lista, estado=estado, conteos=conteos)


@admin_bp.route('/coincidencias/recalcular', methods=['POST'])
def recalcular_coincidencias():
    from services.coincidencias import recalcular_todo
    n = recalcular_todo()
    flash(f'🎯 {n} coincidencia(s) nueva(s) encontrada(s)' if n else 'No hay coincidencias nuevas', 'info')
    return redirect(url_for('admin.coincidencias'))


@admin_bp.route('/coincidencia/<int:cid>/ofrecer', methods=['POST'])
def ofrecer_coincidencia(cid):
    """Ofrece el artículo al cliente que lo buscaba y lo anota como interesado."""
    c = db.get_or_404(Coincidencia, cid)
    volver = redirect(request.referrer or url_for('admin.coincidencias'))
    pub, sol = c.publicacion, c.solicitud
    if pub.estado != 'publicada':
        flash('El artículo ya no está disponible', 'warning')
        return volver
    it = Interes.query.filter_by(publicacion_id=pub.id, comprador_id=sol.cliente_id).first()
    if not it:
        it = Interes(publicacion_id=pub.id, comprador_id=sol.cliente_id, estado='contactado',
                     mensaje=f'Coincidencia con su búsqueda {sol.codigo}: {sol.titulo}'[:1000])
        db.session.add(it)
    c.estado = 'ofrecida'
    db.session.commit()
    en_segundo_plano(tarea_ofrecer_coincidencia, c.id)
    flash(f'📨 Ofrecido a {sol.cliente.nombre} por WhatsApp; ya aparece entre los interesados de {pub.codigo}.', 'success')
    return volver


@admin_bp.route('/coincidencia/<int:cid>/descartar', methods=['POST'])
def descartar_coincidencia(cid):
    c = db.get_or_404(Coincidencia, cid)
    c.estado = 'descartada'
    db.session.commit()
    flash('Coincidencia descartada', 'info')
    return redirect(request.referrer or url_for('admin.coincidencias'))


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
