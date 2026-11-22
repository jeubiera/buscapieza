from decimal import Decimal, InvalidOperation

from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app, abort
from flask_login import login_required, current_user
from models import (db, Solicitud, SolicitudFoto, Categoria, Provincia, Rating,
                    URGENCIAS, ESTADOS_SOLICITUD)
from services.archivos import es_imagen_valida
from services.cloudinary_svc import subir_imagen
from services.tareas import en_segundo_plano
from services.notificaciones import tarea_nueva_solicitud

sol_bp = Blueprint('solicitudes', __name__)

MAX_FOTOS = 6


def _decimal_o_none(valor):
    valor = (valor or '').strip().replace(',', '')
    if not valor:
        return None
    try:
        d = Decimal(valor)
    except InvalidOperation:
        raise ValueError
    if d < 0 or d >= Decimal('10000000000'):
        raise ValueError
    return d.quantize(Decimal('0.01'))


@sol_bp.route('/nueva', methods=['GET', 'POST'])
@login_required
def nueva():
    if current_user.rol == 'proveedor':
        flash('Los proveedores no pueden publicar solicitudes', 'warning')
        return redirect(url_for('main.index'))

    categorias = Categoria.query.filter_by(activa=True).all()
    provincias  = Provincia.query.order_by(Provincia.nombre).all()

    if request.method == 'POST':
        f = request.form
        titulo      = f.get('titulo', '').strip()
        descripcion = f.get('descripcion', '').strip()
        cat_id      = f.get('categoria_id', type=int)
        prov_id     = f.get('provincia_id', type=int) or current_user.provincia_id
        urgencia    = f.get('urgencia', 'normal')

        errores = []
        if not titulo:
            errores.append('Indica qué estás buscando')
        elif len(titulo) > 200:
            errores.append('El título no puede pasar de 200 caracteres')
        if not descripcion:
            errores.append('La descripción es obligatoria')
        if cat_id and not db.session.get(Categoria, cat_id):
            cat_id = None
        if prov_id and not db.session.get(Provincia, prov_id):
            prov_id = None
        if urgencia not in URGENCIAS:
            urgencia = 'normal'
        try:
            presupuesto = _decimal_o_none(f.get('presupuesto'))
        except ValueError:
            presupuesto = None
            errores.append('El presupuesto debe ser un número positivo')

        if errores:
            for e in errores:
                flash(e, 'danger')
            return render_template('solicitudes/nueva.html', categorias=categorias,
                                   provincias=provincias, form=f), 400

        sol = Solicitud(
            cliente_id   = current_user.id,
            categoria_id = cat_id,
            provincia_id = prov_id,
            titulo       = titulo,
            descripcion  = descripcion,
            presupuesto  = presupuesto,
            urgencia     = urgencia,
            estado       = 'pendiente'
        )
        db.session.add(sol)
        db.session.flush()
        sol.generar_codigo()

        # ── Subir fotos (hasta 6) ──────────────────────────────────────────
        subidas = rechazadas = 0
        for foto in request.files.getlist('fotos')[:MAX_FOTOS]:
            if not foto or not foto.filename:
                continue
            if not es_imagen_valida(foto):
                rechazadas += 1
                continue
            try:
                url, pid = subir_imagen(foto, carpeta='buscapieza/solicitudes')
                db.session.add(SolicitudFoto(
                    solicitud_id = sol.id,
                    url          = url,
                    public_id    = pid,
                    es_principal = (subidas == 0),
                    orden        = subidas
                ))
                subidas += 1
            except Exception as e:
                rechazadas += 1
                current_app.logger.error(f"Error subiendo foto: {e}")

        db.session.commit()

        # ── Notificaciones (en segundo plano) ──────────────────────────────
        en_segundo_plano(tarea_nueva_solicitud, sol.id)

        foto_txt = f" con {subidas} foto(s)" if subidas else ""
        flash(f'✅ Solicitud {sol.codigo} publicada{foto_txt}. Te contactaremos pronto.', 'success')
        if rechazadas:
            flash(f'{rechazadas} archivo(s) no se subieron porque no son imágenes válidas.', 'warning')
        return redirect(url_for('solicitudes.mis_solicitudes'))

    return render_template('solicitudes/nueva.html', categorias=categorias, provincias=provincias, form={})


@sol_bp.route('/mis-solicitudes')
@login_required
def mis_solicitudes():
    sols = Solicitud.query.filter_by(cliente_id=current_user.id)\
        .order_by(Solicitud.created_at.desc()).all()
    return render_template('solicitudes/mis_solicitudes.html', solicitudes=sols)


