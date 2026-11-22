"""
Servicio de Push Notifications usando Firebase Cloud Messaging (FCM).
- Método moderno con Firebase Admin SDK (la API "legacy" con Server Key ya no existe)
- Gratis hasta 1M mensajes/mes
- Credenciales: Firebase Console → Project Settings → Service Accounts → Generate new private key
- Ver FIREBASE_SETUP.md
"""
import os
from flask import current_app
from services.notificaciones_log import log

# Importar Firebase como dependencia opcional
try:
    import firebase_admin
    from firebase_admin import credentials, messaging
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False
    firebase_admin = None
    credentials = None
    messaging = None


# App de Firebase inicializada (singleton) y ruta con la que se inicializó
_firebase_app = None
_firebase_cred_path = None

ICONO = '/static/icons/icon-192.png'
BADGE = '/static/icons/badge-96.png'


def _ruta_credenciales():
    ruta = current_app.config.get('FIREBASE_CREDENTIALS_PATH', '') or ''
    if ruta and not os.path.isabs(ruta):
        # Relativa a la raíz del proyecto, no al directorio desde el que se lanzó el proceso
        ruta = os.path.join(current_app.root_path, ruta)
    return ruta


def reiniciar_firebase():
    """Descarta la app de Firebase (p. ej. tras cambiar las credenciales en el panel)."""
    global _firebase_app, _firebase_cred_path
    if _firebase_app is not None and FIREBASE_AVAILABLE:
        try:
            firebase_admin.delete_app(_firebase_app)
        except Exception:
            pass
    _firebase_app = None
    _firebase_cred_path = None


def _inicializar_firebase():
    """Inicializa Firebase Admin SDK una sola vez por proceso."""
    global _firebase_app, _firebase_cred_path

    if not FIREBASE_AVAILABLE:
        current_app.logger.warning("Firebase Admin SDK no está instalado. Instala con: pip install firebase-admin")
        return False

    cred_path = _ruta_credenciales()
    if not cred_path:
        current_app.logger.debug("FIREBASE_CREDENTIALS_PATH no configurado; push desactivado")
        return False

    if _firebase_app is not None and _firebase_cred_path == cred_path:
        return True
    if _firebase_app is not None:
        reiniciar_firebase()

    try:
        cred = credentials.Certificate(cred_path)
        _firebase_app = firebase_admin.initialize_app(cred, name='buscapieza')
        _firebase_cred_path = cred_path
        current_app.logger.info("Firebase Admin SDK inicializado correctamente")
        return True
    except FileNotFoundError:
        current_app.logger.error(f"Archivo de credenciales Firebase no encontrado: {cred_path}")
    except ValueError as e:
        # Ya existe una app con ese nombre (p. ej. recarga en caliente): reutilizarla
        try:
            _firebase_app = firebase_admin.get_app('buscapieza')
            _firebase_cred_path = cred_path
            return True
        except ValueError:
            current_app.logger.error(f"Credenciales Firebase inválidas: {e}")
    except Exception as e:
        current_app.logger.error(f"Error crítico inicializando Firebase: {e}")
    return False


def _url_absoluta(url: str) -> str:
    if url.startswith('http'):
        return url
    return current_app.config.get('APP_URL', '').rstrip('/') + url


def _borrar_token(token: str):
    from models import db, PushToken
    try:
        PushToken.query.filter_by(token=token).delete()
        db.session.commit()
    except Exception:
        db.session.rollback()


