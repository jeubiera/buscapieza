"""
Pagos en línea: el comprador paga una venta y el vendedor paga destacados.

Seguridad de las vueltas de las pasarelas:
- Azul vuelve con los datos en la URL firmados (AuthHash): solo se acepta si la firma cuadra.
- CardNet vuelve sin datos fiables: el resultado se consulta de servidor a servidor.
- Ninguna vuelta depende de que haya sesión iniciada (los navegadores pueden no enviar la cookie).
"""
from decimal import Decimal, InvalidOperation

from flask import (Blueprint, render_template, redirect, url_for, request, flash, abort, current_app)
from flask_login import login_required, current_user

from extensions import db, csrf
from models import Pago, Transaccion, Publicacion, PlanDestacado
from services import pagos as svc
from services.archivos import es_comprobante_valido
from services.cloudinary_svc import subir_imagen
from services.pasarelas import ErrorPasarela, azul, cardnet
from services.tareas import en_segundo_plano
from services.notificaciones import tarea_pago

pagos_bp = Blueprint('pagos', __name__)


def _url_externa(endpoint, **kw):
    """URL absoluta con APP_URL (las pasarelas exigen URLs completas)."""
    return current_app.config.get('APP_URL', '').rstrip('/') + url_for(endpoint, **kw)


def _mi_pago(ref):
    pago = Pago.query.filter_by(referencia=ref).first_or_404()
    if pago.usuario_id != current_user.id and current_user.rol != 'admin':
        abort(404)
    return pago


def _volver_a(pago):
    return redirect(url_for('pagos.detalle', ref=pago.referencia))


# ── Elegir forma de pago ──────────────────────────────────────────────────────

@pagos_bp.route('/venta/<int:tid>')
@login_required
def pagar_venta(tid):
    trans = db.get_or_404(Transaccion, tid)
    if trans.cliente_id != current_user.id:
        abort(404)
    if trans.estado_pago != 'pendiente':
        flash('Esta compra ya no está pendiente de pago', 'info')
        return redirect(url_for('pagos.mis_pagos'))
    en_revision = trans.pagos.filter(Pago.estado == 'en_revision').first()
    return render_template('pagos/elegir.html', concepto='venta', objeto=trans, montos=svc.montos_venta(trans),
                           metodos=svc.metodos_disponibles(), en_revision=en_revision,
                           titulo=f'{trans.codigo_origen} · {trans.titulo_origen}')


@pagos_bp.route('/destacar/<int:pid>')
@login_required
def destacar(pid):
    pub = db.get_or_404(Publicacion, pid)
    if pub.vendedor_id != current_user.id:
        abort(404)
    if pub.estado != 'publicada':
        flash('Solo se pueden destacar artículos publicados', 'warning')
        return redirect(url_for('ventas.mis_publicaciones'))
    planes = PlanDestacado.query.filter_by(activo=True).order_by(PlanDestacado.orden, PlanDestacado.dias).all()
    if not planes:
        flash('Los destacados no están disponibles en este momento', 'info')
        return redirect(url_for('ventas.mis_publicaciones'))
    return render_template('pagos/elegir.html', concepto='destacado', objeto=pub, planes=planes,
                           montos={p.id: svc.montos_destacado(p.precio) for p in planes},
                           metodos=svc.metodos_disponibles(), en_revision=None,
                           titulo=f'{pub.codigo} · {pub.titulo}')


@pagos_bp.route('/iniciar', methods=['POST'])
@login_required
def iniciar():
    concepto = request.form.get('concepto')
    metodo = request.form.get('metodo')
    obj_id = request.form.get('id', type=int)
    try:
        if concepto == 'venta':
            trans = db.get_or_404(Transaccion, obj_id)
            volver = url_for('pagos.pagar_venta', tid=obj_id)
            pago = svc.crear_pago_venta(trans, current_user, metodo)
        elif concepto == 'destacado':
            pub = db.get_or_404(Publicacion, obj_id)
            volver = url_for('pagos.destacar', pid=obj_id)
            plan = db.session.get(PlanDestacado, request.form.get('plan_id', type=int) or 0)
            pago = svc.crear_pago_destacado(pub, plan, current_user, metodo)
        else:
            abort(400)
        db.session.commit()
    except svc.ErrorPago as e:
        db.session.rollback()
        flash(str(e), 'warning')
        return redirect(volver)

    if metodo == 'transferencia':
        flash(f'Pago {pago.referencia} creado. Transfiere y sube el comprobante aquí.', 'info')
        return _volver_a(pago)
    return _redirigir_a_pasarela(pago)