@sol_bp.route('/buscar')
def buscar():
    """
    Búsqueda de solicitudes activas con filtros.
    Pública (no muestra datos del cliente). El admin además puede filtrar por cualquier estado.
    """
    es_admin = current_user.is_authenticated and current_user.rol == 'admin'

    texto = request.args.get('q', '').strip()[:100]
    categoria_id = request.args.get('categoria', type=int)
    provincia_id = request.args.get('provincia', type=int)
    estado = request.args.get('estado', '').strip()
    urgencia = request.args.get('urgencia', '').strip()
    presupuesto_min = request.args.get('presupuesto_min', type=float)
    presupuesto_max = request.args.get('presupuesto_max', type=float)
    orden = request.args.get('orden', 'recientes')

    query = Solicitud.query

    if texto:
        query = query.filter(
            (Solicitud.titulo.contains(texto)) |
            (Solicitud.descripcion.contains(texto))
        )
    if categoria_id:
        query = query.filter(Solicitud.categoria_id == categoria_id)
    if provincia_id:
        query = query.filter(Solicitud.provincia_id == provincia_id)

    if es_admin and estado in ESTADOS_SOLICITUD:
        query = query.filter(Solicitud.estado == estado)
    elif not (es_admin and estado == 'todos'):
        query = query.filter(Solicitud.estado.in_(['pendiente', 'en_gestion']))
        if not es_admin:
            estado = ''

    if urgencia in URGENCIAS:
        query = query.filter(Solicitud.urgencia == urgencia)
    if presupuesto_min is not None:
        query = query.filter(Solicitud.presupuesto >= presupuesto_min)
    if presupuesto_max is not None:
        query = query.filter(Solicitud.presupuesto <= presupuesto_max)

    if orden == 'antiguos':
        query = query.order_by(Solicitud.created_at.asc())
    elif orden == 'presupuesto_desc':
        query = query.order_by(Solicitud.presupuesto.desc().nullslast())
    elif orden == 'presupuesto_asc':
        query = query.order_by(Solicitud.presupuesto.asc().nullslast())
    else:
        orden = 'recientes'
        query = query.order_by(Solicitud.created_at.desc())

    page = request.args.get('page', 1, type=int)
    pagination = query.paginate(page=page, per_page=20, error_out=False)

    categorias = Categoria.query.filter_by(activa=True).order_by(Categoria.nombre).all()
    provincias = Provincia.query.order_by(Provincia.nombre).all()

    filtros = {
        'q': texto, 'categoria': categoria_id, 'provincia': provincia_id,
        'estado': estado, 'urgencia': urgencia,
        'presupuesto_min': presupuesto_min, 'presupuesto_max': presupuesto_max,
        'orden': orden,
    }
    return render_template('solicitudes/buscar.html',
        solicitudes=pagination.items,
        pagination=pagination,
        categorias=categorias,
        provincias=provincias,
        es_admin=es_admin,
        filtros=filtros,
        filtros_url={k: v for k, v in filtros.items() if v not in (None, '')},
    )


def _solicitud_del_cliente(sid):
    sol = db.get_or_404(Solicitud, sid)
    if sol.cliente_id != current_user.id and current_user.rol != 'admin':
        abort(403)
    return sol


@sol_bp.route('/<int:sid>')
@login_required
def detalle(sid):
    sol = db.get_or_404(Solicitud, sid)
    if sol.cliente_id != current_user.id and current_user.rol != 'admin':
        flash('Acceso denegado', 'danger')
        return redirect(url_for('main.index'))
    trans = sol.transaccion_activa()
    rating = trans.rating[0] if trans and trans.rating else None
    return render_template('solicitudes/detalle.html', sol=sol, trans=trans, rating=rating)


@sol_bp.route('/<int:sid>/calificar', methods=['POST'])
@login_required
def calificar(sid):
    """El cliente califica al proveedor cuando la compra está pagada."""
    sol = _solicitud_del_cliente(sid)
    if sol.cliente_id != current_user.id:
        abort(403)
    trans = sol.transaccion_activa()
    if not trans or trans.estado_pago != 'pagado':
        flash('Podrás calificar cuando la compra esté completada', 'warning')
        return redirect(url_for('solicitudes.detalle', sid=sid))
    if trans.rating:
        flash('Ya calificaste esta compra', 'info')
        return redirect(url_for('solicitudes.detalle', sid=sid))

    criterios = {}
    for campo in ('calidad_producto', 'tiempo_entrega', 'atencion_cliente', 'precio_justo'):
        valor = request.form.get(campo, type=int)
        if valor is None or not 1 <= valor <= 5:
            flash('Califica cada criterio de 1 a 5 estrellas', 'danger')
            return redirect(url_for('solicitudes.detalle', sid=sid))
        criterios[campo] = valor

    rating = Rating(
        transaccion_id=trans.id,
        proveedor_id=trans.proveedor_id,
        cliente_id=current_user.id,
        comentario=request.form.get('comentario', '').strip()[:1000] or None,
        **criterios,
    )
    rating.calcular_promedio()
    db.session.add(rating)
    db.session.commit()
    flash('⭐ ¡Gracias por tu calificación!', 'success')
    return redirect(url_for('solicitudes.detalle', sid=sid))
