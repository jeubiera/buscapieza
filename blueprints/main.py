from flask import Blueprint, render_template
from models import Solicitud, Categoria

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
    from flask import jsonify

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
    return send_from_directory('static/js', 'sw.js',
        mimetype='application/javascript')
