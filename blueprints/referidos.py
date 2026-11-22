"""Programa de referidos: página "Mi red" de cada usuario."""
from flask import Blueprint, render_template, current_app, url_for
from flask_login import login_required, current_user

from extensions import db
from models import ComisionReferido
from services import referidos as svc

referidos_bp = Blueprint('referidos', __name__)


@referidos_bp.route('/referidos')
@login_required
def mi_red():
    cfg = svc.config()
    nuevo = not current_user.codigo_referido
    codigo = svc.asegurar_codigo(current_user)
    if nuevo:
        db.session.commit()
    base = current_app.config.get('APP_URL', '').rstrip('/')
    enlace = f"{base}{url_for('auth.registro')}?ref={codigo}"
    periodo = svc.periodo_de(None)
    niveles = svc.red_por_niveles(current_user, max(len(cfg['niveles']), 1))
    comisiones = (current_user.comisiones_referido.order_by(ComisionReferido.created_at.desc()).limit(50).all())
    return render_template('referidos/mi_red.html', cfg=cfg, codigo=codigo, enlace=enlace,
                           niveles=niveles, saldo=svc.saldo(current_user.id), comisiones=comisiones,
                           compras_mes=svc.compras_personales(current_user.id, periodo), periodo=periodo,
                           patrocinador=svc.nombre_privado(current_user.patrocinador) if current_user.patrocinador else None,
                           nombre_privado=svc.nombre_privado)
