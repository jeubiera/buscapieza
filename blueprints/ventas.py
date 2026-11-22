"""
Compraventa: los usuarios publican lo que venden, BuscatodoRD aprueba, acuerda el precio
con el vendedor y gestiona a los compradores interesados (el comprador nunca ve al vendedor).
"""
from decimal import Decimal, InvalidOperation

from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app, abort
from flask_login import login_required, current_user
from sqlalchemy import case

from models import (db, Publicacion, PublicacionFoto, Interes, Categoria, Provincia,
                    CONDICIONES)
from services.archivos import es_imagen_valida
from services.cloudinary_svc import subir_imagen, eliminar_imagen
from services.tareas import en_segundo_plano
from services.notificaciones import tarea_nueva_publicacion, tarea_nuevo_interes

ventas_bp = Blueprint('ventas', __name__)

MAX_FOTOS = 6
PRECIO_MAX = Decimal('10000000000')


def _decimal(valor, obligatorio=False, minimo=Decimal('0')):
    """Convierte texto a Decimal (2 decimales). Lanza ValueError si no es válido."""
    valor = (valor or '').strip().replace(',', '')
    if not valor:
        if obligatorio:
            raise ValueError
        return None
    try:
        d = Decimal(valor)
    except InvalidOperation:
        raise ValueError
    if d < minimo or d >= PRECIO_MAX:
        raise ValueError
    return d.quantize(Decimal('0.01'))


def _subir_fotos(pub, archivos, ya_hay=0):
    """Sube hasta completar MAX_FOTOS. Devuelve (subidas, rechazadas)."""
    subidas = rechazadas = 0
    for foto in archivos:
        if ya_hay + subidas >= MAX_FOTOS:
            break
        if not foto or not foto.filename:
            continue
        if not es_imagen_valida(foto):
            rechazadas += 1
            continue
        try:
            url, pid = subir_imagen(foto, carpeta='buscatodo/publicaciones')
        except Exception as e:
            current_app.logger.error(f'Error subiendo foto de publicación: {e}')
            rechazadas += 1
            continue
        orden = ya_hay + subidas
        db.session.add(PublicacionFoto(publicacion_id=pub.id, url=url, public_id=pid,
                                       es_principal=(orden == 0), orden=orden))
        subidas += 1
    return subidas, rechazadas


def _validar_formulario(f):
    """Valida los campos comunes de publicar/editar. Devuelve (datos, errores)."""
    errores = []
    datos = {
        'titulo': f.get('titulo', '').strip(),
        'descripcion': f.get('descripcion', '').strip(),
        'categoria_id': f.get('categoria_id', type=int),
        'provincia_id': f.get('provincia_id', type=int) or current_user.provincia_id,
        'condicion': f.get('condicion', 'usado'),
    }
    if not datos['titulo']:
        errores.append('Indica qué vendes')
    elif len(datos['titulo']) > 200:
        errores.append('El título no puede pasar de 200 caracteres')
    if len(datos['descripcion']) < 10:
        errores.append('Describe el artículo (al menos 10 caracteres)')
    if datos['categoria_id'] and not db.session.get(Categoria, datos['categoria_id']):
        datos['categoria_id'] = None
    if not datos['categoria_id']:
        errores.append('Elige una categoría')
    if datos['provincia_id'] and not db.session.get(Provincia, datos['provincia_id']):
        datos['provincia_id'] = None
    if datos['condicion'] not in CONDICIONES:
        datos['condicion'] = 'usado'
    try:
        datos['precio_pedido'] = _decimal(f.get('precio_pedido'), obligatorio=True, minimo=Decimal('1'))
    except ValueError:
        errores.append('Indica cuánto quieres recibir (número mayor que 0)')
    return datos, errores


def _contexto_form():
    return {
        'categorias': Categoria.query.filter_by(activa=True).order_by(Categoria.nombre).all(),
        'provincias': Provincia.query.order_by(Provincia.nombre).all(),
        'condiciones': CONDICIONES,
        'max_fotos': MAX_FOTOS,
    }


# ═════════════════════════════ CATÁLOGO PÚBLICO ═══════════════════════════════

