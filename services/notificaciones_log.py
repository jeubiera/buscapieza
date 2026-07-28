"""
Guarda log de cada notificación enviada en la BD.
"""
from models import db, Notificacion
from datetime import datetime

def log(tipo: str, destinatario: str, mensaje: str, enviado: bool, error: str = ''):
    n = Notificacion(
        tipo         = tipo,
        destinatario = destinatario,
        mensaje      = mensaje[:500],
        enviado      = enviado,
        error        = error[:300] if error else None,
        created_at   = datetime.utcnow()
    )
    db.session.add(n)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
