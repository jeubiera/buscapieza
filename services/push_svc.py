"""
Servicio de Push Notifications usando Firebase Cloud Messaging (FCM).
- Gratis hasta 1M mensajes/mes
- Requiere cuenta en https://firebase.google.com/
- Obtener Server Key en: Firebase Console → Project Settings → Cloud Messaging
"""
import json
import requests
from flask import current_app


def _server_key():
    return current_app.config.get('FIREBASE_SERVER_KEY', '')


def enviar_push(token: str, titulo: str, cuerpo: str, url: str = '/') -> bool:
    """
    Envía push a un token FCM específico.
    """
    key = _server_key()
    if not key:
        current_app.logger.warning("Firebase Server Key no configurado")
        return False

    payload = {
        "to": token,
        "notification": {
            "title": titulo,
            "body" : cuerpo,
            "icon" : "/static/icons/icon.svg",
            "click_action": url,
            "badge": "/static/icons/icon.svg"
        },
        "data": {
            "url": url
        },
        "webpush": {
            "fcm_options": {"link": url}
        }
    }

    try:
        r = requests.post(
            "https://fcm.googleapis.com/fcm/send",
            headers={
                "Authorization": f"key={key}",
                "Content-Type" : "application/json"
            },
            data=json.dumps(payload),
            timeout=8
        )
        r.raise_for_status()
        resp = r.json()
        if resp.get('failure', 0) > 0:
            current_app.logger.warning(f"FCM fallo: {resp}")
            return False
        return True
    except requests.RequestException as e:
        current_app.logger.error(f"Error FCM: {e}")
        return False


def enviar_push_a_todos_proveedores(titulo: str, cuerpo: str, url: str = '/') -> int:
    """
    Envía push a todos los proveedores activos con token registrado.
    Retorna cantidad de envíos exitosos.
    """
    from models import PushToken, Usuario

    tokens = (
        PushToken.query
        .join(Usuario, PushToken.usuario_id == Usuario.id)
        .filter(Usuario.rol == 'proveedor', Usuario.activo == True)
        .all()
    )

    exitosos = 0
    for pt in tokens:
        if enviar_push(pt.token, titulo, cuerpo, url):
            exitosos += 1

    return exitosos


def enviar_push_broker(titulo: str, cuerpo: str, url: str = '/admin/dashboard') -> bool:
    """
    Envía push al admin/broker.
    """
    from models import PushToken, Usuario

    admin = Usuario.query.filter_by(rol='admin', activo=True).first()
    if not admin:
        return False

    tokens = PushToken.query.filter_by(usuario_id=admin.id).all()
    ok = False
    for pt in tokens:
        if enviar_push(pt.token, titulo, cuerpo, url):
            ok = True
    return ok


def notificar_nueva_solicitud(sol) -> dict:
    """
    Dispara push para nueva solicitud:
    - Al broker (admin)
    - A todos los proveedores activos
    Retorna estadísticas del envío.
    """
    broker_ok   = enviar_push_broker(
        titulo = f"🔔 Nueva solicitud: {sol.codigo}",
        cuerpo = sol.titulo,
        url    = f"/admin/solicitud/{sol.id}"
    )

    provs_ok = enviar_push_a_todos_proveedores(
        titulo = f"🔍 Nueva búsqueda: {sol.titulo[:50]}",
        cuerpo = f"{sol.categoria.nombre if sol.categoria else 'General'} · {sol.urgencia.replace('_',' ').title()}",
        url    = f"/ofertas/hacer/{sol.id}"
    )

    return {"broker": broker_ok, "proveedores": provs_ok}


def notificar_nueva_oferta(oferta, sol) -> bool:
    """
    Push al broker cuando llega oferta de un proveedor.
    """
    prov = oferta.proveedor
    return enviar_push_broker(
        titulo = f"💼 Oferta de {prov.empresa or prov.nombre}",
        cuerpo = f"{sol.titulo} · RD${oferta.precio:,.0f}",
        url    = f"/admin/solicitud/{sol.id}"
    )