def _redirigir_a_pasarela(pago):
    """Página que envía automáticamente el navegador a Azul o CardNet."""
    try:
        if pago.metodo == 'azul':
            campos = azul.campos_formulario(
                pago,
                url_aprobado=_url_externa('pagos.azul_vuelta', resultado='aprobado'),
                url_declinado=_url_externa('pagos.azul_vuelta', resultado='declinado'),
                url_cancelado=_url_externa('pagos.azul_cancelado', ref=pago.referencia))
            return render_template('pagos/redirigir.html', accion=azul.url_pago(), campos=campos, pasarela='Azul')
        if pago.metodo == 'cardnet':
            sesion, clave = cardnet.crear_sesion(
                pago,
                url_retorno=_url_externa('pagos.cardnet_vuelta', ref=pago.referencia),
                url_cancelar=_url_externa('pagos.cardnet_cancelado', ref=pago.referencia))
            pago.pasarela_ref, pago.pasarela_clave = sesion, clave
            db.session.commit()
            return render_template('pagos/redirigir.html', accion=cardnet.url_autorizar(),
                                   campos={'SESSION': sesion}, pasarela='CardNet')
    except ErrorPasarela as e:
        current_app.logger.error(f'Pasarela {pago.metodo} ({pago.referencia}): {e}')
        svc.cancelar(pago)
        db.session.commit()
        flash(f'{e}. Inténtalo de nuevo o usa otra forma de pago.', 'danger')
        return redirect(request.referrer or url_for('pagos.mis_pagos'))
    abort(400)


# ── Detalle, comprobante, recibo ──────────────────────────────────────────────

@pagos_bp.route('/mis-pagos')
@login_required
def mis_pagos():
    lista = current_user.pagos.filter(Pago.estado != 'cancelado').order_by(Pago.created_at.desc()).all()
    pendientes = Transaccion.query.filter_by(cliente_id=current_user.id, estado_pago='pendiente').all()
    return render_template('pagos/mis_pagos.html', pagos=lista, ventas_pendientes=pendientes)


@pagos_bp.route('/<ref>')
@login_required
def detalle(ref):
    pago = _mi_pago(ref)
    return render_template('pagos/detalle.html', pago=pago,
                           instrucciones=current_app.config.get('TRANSFERENCIA_INSTRUCCIONES', ''))


@pagos_bp.route('/<ref>/comprobante', methods=['POST'])
@login_required
def subir_comprobante(ref):
    pago = _mi_pago(ref)
    if pago.usuario_id != current_user.id:
        abort(404)
    archivo = request.files.get('comprobante')
    if not archivo or not archivo.filename or not es_comprobante_valido(archivo):
        flash('Sube una foto o PDF del comprobante (JPG, PNG, WEBP o PDF)', 'danger')
        return _volver_a(pago)
    try:
        url, pid = subir_imagen(archivo, carpeta='buscatodo/comprobantes')
        svc.registrar_comprobante(pago, url, pid)
        db.session.commit()
    except svc.ErrorPago as e:
        db.session.rollback()
        flash(str(e), 'warning')
        return _volver_a(pago)
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Comprobante {pago.referencia}: {e}')
        flash('No se pudo subir el comprobante. Inténtalo de nuevo.', 'danger')
        return _volver_a(pago)
    en_segundo_plano(tarea_pago, pago.id, 'comprobante')
    flash('✅ Recibimos tu comprobante. Te avisaremos cuando lo confirmemos.', 'success')
    return _volver_a(pago)


@pagos_bp.route('/<ref>/cancelar', methods=['POST'])
@login_required
def cancelar(ref):
    pago = _mi_pago(ref)
    if pago.usuario_id == current_user.id and pago.estado == 'pendiente':
        svc.cancelar(pago)
        db.session.commit()
        flash('Pago cancelado', 'info')
    return redirect(url_for('pagos.mis_pagos'))


@pagos_bp.route('/<ref>/recibo')
@login_required
def recibo(ref):
    pago = _mi_pago(ref)
    if pago.estado != 'aprobado':
        flash('El recibo está disponible cuando el pago se confirma', 'info')
        return _volver_a(pago)
    return render_template('pagos/recibo.html', pago=pago)


# ── Vuelta de Azul ────────────────────────────────────────────────────────────

def _monto_desde_centavos(valor):
    try:
        return (Decimal(str(valor).strip()) / 100) if valor not in (None, '') else None
    except InvalidOperation:
        return None


