"""
Tareas de notificación pensadas para ejecutarse con services.tareas.en_segundo_plano.
Reciben IDs y vuelven a cargar los objetos en su propia sesión.
"""
from flask import current_app
from extensions import db


def tarea_nueva_solicitud(sol_id: int):
    from models import Solicitud
    from services.whatsapp_svc import notificar_broker_nueva_solicitud
    from services.push_svc import notificar_nueva_solicitud

    sol = db.session.get(Solicitud, sol_id)
    if not sol:
        return
    for envio in (notificar_broker_nueva_solicitud, notificar_nueva_solicitud):
        try:
            envio(sol)
        except Exception as e:
            current_app.logger.error(f"{envio.__name__} ({sol.codigo}): {e}")


def tarea_nueva_oferta(oferta_id: int):
    from models import Oferta
    from services.whatsapp_svc import notificar_broker_nueva_oferta
    from services.push_svc import notificar_nueva_oferta

    oferta = db.session.get(Oferta, oferta_id)
    if not oferta:
        return
    for envio in (notificar_broker_nueva_oferta, notificar_nueva_oferta):
        try:
            envio(oferta, oferta.solicitud)
        except Exception as e:
            current_app.logger.error(f"{envio.__name__} (oferta {oferta_id}): {e}")


def tarea_notificar_proveedores(sol_id: int):
    """WhatsApp a cada proveedor verificado + push masivo. El resultado queda en el log."""
    from models import Solicitud, Usuario
    from services.whatsapp_svc import notificar_proveedor_solicitud
    from services.push_svc import enviar_push_a_todos_proveedores

    sol = db.session.get(Solicitud, sol_id)
    if not sol:
        return
    proveedores = Usuario.query.filter_by(rol='proveedor', activo=True, verificado=True).all()

    wa_ok = 0
    for prov in proveedores:
        try:
            if notificar_proveedor_solicitud(prov, sol):
                wa_ok += 1
        except Exception as e:
            current_app.logger.error(f"WA proveedor {prov.id}: {e}")

    push_ok = 0
    try:
        push_ok = enviar_push_a_todos_proveedores(
            titulo=f"🔍 {sol.titulo[:50]}",
            cuerpo=f"Nueva solicitud {sol.codigo} — ¿Tienes esta pieza?",
            url=f"/ofertas/hacer/{sol.id}"
        )
    except Exception as e:
        current_app.logger.error(f"Push proveedores: {e}")

    current_app.logger.info(
        f"{sol.codigo}: WhatsApp {wa_ok}/{len(proveedores)} proveedores · Push {push_ok} dispositivos")