@ventas_bp.route('/catalogo')
def catalogo():
    q = request.args.get('q', '').strip()[:100]
    categoria_id = request.args.get('categoria', type=int)
    provincia_id = request.args.get('provincia', type=int)
    condicion = request.args.get('condicion', '')
    orden = request.args.get('orden', 'recientes')

    query = Publicacion.query.filter(Publicacion.estado.in_(['publicada', 'reservada']))
    if q:
        query = query.filter(Publicacion.titulo.icontains(q, autoescape=True) |
                             Publicacion.descripcion.icontains(q, autoescape=True))
    if categoria_id:
        query = query.filter(Publicacion.categoria_id == categoria_id)
    if provincia_id:
        query = query.filter(Publicacion.provincia_id == provincia_id)
    if condicion in CONDICIONES:
        query = query.filter(Publicacion.condicion == condicion)
    else:
        condicion = ''

    # Ordenar por precio solo con los precios visibles: los ocultos van al final y sin
    # ordenarse entre sí, para no revelar su precio relativo.
    precio_visible = case((Publicacion.mostrar_precio.is_(True), Publicacion.precio_publico), else_=None)
    if orden == 'precio_asc':
        query = query.order_by(precio_visible.asc().nullslast(), Publicacion.publicada_en.desc())
    elif orden == 'precio_desc':
        query = query.order_by(precio_visible.desc().nullslast(), Publicacion.publicada_en.desc())
    else:
        orden = 'recientes'
        query = query.order_by(Publicacion.estado.asc(), Publicacion.publicada_en.desc())

    pag = query.paginate(page=request.args.get('page', 1, type=int), per_page=24, error_out=False)
    filtros = {'q': q, 'categoria': categoria_id, 'provincia': provincia_id, 'condicion': condicion, 'orden': orden}
    return render_template('ventas/catalogo.html', publicaciones=pag.items, pagination=pag, filtros=filtros,
                           filtros_url={k: v for k, v in filtros.items() if v not in (None, '')},
                           **_contexto_form())


@ventas_bp.route('/catalogo/<int:pid>')
def detalle(pid):
    pub = db.get_or_404(Publicacion, pid)
    es_dueno = current_user.is_authenticated and current_user.id == pub.vendedor_id
    es_admin = current_user.is_authenticated and current_user.rol == 'admin'
    if not pub.visible_en_catalogo and not (es_dueno or es_admin):
        abort(404)
    if not (es_dueno or es_admin):
        pub.vistas = (pub.vistas or 0) + 1
        db.session.commit()

    mi_interes = None
    if current_user.is_authenticated:
        mi_interes = Interes.query.filter_by(publicacion_id=pub.id, comprador_id=current_user.id).first()
    return render_template('ventas/detalle.html', pub=pub, es_dueno=es_dueno, es_admin=es_admin,
                           mi_interes=mi_interes)


@ventas_bp.route('/catalogo/<int:pid>/interes', methods=['POST'])
@login_required
def interes(pid):
    pub = db.get_or_404(Publicacion, pid)
    volver = redirect(url_for('ventas.detalle', pid=pid))
    if pub.estado != 'publicada':
        flash('Este artículo ya no está disponible', 'info')
        return volver
    if current_user.id == pub.vendedor_id or current_user.rol == 'admin':
        flash('No puedes mostrar interés en esta publicación', 'warning')
        return volver

    mensaje = request.form.get('mensaje', '').strip()[:1000] or None
    try:
        oferta = _decimal(request.form.get('oferta'), minimo=Decimal('1'))
    except ValueError:
        flash('La cantidad que ofreces debe ser un número mayor que 0', 'danger')
        return volver

    existente = Interes.query.filter_by(publicacion_id=pub.id, comprador_id=current_user.id).first()
    if existente:
        existente.mensaje = mensaje or existente.mensaje
        existente.oferta_comprador = oferta or existente.oferta_comprador
        if existente.estado == 'descartado':
            existente.estado = 'nuevo'
        registro = existente
    else:
        registro = Interes(publicacion_id=pub.id, comprador_id=current_user.id,
                           mensaje=mensaje, oferta_comprador=oferta)
        db.session.add(registro)
    db.session.commit()
    en_segundo_plano(tarea_nuevo_interes, registro.id)

    if pub.mostrar_precio:
        flash('✅ ¡Listo! Un asesor de BuscatodoRD te contactará para coordinar la compra.', 'success')
    else:
        flash('✅ Recibimos tu consulta. Un asesor de BuscatodoRD te contactará con el precio.', 'success')
    return volver


@ventas_bp.route('/catalogo/mis-consultas')
@login_required
def mis_consultas():
    intereses = current_user.intereses.order_by(Interes.created_at.desc()).all()
    return render_template('ventas/mis_consultas.html', intereses=intereses)


# ═════════════════════════════ VENDEDOR ═══════════════════════════════════════