@pagos_bp.route('/azul/<resultado>')
@csrf.exempt
def azul_vuelta(resultado):
    params = request.args.to_dict()
    pago = db.session.get(Pago, request.args.get('OrderNumber', type=int) or 0)
    if not pago or pago.metodo != 'azul' or resultado not in ('aprobado', 'declinado'):
        abort(404)
    if not azul.verificar_respuesta(params):
        current_app.logger.warning(f'Azul: firma inválida en la vuelta del pago {pago.referencia}')
        flash('No pudimos verificar la respuesta del banco. Si se te cobró, escríbenos con tu referencia.', 'danger')
        return _resultado(pago)

    respuesta = _respuesta_azul_segura(params)
    try:
        if resultado == 'aprobado' and azul.aprobada(params):
            if svc.aprobar(pago, autorizacion=params.get('AuthorizationCode'), respuesta=respuesta,
                           monto_confirmado=_monto_desde_centavos(params.get('Amount'))):
                pago.pasarela_ref = params.get('AzulOrderId') or pago.pasarela_ref
                db.session.commit()
                en_segundo_plano(tarea_pago, pago.id, 'aprobado_pasarela')
        elif pago.estado in ('pendiente',):
            svc.rechazar(pago, params.get('ResponseMessage') or params.get('ErrorDescription') or 'Declinada',
                         respuesta=respuesta)
            db.session.commit()
    except svc.ErrorPago as e:
        db.session.rollback()
        current_app.logger.error(f'Azul {pago.referencia}: {e}')
        flash(f'Hubo un problema al registrar el pago: {e}. Escríbenos con tu referencia.', 'danger')
    return _resultado(pago)


def _respuesta_azul_segura(params):
    import json
    campos = ('OrderNumber', 'Amount', 'ITBIS', 'AuthorizationCode', 'DateTime', 'ResponseCode', 'IsoCode',
              'ResponseMessage', 'ErrorDescription', 'RRN', 'AzulOrderId')
    return json.dumps({k: params.get(k) for k in campos if k in params}, ensure_ascii=False)


@pagos_bp.route('/azul/cancelado/<ref>')
def azul_cancelado(ref):
    pago = Pago.query.filter_by(referencia=ref, metodo='azul').first_or_404()
    if pago.estado == 'pendiente':
        svc.cancelar(pago)
        db.session.commit()
    flash('Cancelaste el pago. Puedes intentarlo de nuevo cuando quieras.', 'info')
    return _resultado(pago)


# ── Vuelta de CardNet ─────────────────────────────────────────────────────────

@pagos_bp.route('/cardnet/vuelta/<ref>', methods=['GET', 'POST'])
@csrf.exempt
def cardnet_vuelta(ref):
    pago = Pago.query.filter_by(referencia=ref, metodo='cardnet').first_or_404()
    if pago.estado == 'pendiente' and pago.pasarela_ref and pago.pasarela_clave:
        try:
            resultado = cardnet.consultar(pago.pasarela_ref, pago.pasarela_clave)
            respuesta = cardnet.resumen_seguro(resultado)
            if cardnet.aprobada(resultado):
                monto = resultado.get('Amount')
                monto = _monto_desde_centavos(monto) if monto and str(monto).isdigit() else None
                if svc.aprobar(pago, autorizacion=resultado.get('AuthorizationCode'), respuesta=respuesta,
                               monto_confirmado=monto):
                    db.session.commit()
                    en_segundo_plano(tarea_pago, pago.id, 'aprobado_pasarela')
            else:
                svc.rechazar(pago, resultado.get('ResponseMessage') or f"Código {resultado.get('ResponseCode', '?')}",
                             respuesta=respuesta)
                db.session.commit()
        except ErrorPasarela as e:
            current_app.logger.error(f'CardNet {pago.referencia}: {e}')
            flash('No pudimos confirmar el resultado con el banco todavía. Revisa en unos minutos.', 'warning')
        except svc.ErrorPago as e:
            db.session.rollback()
            current_app.logger.error(f'CardNet {pago.referencia}: {e}')
            flash(f'Hubo un problema al registrar el pago: {e}. Escríbenos con tu referencia.', 'danger')
    return _resultado(pago)


@pagos_bp.route('/cardnet/cancelado/<ref>', methods=['GET', 'POST'])
@csrf.exempt
def cardnet_cancelado(ref):
    pago = Pago.query.filter_by(referencia=ref, metodo='cardnet').first_or_404()
    if pago.estado == 'pendiente':
        svc.cancelar(pago)
        db.session.commit()
    flash('Cancelaste el pago. Puedes intentarlo de nuevo cuando quieras.', 'info')
    return _resultado(pago)


def _resultado(pago):
    """Tras volver de la pasarela: al detalle si hay sesión; si no, una página pública sin datos."""
    if current_user.is_authenticated and (current_user.id == pago.usuario_id or current_user.rol == 'admin'):
        if pago.estado == 'aprobado':
            flash(f'✅ ¡Pago confirmado! Referencia {pago.referencia}', 'success')
        elif pago.estado == 'rechazado':
            flash(f'El pago no fue aprobado: {pago.motivo_rechazo}', 'danger')
        return _volver_a(pago)
    return render_template('pagos/resultado_publico.html', pago=pago)
