from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app
from flask_login import login_required, current_user
from models import db, Oferta, Solicitud
from services.cloudinary_svc import subir_imagen
from services.whatsapp_svc import notificar_broker_nueva_oferta
from services.push_svc import notificar_nueva_oferta

oferta_bp = Blueprint('ofertas', __name__)

ALLOWED = {'png', 'jpg', 'jpeg', 'webp', 'gif'}

def _allowed(f):
    return '.' in f and f.rsplit('.', 1)[1].lower() in ALLOWED

@oferta_bp.route('/mis-ofertas')
@login_required
def mis_ofertas():
    if current_user.rol not in ('proveedor', 'admin'):
        flash('Acceso solo para proveedores', 'warning')
        return redirect(url_for('main.index'))

    solicitudes = Solicitud.query.filter_by(estado='pendiente')\
        .order_by(Solicitud.created_at.desc()).all()
    mis = Oferta.query.filter_by(proveedor_id=current_user.id)\
        .order_by(Oferta.created_at.desc()).all()

    return render_template('ofertas/panel_proveedor.html',
        solicitudes=solicitudes, mis_ofertas=mis)


@oferta_bp.route('/hacer/<int:sid>', methods=['GET', 'POST'])
@login_required
def hacer_oferta(sid):
    if current_user.rol not in ('proveedor', 'admin'):
        flash('Solo proveedores pueden ofertar', 'warning')
        return redirect(url_for('main.index'))

    sol = Solicitud.query.get_or_404(sid)

    existente = Oferta.query.filter_by(
        solicitud_id=sid, proveedor_id=current_user.id).first()
    if existente:
        flash('Ya enviaste una oferta para esta solicitud', 'info')
        return redirect(url_for('ofertas.mis_ofertas'))

    if request.method == 'POST':
        foto_url = None
        foto = request.files.get('foto')
        if foto and foto.filename and _allowed(foto.filename):
            try:
                foto_url, _ = subir_imagen(foto, carpeta='buscapieza/ofertas')
            except Exception as e:
                current_app.logger.error(f"Error foto oferta: {e}")

        oferta = Oferta(
            solicitud_id   = sid,
            proveedor_id   = current_user.id,
            precio         = request.form.get('precio'),
            descripcion    = request.form.get('descripcion', '').strip(),
            tiempo_entrega = request.form.get('tiempo_entrega', '').strip(),
            incluye_envio  = bool(request.form.get('incluye_envio')),
            foto_url       = foto_url,
            estado         = 'nueva'
        )
        db.session.add(oferta)
        db.session.commit()

        # ── Notificar al broker ─────────────────────────────────────────────
        try:
            notificar_broker_nueva_oferta(oferta, sol)  # WhatsApp
        except Exception as e:
            current_app.logger.error(f"WA oferta error: {e}")

        try:
            notificar_nueva_oferta(oferta, sol)          # Push
        except Exception as e:
            current_app.logger.error(f"Push oferta error: {e}")

        flash('✅ Oferta enviada al equipo de BuscaPieza', 'success')
        return redirect(url_for('ofertas.mis_ofertas'))

    return render_template('ofertas/hacer_oferta.html', sol=sol)