@ventas_bp.route('/vender/nueva', methods=['GET', 'POST'])
@login_required
def nueva():
    if current_user.rol == 'admin':
        flash('El administrador no publica artículos a la venta', 'warning')
        return redirect(url_for('admin.publicaciones'))

    if request.method == 'POST':
        datos, errores = _validar_formulario(request.form)
        archivos = [f for f in request.files.getlist('fotos') if f and f.filename]
        if not archivos:
            errores.append('Sube al menos una foto del artículo')
        if errores:
            for e in errores:
                flash(e, 'danger')
            return render_template('ventas/form.html', form=request.form, pub=None, **_contexto_form()), 400

        pub = Publicacion(vendedor_id=current_user.id, estado='pendiente', **datos)
        db.session.add(pub)
        db.session.flush()
        pub.generar_codigo()
        subidas, rechazadas = _subir_fotos(pub, archivos)
        if not subidas:
            db.session.rollback()
            flash('Ninguna foto es una imagen válida (JPG, PNG, WEBP o GIF)', 'danger')
            return render_template('ventas/form.html', form=request.form, pub=None, **_contexto_form()), 400
        db.session.commit()
        en_segundo_plano(tarea_nueva_publicacion, pub.id)

        flash(f'✅ Recibimos tu publicación {pub.codigo}. La revisaremos y te contactaremos para acordar el precio.',
              'success')
        if rechazadas:
            flash(f'{rechazadas} archivo(s) no se subieron porque no son imágenes válidas.', 'warning')
        return redirect(url_for('ventas.mis_publicaciones'))

    return render_template('ventas/form.html', form={}, pub=None, **_contexto_form())


@ventas_bp.route('/vender/mis-publicaciones')
@login_required
def mis_publicaciones():
    pubs = current_user.publicaciones.order_by(Publicacion.created_at.desc()).all()
    return render_template('ventas/mis_publicaciones.html', publicaciones=pubs)


def _mi_publicacion(pid):
    pub = db.get_or_404(Publicacion, pid)
    if pub.vendedor_id != current_user.id:
        abort(404)
    return pub


@ventas_bp.route('/vender/<int:pid>/editar', methods=['GET', 'POST'])
@login_required
def editar(pid):
    pub = _mi_publicacion(pid)
    if not pub.editable_por_vendedor:
        flash('Esta publicación ya está aprobada. Para cambiarla escríbenos por WhatsApp.', 'info')
        return redirect(url_for('ventas.mis_publicaciones'))

    if request.method == 'POST':
        datos, errores = _validar_formulario(request.form)
        borrar = set(request.form.getlist('borrar_foto', type=int))
        quedan = [f for f in pub.fotos if f.id not in borrar]
        archivos = [f for f in request.files.getlist('fotos') if f and f.filename]
        if not quedan and not archivos:
            errores.append('La publicación debe tener al menos una foto')
        if errores:
            for e in errores:
                flash(e, 'danger')
            return render_template('ventas/form.html', form=request.form, pub=pub, **_contexto_form()), 400

        for foto in [f for f in pub.fotos if f.id in borrar]:
            eliminar_imagen(foto.public_id)
            db.session.delete(foto)
        for k, v in datos.items():
            setattr(pub, k, v)
        db.session.flush()
        for i, foto in enumerate(quedan):
            foto.orden, foto.es_principal = i, (i == 0)
        _, rechazadas = _subir_fotos(pub, archivos, ya_hay=len(quedan))

        reenviada = pub.estado == 'rechazada'
        pub.estado, pub.motivo_rechazo = 'pendiente', None
        db.session.commit()
        if reenviada:
            en_segundo_plano(tarea_nueva_publicacion, pub.id)
        flash('✅ Cambios guardados. Revisaremos tu publicación.' if reenviada else '✅ Cambios guardados.', 'success')
        if rechazadas:
            flash(f'{rechazadas} archivo(s) no se subieron porque no son imágenes válidas.', 'warning')
        return redirect(url_for('ventas.mis_publicaciones'))

    form = {'titulo': pub.titulo, 'descripcion': pub.descripcion, 'categoria_id': pub.categoria_id,
            'provincia_id': pub.provincia_id, 'condicion': pub.condicion, 'precio_pedido': pub.precio_pedido}
    return render_template('ventas/form.html', form=form, pub=pub, **_contexto_form())


@ventas_bp.route('/vender/<int:pid>/retirar', methods=['POST'])
@login_required
def retirar(pid):
    pub = _mi_publicacion(pid)
    if pub.estado in ('reservada', 'vendida'):
        flash('No se puede retirar: ya hay una venta en curso. Escríbenos por WhatsApp.', 'warning')
    elif pub.estado != 'retirada':
        pub.estado = 'retirada'
        db.session.commit()
        flash(f'Publicación {pub.codigo} retirada', 'info')
    return redirect(url_for('ventas.mis_publicaciones'))