def enviar_push(token: str, titulo: str, cuerpo: str, url: str = '/') -> bool:
    """
    Envía push a un token FCM específico.
    Los tokens caducados se eliminan de la BD automáticamente.
    """
    if not _inicializar_firebase():
        return False

    link = _url_absoluta(url)
    # FCM solo acepta enlaces HTTPS absolutos en fcm_options
    fcm_options = messaging.WebpushFCMOptions(link=link) if link.startswith('https://') else None

    try:
        message = messaging.Message(
            notification=messaging.Notification(title=titulo, body=cuerpo),
            data={'url': url, 'title': titulo, 'body': cuerpo},
            webpush=messaging.WebpushConfig(
                notification=messaging.WebpushNotification(
                    title=titulo, body=cuerpo, icon=ICONO, badge=BADGE,
                ),
                fcm_options=fcm_options,
            ),
            token=token,
        )
        response = messaging.send(message, app=_firebase_app)
        current_app.logger.info(f"Push enviado: {response}")
        log('push', token, f"{titulo} — {cuerpo}", True)
        return True

    except messaging.UnregisteredError:
        current_app.logger.info(f"Token FCM caducado, eliminado: {token[:20]}...")
        _borrar_token(token)
        log('push', token, f"{titulo} — {cuerpo}", False, 'Token caducado (eliminado)')
    except Exception as e:
        current_app.logger.error(f"Error enviando push: {e}")
        log('push', token, f"{titulo} — {cuerpo}", False, str(e))
    return False


def enviar_push_a_todos_proveedores(titulo: str, cuerpo: str, url: str = '/') -> int:
    """Envía push a todos los proveedores activos y verificados con token registrado."""
    from models import PushToken, Usuario

    if not _inicializar_firebase():
        return 0

    tokens = (
        PushToken.query
        .join(Usuario, PushToken.usuario_id == Usuario.id)
        .filter(Usuario.rol == 'proveedor', Usuario.activo == True, Usuario.verificado == True)  # noqa: E712
        .all()
    )
    valores = [pt.token for pt in tokens]

    exitosos = sum(1 for t in valores if enviar_push(t, titulo, cuerpo, url))
    current_app.logger.info(f"Push masivo: {exitosos}/{len(valores)} dispositivos de proveedores")
    return exitosos


def enviar_push_broker(titulo: str, cuerpo: str, url: str = '/admin/dashboard') -> bool:
    """Envía push a todos los dispositivos de todos los admins activos."""
    from models import PushToken, Usuario

    if not _inicializar_firebase():
        return False

    tokens = (
        PushToken.query
        .join(Usuario, PushToken.usuario_id == Usuario.id)
        .filter(Usuario.rol == 'admin', Usuario.activo == True)  # noqa: E712
        .all()
    )
    if not tokens:
        current_app.logger.info("Ningún admin tiene tokens FCM registrados")
        return False

    valores = [pt.token for pt in tokens]
    resultados = [enviar_push(t, titulo, cuerpo, url) for t in valores]
    return any(resultados)


def notificar_nueva_solicitud(sol) -> dict:
    """Push al broker y a los proveedores por una nueva solicitud."""
    broker_ok = enviar_push_broker(
        titulo=f"🔔 Nueva solicitud: {sol.codigo}",
        cuerpo=sol.titulo,
        url=f"/admin/solicitud/{sol.id}"
    )

    categoria_nombre = sol.categoria.nombre if sol.categoria else 'General'
    urgencia_texto = sol.urgencia.replace('_', ' ').title() if sol.urgencia else 'Normal'

    provs_ok = enviar_push_a_todos_proveedores(
        titulo=f"🔍 Nueva búsqueda: {sol.titulo[:50]}",
        cuerpo=f"{categoria_nombre} · {urgencia_texto}",
        url=f"/ofertas/hacer/{sol.id}"
    )

    return {"broker": broker_ok, "proveedores": provs_ok}


def notificar_nueva_oferta(oferta, sol) -> bool:
    """Push al broker cuando llega oferta de un proveedor."""
    prov = oferta.proveedor
    empresa = prov.empresa or prov.nombre

    return enviar_push_broker(
        titulo=f"💼 Oferta de {empresa}",
        cuerpo=f"{sol.titulo} · RD${oferta.precio:,.0f}",
        url=f"/admin/solicitud/{sol.id}"
    )
