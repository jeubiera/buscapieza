from decimal import Decimal, InvalidOperation

from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app
from flask_login import login_required, current_user
from models import db, Oferta, Solicitud
from services.archivos import es_imagen_valida
from services.cloudinary_svc import subir_imagen
from services.tareas import en_segundo_plano
from services.notificaciones import tarea_nueva_oferta

oferta_bp = Blueprint('ofertas', __name__)

TIEMPOS_ENTREGA = ['Inmediato', '1-2 días', '3-5 días', '1 semana', '2 semanas']


@oferta_bp.route('/mis-ofertas')
@login_required
def mis_ofertas():
    if current_user.rol not in ('proveedor', 'admin'):
        flash('Acceso solo para proveedores', 'warning')
        return redirect(url_for('main.index'))

    ya_ofertadas = db.session.query(Oferta.solicitud_id).filter(Oferta.proveedor_id == current_user.id)
    solicitudes = Solicitud.query.filter(Solicitud.estado.in_(['pendiente', 'en_gestion']))\
        .filter(~Solicitud.id.in_(ya_ofertadas))\
        .order_by(Solicitud.created_at.desc()).all()
    solicitudes = [s for s in solicitudes if s.acepta_ofertas]
    mis = Oferta.query.filter_by(proveedor_id=current_user.id)\
        .order_by(Oferta.created_at.desc()).all()

    return render_template('ofertas/panel_proveedor.html',
        solicitudes=solicitudes, mis_ofertas=mis)


@oferta_bp.route('/hacer/<int:sid>', methods=['GET', 'POST'])
@login_required
def hacer_oferta(sid):
    if current_user.rol != 'proveedor':
        flash('Solo proveedores pueden ofertar', 'warning')
        return redirect(url_for('main.index'))
    if not current_user.verificado:
        flash('Tu cuenta de proveedor aún no está verificada. El equipo de BuscaPieza te contactará.', 'warning')
        return redirect(url_for('ofertas.mis_ofertas'))

    sol = db.get_or_404(Solicitud, sid)
    if not sol.acepta_ofertas:
        flash('Esta solicitud ya no recibe ofertas', 'info')
        return redirect(url_for('ofertas.mis_ofertas'))

    existente = Oferta.query.filter_by(
        solicitud_id=sid, proveedor_id=current_user.id).first()
    if existente:
        flash('Ya enviaste una oferta para esta solicitud', 'info')
        return redirect(url_for('ofertas.mis_ofertas'))

    if request.method == 'POST':
        f = request.form
        errores = []
        try:
            precio = Decimal((f.get('precio') or '').replace(',', '').strip())
            if not (Decimal('1') <= precio < Decimal('10000000000')):
                raise InvalidOperation
            precio = precio.quantize(Decimal('0.01'))
        except InvalidOperation:
            precio = None
            errores.append('Indica un precio válido (mínimo RD$1)')
        tiempo = f.get('tiempo_entrega', '').strip()
        if tiempo not in TIEMPOS_ENTREGA:
            errores.append('Selecciona el tiempo de entrega')

        foto = request.files.get('foto')
        if foto and foto.filename and not es_imagen_valida(foto):
            errores.append('La foto debe ser una imagen JPG, PNG, WEBP o GIF')

        if errores:
            for e in errores:
                flash(e, 'danger')
            return render_template('ofertas/hacer_oferta.html', sol=sol,
                                   tiempos=TIEMPOS_ENTREGA, form=f), 400

        foto_url = None
        if foto and foto.filename:
            try:
                foto_url, _ = subir_imagen(foto, carpeta='buscapieza/ofertas')
            except Exception as e:
                current_app.logger.error(f"Error foto oferta: {e}")

        oferta = Oferta(
            solicitud_id   = sid,
            proveedor_id   = current_user.id,
            precio         = precio,
            descripcion    = f.get('descripcion', '').strip()[:2000],
            tiempo_entrega = tiempo,
            incluye_envio  = bool(f.get('incluye_envio')),
            foto_url       = foto_url,
            estado         = 'nueva'
        )
        db.session.add(oferta)
        db.session.commit()

        en_segundo_plano(tarea_nueva_oferta, oferta.id)

        flash('✅ Oferta enviada al equipo de BuscaPieza', 'success')
        return redirect(url_for('ofertas.mis_ofertas'))

    return render_template('ofertas/hacer_oferta.html', sol=sol, tiempos=TIEMPOS_ENTREGA, form={})
