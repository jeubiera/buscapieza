"""
Configuración dinámica guardada en la BD (tabla `configuracion`).

- Las claves de integraciones editables desde /admin/configuracion tienen prioridad
  sobre el .env cuando tienen valor.
- Los secretos se guardan cifrados (Fernet) con una clave derivada de SECRET_KEY.
  Si cambias SECRET_KEY, los secretos guardados dejarán de poder leerse y habrá que
  volver a introducirlos en el panel.
"""
import base64
import hashlib
from decimal import Decimal, InvalidOperation

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app

# Claves que el admin puede editar desde el panel
CLAVES_INTEGRACION = [
    'GREEN_API_INSTANCE', 'GREEN_API_TOKEN',
    'BROKER_WHATSAPP', 'BROKER_NOMBRE', 'APP_URL',
    'CLOUDINARY_CLOUD_NAME', 'CLOUDINARY_API_KEY', 'CLOUDINARY_API_SECRET',
    'FIREBASE_CREDENTIALS_PATH', 'FIREBASE_WEB_CONFIG', 'FIREBASE_VAPID_PUBLIC',
]

# Claves que nunca se devuelven al navegador y se guardan cifradas
CLAVES_SECRETAS = {'GREEN_API_TOKEN', 'CLOUDINARY_API_SECRET'}

# Claves numéricas del negocio
CLAVES_COMISION = ['comision_default', 'comision_minima', 'comision_maxima']

_PREFIJO = 'enc:'


def _fernet(secret_key=None):
    secret_key = secret_key or current_app.config['SECRET_KEY']
    clave = base64.urlsafe_b64encode(hashlib.sha256(secret_key.encode()).digest())
    return Fernet(clave)


def cifrar(valor: str) -> str:
    if not valor:
        return ''
    return _PREFIJO + _fernet().encrypt(valor.encode()).decode()


def descifrar(valor: str) -> str:
    if not valor or not valor.startswith(_PREFIJO):
        return valor or ''
    try:
        return _fernet().decrypt(valor[len(_PREFIJO):].encode()).decode()
    except InvalidToken:
        current_app.logger.error("No se pudo descifrar un secreto de la BD (¿cambió SECRET_KEY?)")
        return ''


def cargar_config_bd(app):
    """Copia a app.config los valores no vacíos guardados en la BD."""
    from models import Configuracion
    with app.app_context():
        try:
            filas = Configuracion.query.filter(Configuracion.clave.in_(CLAVES_INTEGRACION)).all()
        except Exception as e:  # tablas aún no creadas (antes de `flask db upgrade`)
            app.logger.warning(f"No se pudo leer la configuración de la BD: {e}")
            return
        for fila in filas:
            valor = descifrar(fila.valor) if fila.clave in CLAVES_SECRETAS else (fila.valor or '')
            if valor:
                app.config[fila.clave] = valor.rstrip('/') if fila.clave == 'APP_URL' else valor


def guardar_config(datos: dict):
    """
    Guarda las claves de integración. Para los secretos, un valor vacío significa
    "no cambiar" (el formulario nunca muestra el valor guardado).
    """
    from models import db, Configuracion
    for clave in CLAVES_INTEGRACION:
        if clave not in datos:
            continue
        valor = (datos.get(clave) or '').strip()
        es_secreto = clave in CLAVES_SECRETAS
        if es_secreto and not valor:
            continue
        guardado = cifrar(valor) if es_secreto else valor
        fila = Configuracion.query.filter_by(clave=clave).first()
        if fila:
            fila.valor = guardado
        else:
            db.session.add(Configuracion(clave=clave, valor=guardado))
        current_app.config[clave] = valor.rstrip('/') if clave == 'APP_URL' else valor
    db.session.commit()


def borrar_secreto(clave: str):
    from models import db, Configuracion
    if clave not in CLAVES_SECRETAS:
        return
    fila = Configuracion.query.filter_by(clave=clave).first()
    if fila:
        fila.valor = ''
        db.session.commit()
    current_app.config[clave] = ''


def valores_para_formulario() -> dict:
    """Valores actuales para el panel (los secretos solo indican si existen)."""
    cfg = current_app.config
    datos = {c: cfg.get(c, '') or '' for c in CLAVES_INTEGRACION if c not in CLAVES_SECRETAS}
    datos['secretos'] = {c: bool(cfg.get(c)) for c in CLAVES_SECRETAS}
    datos.update(comisiones())
    return datos


def get_decimal(clave: str, default: str) -> Decimal:
    from models import Configuracion
    fila = Configuracion.query.filter_by(clave=clave).first()
    try:
        return Decimal(fila.valor) if fila and fila.valor else Decimal(default)
    except InvalidOperation:
        return Decimal(default)


def comisiones() -> dict:
    return {
        'comision_default': get_decimal('comision_default', '15'),
        'comision_minima':  get_decimal('comision_minima', '5'),
        'comision_maxima':  get_decimal('comision_maxima', '30'),
    }


def guardar_comisiones(datos: dict):
    """Valida y guarda los porcentajes de comisión. Devuelve un mensaje de error o None."""
    from models import db, Configuracion
    try:
        nuevos = {c: Decimal(str(datos.get(c, '')).strip()) for c in CLAVES_COMISION}
    except InvalidOperation:
        return 'Los porcentajes de comisión deben ser números'
    mn, df, mx = nuevos['comision_minima'], nuevos['comision_default'], nuevos['comision_maxima']
    if not (Decimal('0') <= mn <= df <= mx <= Decimal('100')):
        return 'Las comisiones deben cumplir 0 ≤ mínima ≤ por defecto ≤ máxima ≤ 100'
    for clave, valor in nuevos.items():
        fila = Configuracion.query.filter_by(clave=clave).first()
        if fila:
            fila.valor = str(valor)
        else:
            db.session.add(Configuracion(clave=clave, valor=str(valor)))
    db.session.commit()
    return None
