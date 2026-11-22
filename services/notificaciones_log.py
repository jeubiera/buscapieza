"""
Guarda log de cada notificación enviada en la BD (visible en /admin/notificaciones).
Usa una sesión propia para no hacer commit de cambios ajenos de la petición.
"""
from flask import current_app
from sqlalchemy.orm import Session


def log(tipo: str, destinatario: str, mensaje: str, enviado: bool, error: str = ''):
    from extensions import db
    from models import Notificacion, ahora_utc

    destinatario = destinatario or ''
    if len(destinatario) > 20:               # tokens push: guardar solo un prefijo
        destinatario = destinatario[:17] + '...'
    try:
        with Session(db.engine) as s:
            s.add(Notificacion(
                tipo         = tipo,
                destinatario = destinatario,
                mensaje      = (mensaje or '')[:500],
                enviado      = enviado,
                error        = error[:300] if error else None,
                created_at   = ahora_utc(),
            ))
            s.commit()
    except Exception as e:
        current_app.logger.error(f"No se pudo guardar log de notificación: {e}")
