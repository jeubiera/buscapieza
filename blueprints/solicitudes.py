from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app
from flask_login import login_required, current_user
from models import db, Solicitud, SolicitudFoto, Categoria, Provincia
from services.cloudinary_svc import subir_imagen
from services.whatsapp_svc import notificar_broker_nueva_solicitud
from services.push_svc import notificar_nueva_solicitud

sol_bp = Blueprint('solicitudes', __name__)

ALLOWED = {'png', 'jpg', 'jpeg', 'webp', 'gif'}

def _allowed(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED

@sol_bp.route('/nueva', methods=['GET', 'POST'])
@login_required
def nueva():
    if current_user.rol == 'proveedor':
        flash('Los proveedores no pueden publicar solicitudes', 'warning')
        return redirect(url_for('main.index'))

    categorias = Categoria.query.filter_by(activa=True).all()
    provincias  = Provincia.query.order_by(Provincia.nombre).all()

    if request.method == 'POST':
        sol = Solicitud(
            cliente_id   = current_user.id,
            categoria_id = request.form.get('categoria_id') or None,
            provincia_id = request.form.get('provincia_id') or current_user.provincia_id,
            titulo       = request.form.get('titulo', '').strip(),
            descripcion  = request.form.get('descripcion', '').strip(),
            presupuesto  = request.form.get('presupuesto') or None,
            urgencia     = request.form.get('urgencia', 'normal'),
            estado       = 'pendiente'
        )
        db.session.add(sol)
        db.session.flush()
        sol.generar_codigo()

        # ── Subir fotos (hasta 6) ──────────────────────────────────────────
        fotos = request.files.getlist('fotos')
        subidas = 0
        for i, foto in enumerate(fotos[:6]):
            if foto and foto.filename and _allowed(foto.filename):
                try:
                    url, pid = subir_imagen(foto, carpeta='buscapieza/solicitudes')
                    db.session.add(SolicitudFoto(
                        solicitud_id = sol.id,
                        url          = url,
                        public_id    = pid,
                        es_principal = (i == 0),
                        orden        = i
                    ))
                    subidas += 1
                except Exception as e:
                    current_app.logger.error(f"Error subiendo foto {i}: {e}")

        db.session.commit()

        # ── Notificaciones ─────────────────────────────────────────────────
        try:
            notificar_broker_nueva_solicitud(sol)   # WhatsApp al broker
        except Exception as e:
            current_app.logger.error(f"WA broker error: {e}")

        try:
            notificar_nueva_solicitud(sol)           # Push al broker + proveedores
        except Exception as e:
            current_app.logger.error(f"Push error: {e}")

        foto_txt = f" con {subidas} foto(s)" if subidas else ""
        flash(f'✅ Solicitud {sol.codigo} publicada{foto_txt}. Te contactaremos pronto.', 'success')
        return redirect(url_for('solicitudes.mis_solicitudes'))

    return render_template('solicitudes/nueva.html', categorias=categorias, provincias=provincias)


@sol_bp.route('/mis-solicitudes')
@login_required
def mis_solicitudes():
    sols = Solicitud.query.filter_by(cliente_id=current_user.id)\
        .order_by(Solicitud.created_at.desc()).all()
    return render_template('solicitudes/mis_solicitudes.html', solicitudes=sols)


@sol_bp.route('/buscar')
def buscar():
    """
    Búsqueda avanzada de solicitudes con múltiples filtros
    Accesible para proveedores y usuarios públicos
    """
    # Obtener parámetros de búsqueda
    texto = request.args.get('q', '').strip()
    categoria_id = request.args.get('categoria', type=int)
    provincia_id = request.args.get('provincia', type=int)
    estado = request.args.get('estado', '').strip()
    urgencia = request.args.get('urgencia', '').strip()
    presupuesto_min = request.args.get('presupuesto_min', type=float)
    presupuesto_max = request.args.get('presupuesto_max', type=float)
    orden = request.args.get('orden', 'recientes')  # recientes, antiguos, presupuesto

    # Query base
    query = Solicitud.query

    # Filtro de texto (busca en título y descripción)
    if texto:
        query = query.filter(
            (Solicitud.titulo.contains(texto)) |
            (Solicitud.descripcion.contains(texto))
        )

    # Filtro por categoría
    if categoria_id:
        query = query.filter(Solicitud.categoria_id == categoria_id)

    # Filtro por provincia
    if provincia_id:
        query = query.filter(Solicitud.provincia_id == provincia_id)

    # Filtro por estado
    if estado and estado != 'todos':
        query = query.filter(Solicitud.estado == estado)
    else:
        # Por defecto mostrar solo activas para público
        if not current_user.is_authenticated or current_user.rol != 'admin':
            query = query.filter(Solicitud.estado.in_(['pendiente', 'en_gestion']))

    # Filtro por urgencia
    if urgencia and urgencia != 'todas':
        query = query.filter(Solicitud.urgencia == urgencia)

    # Filtro por rango de presupuesto
    if presupuesto_min is not None:
        query = query.filter(Solicitud.presupuesto >= presupuesto_min)
    if presupuesto_max is not None:
        query = query.filter(Solicitud.presupuesto <= presupuesto_max)

    # Ordenamiento
    if orden == 'antiguos':
        query = query.order_by(Solicitud.created_at.asc())
    elif orden == 'presupuesto_desc':
        query = query.order_by(Solicitud.presupuesto.desc().nullslast())
    elif orden == 'presupuesto_asc':
        query = query.order_by(Solicitud.presupuesto.asc().nullslast())
    else:  # recientes (default)
        query = query.order_by(Solicitud.created_at.desc())

    # Paginación
    page = request.args.get('page', 1, type=int)
    per_page = 20
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    # Obtener listas para filtros
    categorias = Categoria.query.filter_by(activa=True).order_by(Categoria.nombre).all()
    provincias = Provincia.query.order_by(Provincia.nombre).all()

    return render_template('solicitudes/buscar.html',
        solicitudes=pagination.items,
        pagination=pagination,
        categorias=categorias,
        provincias=provincias,
        # Mantener filtros actuales en el template
        filtros={
            'q': texto,
            'categoria': categoria_id,
            'provincia': provincia_id,
            'estado': estado,
            'urgencia': urgencia,
            'presupuesto_min': presupuesto_min,
            'presupuesto_max': presupuesto_max,
            'orden': orden
        }
    )


@sol_bp.route('/<int:sid>')
@login_required
def detalle(sid):
    sol = Solicitud.query.get_or_404(sid)
    if sol.cliente_id != current_user.id and current_user.rol != 'admin':
        flash('Acceso denegado', 'danger')
        return redirect(url_for('main.index'))
    return render_template('solicitudes/detalle.html', sol=sol)
