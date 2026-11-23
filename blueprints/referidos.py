"""Programa de referidos: página "Mi red" de cada usuario."""
from flask import Blueprint, render_template, current_app, url_for, request, Response
from flask_login import login_required, current_user

from extensions import db
from models import ComisionReferido
from services import referidos as svc
from services import promo

referidos_bp = Blueprint('referidos', __name__)


@referidos_bp.route('/referidos')
@login_required
def mi_red():
    cfg = svc.config()
    nuevo = not current_user.codigo_referido
    codigo = svc.asegurar_codigo(current_user)
    if nuevo:
        db.session.commit()
    enlace = promo.enlace(current_user)
    periodo = svc.periodo_de(None)
    niveles = svc.red_por_niveles(current_user, max(len(cfg['niveles']), 1))
    comisiones = (current_user.comisiones_referido.order_by(ComisionReferido.created_at.desc()).limit(50).all())
    return render_template('referidos/mi_red.html', cfg=cfg, codigo=codigo, enlace=enlace,
                           niveles=niveles, saldo=svc.saldo(current_user.id), comisiones=comisiones,
                           compras_mes=svc.compras_personales(current_user.id, periodo), periodo=periodo,
                           patrocinador=svc.nombre_privado(current_user.patrocinador) if current_user.patrocinador else None,
                           nombre_privado=svc.nombre_privado)


@referidos_bp.route('/referidos/qr.png')
@login_required
def qr():
    """QR con el enlace de invitación del usuario. ?p= identifica el material (qr, i3...); ?descargar=1 lo baja."""
    ref = promo.ref_valida(request.args.get('p')) or 'qr'
    png = promo.qr_png(promo.enlace(current_user, ref))
    db.session.commit()   # por si se acaba de generar el código
    resp = Response(png, mimetype='image/png')
    resp.headers['Cache-Control'] = 'private, max-age=3600'
    if request.args.get('descargar'):
        resp.headers['Content-Disposition'] = f'attachment; filename="buscatodo-qr-{current_user.codigo_referido}.png"'
    return resp


@referidos_bp.route('/referidos/kit')
@login_required
def kit():
    codigo = svc.asegurar_codigo(current_user)
    db.session.commit()
    frases = {}
    for f in promo.activas('frase'):
        frases.setdefault(f.categoria, []).append(
            {'id': f.id, 'ref': f.ref, 'texto': promo.personalizar(f.texto, current_user, f.ref)})
    imagenes = [{
        'id': i.id, 'ref': i.ref, 'titulo': i.titulo or '', 'subtitulo': i.subtitulo or '', 'emoji': i.emoji or '',
        'color_ini': i.color_ini or '#0B5CAD', 'color_fin': i.color_fin or '#001838', 'imagen_url': i.imagen_url or '',
        'con_qr': bool(i.con_qr), 'texto': promo.personalizar(i.texto or '{link}', current_user, i.ref),
        'qr': url_for('referidos.qr', p=i.ref),
    } for i in promo.activas('imagen')]
    return render_template('referidos/kit.html', codigo=codigo, frases=frases, imagenes=imagenes,
                           categorias=promo.CATEGORIAS, enlace=promo.enlace(current_user, 'kit'))
