"""Envíos del lado del comprador (elegir entrega, confirmar, reclamar) y del vendedor (despachar)."""
from flask import Blueprint, render_template, redirect, url_for, request, flash, abort, current_app
from flask_login import login_required, current_user

from extensions import db
from models import Envio, TarifaEnvio, Transaccion, Provincia
from services import envios as svc
from services.archivos import es_imagen_valida
from services.cloudinary_svc import subir_imagen
from services.tareas import en_segundo_plano
from services.notificaciones import tarea_envio

envios_bp = Blueprint('envios', __name__)


def _mi_envio(eid):
    env = db.get_or_404(Envio, eid)
    t = env.transaccion
    if current_user.id not in (t.cliente_id, t.proveedor_id) and current_user.rol != 'admin':
        abort(404)
    return env


@envios_bp.route('/compra/<int:tid>/entrega', methods=['GET', 'POST'])
@login_required
def elegir(tid):
    trans = db.get_or_404(Transaccion, tid)
    if trans.cliente_id != current_user.id:
        abort(404)
    if trans.estado_pago != 'pendiente':
        flash('Esta compra ya no está pendiente de pago', 'info')
        return redirect(url_for('envios.mis_envios'))
    if request.method == 'POST':
        tarifa = db.session.get(TarifaEnvio, request.form.get('tarifa_id', type=int) or 0)
        try:
            env = svc.elegir(trans, current_user, tarifa, request.form)
            db.session.commit()
        except svc.ErrorEnvio as e:
            db.session.rollback()
            flash(str(e), 'danger')
            return redirect(url_for('envios.elegir', tid=tid))
        if env.estado == 'por_cotizar':
            en_segundo_plano(tarea_envio, env.id, 'por_cotizar')
            flash('🚚 Recibimos tus datos. Te avisaremos por WhatsApp con el costo del flete para que puedas pagar.', 'info')
            return redirect(url_for('envios.ver', eid=env.id))
        return redirect(url_for('pagos.pagar_venta', tid=tid))
    actual = trans.envio
    datos = {'destinatario': current_user.nombre, 'telefono': current_user.whatsapp or current_user.telefono,
             'provincia_id': current_user.provincia_id}
    if actual:
        datos = {'destinatario': actual.destinatario, 'telefono': actual.telefono, 'provincia_id': actual.provincia_id,
                 'direccion': actual.direccion, 'indicaciones': actual.indicaciones, 'tarifa_id': actual.tarifa_id}
    return render_template('envios/elegir.html', trans=trans, tarifas=svc.tarifas_activas(), datos=datos,
                           provincias=Provincia.query.order_by(Provincia.nombre).all(), nombres=svc.NOMBRES_METODO)


@envios_bp.route('/mis-envios')
@login_required
def mis_envios():
    svc.confirmar_vencidos()
    compras = (Envio.query.join(Transaccion).filter(Transaccion.cliente_id == current_user.id)
               .order_by(Envio.created_at.desc()).all())
    ventas = (Envio.query.join(Transaccion).filter(Transaccion.proveedor_id == current_user.id,
                                                   Envio.estado.notin_(('por_cotizar', 'pendiente_pago')))
              .order_by(Envio.created_at.desc()).all())
    return render_template('envios/mis_envios.html', compras=compras, ventas=ventas, estados=svc.NOMBRES_ESTADO)


@envios_bp.route('/<int:eid>')
@login_required
def ver(eid):
    svc.confirmar_vencidos()
    env = _mi_envio(eid)
    t = env.transaccion
    es_vendedor = current_user.id == t.proveedor_id
    if es_vendedor and env.estado in ('por_cotizar', 'pendiente_pago') and current_user.id != t.cliente_id:
        abort(404)   # el vendedor no ve nada hasta que la compra esté pagada
    return render_template('envios/ver.html', env=env, t=t, es_vendedor=es_vendedor,
                           es_comprador=current_user.id == t.cliente_id, estados=svc.NOMBRES_ESTADO,
                           nombres=svc.NOMBRES_METODO, limite=svc.limite_confirmacion(env),
                           horas=svc.horas_confirmacion(),
                           telefono_guia=current_app.config.get('BROKER_WHATSAPP', ''))


@envios_bp.route('/<int:eid>/despachar', methods=['POST'])
@login_required
def despachar(eid):
    env = _mi_envio(eid)
    if current_user.id != env.transaccion.proveedor_id:
        abort(404)
    foto = request.files.get('foto')
    datos_foto = None
    try:
        if foto and foto.filename:
            if not es_imagen_valida(foto):
                raise svc.ErrorEnvio('La foto debe ser una imagen JPG, PNG o WEBP')
            datos_foto = subir_imagen(foto, carpeta='buscatodo/envios')
        primera = svc.despachar(env, False, request.form.get('empresa'), request.form.get('guia'), datos_foto,
                                request.form.get('nota'))
        db.session.commit()
    except svc.ErrorEnvio as e:
        db.session.rollback()
        flash(str(e), 'danger')
        return redirect(url_for('envios.ver', eid=eid))
    if primera:
        en_segundo_plano(tarea_envio, env.id, 'despachado')
    flash('✅ Despacho registrado. Le avisamos al comprador.', 'success')
    return redirect(url_for('envios.ver', eid=eid))


@envios_bp.route('/<int:eid>/recibido', methods=['POST'])
@login_required
def recibido(eid):
    env = _mi_envio(eid)
    if current_user.id != env.transaccion.cliente_id:
        abort(404)
    try:
        nuevo = svc.confirmar_recepcion(env, 'comprador')
        db.session.commit()
    except svc.ErrorEnvio as e:
        db.session.rollback()
        flash(str(e), 'warning')
        return redirect(url_for('envios.ver', eid=eid))
    if nuevo:
        en_segundo_plano(tarea_envio, env.id, 'entregado')
    flash('🎉 ¡Gracias por confirmar! Disfruta tu compra.', 'success')
    return redirect(url_for('envios.ver', eid=eid))


@envios_bp.route('/<int:eid>/reclamar', methods=['POST'])
@login_required
def reclamar(eid):
    env = _mi_envio(eid)
    if current_user.id != env.transaccion.cliente_id:
        abort(404)
    try:
        svc.reclamar(env, request.form.get('reclamo'))
        db.session.commit()
    except svc.ErrorEnvio as e:
        db.session.rollback()
        flash(str(e), 'warning')
        return redirect(url_for('envios.ver', eid=eid))
    en_segundo_plano(tarea_envio, env.id, 'reclamado')
    flash('Recibimos tu reporte. Retenemos el pago al vendedor hasta resolverlo y te contactaremos.', 'info')
    return redirect(url_for('envios.ver', eid=eid))
