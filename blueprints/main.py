from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from models import db, Solicitud, Categoria, PushToken

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    categorias = Categoria.query.filter_by(activa=True).all()
    total_solicitudes = Solicitud.query.count()
    recientes = Solicitud.query.filter_by(estado='pendiente').order_by(
        Solicitud.created_at.desc()).limit(6).all()
    return render_template('index.html',
        categorias=categorias,
        total_solicitudes=total_solicitudes,
        recientes=recientes)

@main_bp.route('/offline')
def offline():
    return render_template('offline.html')

@main_bp.route('/manifest.json')
def manifest():
    def icon(size, name=None, purpose=None):
        d = {
            "src": f"/static/icons/{name or f'icon-{size}.png'}",
            "sizes": f"{size}x{size}",
            "type": "image/png",
        }
        if purpose:
            d["purpose"] = purpose
        return d

    return jsonify({
        "id": "/",
        "name": "BuscaPieza RD",
        "short_name": "BuscaPieza",
        "description": "Publica lo que buscas y recibe ofertas de proveedores verificados en toda la República Dominicana.",
        "start_url": "/?source=pwa",
        "scope": "/",
        "display": "standalone",
        "display_override": ["window-controls-overlay", "standalone"],
        "orientation": "portrait-primary",
        "background_color": "#0A0E1A",
        "theme_color": "#FF6B35",
        "lang": "es-DO",
        "dir": "ltr",
        "categories": ["shopping", "business", "utilities"],
        "prefer_related_applications": False,
        "icons": [
            icon(48), icon(72), icon(96), icon(128), icon(144),
            icon(152), icon(192), icon(256), icon(384), icon(512),
            icon(192, "icon-maskable-192.png", "maskable"),
            icon(512, "icon-maskable-512.png", "maskable"),
        ],
        "shortcuts": [
            {
                "name": "Nueva búsqueda",
                "short_name": "Buscar",
                "description": "Publica una solicitud de pieza o repuesto",
                "url": "/solicitudes/nueva?source=shortcut",
                "icons": [icon(192, "shortcut-nueva-192.png")]
            },
            {
                "name": "Mis ofertas",
                "short_name": "Ofertas",
                "description": "Revisa las ofertas recibidas",
                "url": "/ofertas/mis-ofertas?source=shortcut",
                "icons": [icon(192, "shortcut-ofertas-192.png")]
            }
        ]
    })

@main_bp.route('/sw.js')
def service_worker():
    from flask import send_from_directory
    resp = send_from_directory('static/js', 'sw.js', mimetype='application/javascript')
    resp.headers['Cache-Control'] = 'no-cache'
    resp.headers['Service-Worker-Allowed'] = '/'
    return resp


@main_bp.route('/push-token', methods=['POST'])
@login_required
def guardar_push_token():
    """Recibe el token FCM del navegador y lo asocia al usuario actual."""
    data  = request.get_json(silent=True) or {}
    token = str(data.get('token', '')).strip()
    if not token or len(token) > 4096:
        return jsonify({'ok': False, 'msg': 'Token inválido'}), 400

    existente = PushToken.query.filter_by(token=token).first()
    if existente:
        # El mismo navegador puede cambiar de usuario: el token pertenece al último
        existente.usuario_id = current_user.id
    else:
        db.session.add(PushToken(usuario_id=current_user.id, token=token))
    db.session.commit()
    return jsonify({'ok': True})


@main_bp.route('/salud')
def salud():
    """Comprobación de estado (la usan el instalador y monitores externos)."""
    from sqlalchemy import text
    try:
        db.session.execute(text('SELECT 1'))
        return jsonify({'ok': True, 'db': True})
    except Exception:
        db.session.rollback()
        return jsonify({'ok': False, 'db': False}), 503
