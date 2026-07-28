"""
Servicio WhatsApp usando Green API (green-api.com)
- Plan gratuito: 300 mensajes/día
- Registro en: https://green-api.com/
"""
import requests
from flask import current_app

# ── helpers ──────────────────────────────────────────────────────────────────

def _cfg():
    return (
        current_app.config.get('GREEN_API_INSTANCE', ''),
        current_app.config.get('GREEN_API_TOKEN', ''),
    )

def _limpiar_numero(numero: str) -> str:
    """
    Normaliza un número de RD al formato requerido por Green API.
    Entrada:  '809-555-0000'  ó  '18095550000'  ó  '8095550000'
    Salida:   '18095550000'   (siempre con código de país)
    """
    num = ''.join(c for c in numero if c.isdigit())
    if len(num) == 10:          # 8095550000 → agregar 1 (RD)
        num = '1' + num
    elif len(num) == 7:         # sin área → no procesar
        return ''
    return num

def _enviar(numero: str, mensaje: str) -> bool:
    instance, token = _cfg()
    if not instance or not token:
        current_app.logger.warning("WhatsApp no configurado (GREEN_API_INSTANCE vacío)")
        return False

    num = _limpiar_numero(numero)
    if not num:
        current_app.logger.warning(f"Número inválido: {numero}")
        return False

    url  = f"https://api.green-api.com/waInstance{instance}/sendMessage/{token}"
    body = {"chatId": f"{num}@c.us", "message": mensaje}

    try:
        r = requests.post(url, json=body, timeout=8)
        r.raise_for_status()
        return True
    except requests.RequestException as e:
        current_app.logger.error(f"Error WhatsApp → {num}: {e}")
        return False

def _enviar_con_imagen(numero: str, imagen_url: str, caption: str) -> bool:
    """Envía imagen + texto (para fotos de solicitud)"""
    instance, token = _cfg()
    if not instance or not token:
        return False

    num = _limpiar_numero(numero)
    if not num:
        return False

    url  = f"https://api.green-api.com/waInstance{instance}/sendFileByUrl/{token}"
    body = {
        "chatId"  : f"{num}@c.us",
        "urlFile" : imagen_url,
        "fileName": "pieza.jpg",
        "caption" : caption
    }
    try:
        r = requests.post(url, json=body, timeout=10)
        r.raise_for_status()
        return True
    except requests.RequestException as e:
        current_app.logger.error(f"Error WhatsApp imagen → {num}: {e}")
        return False

# ── mensajes de negocio ───────────────────────────────────────────────────────

def notificar_broker_nueva_solicitud(sol) -> bool:
    """
    Avisa al broker (admin) que llegó una nueva solicitud.
    """
    broker_wa = current_app.config.get('BROKER_WHATSAPP', '')
    if not broker_wa:
        return False

    urgencia_emoji = {'normal': '🟢', 'urgente': '🟡', 'muy_urgente': '🔴'}.get(sol.urgencia, '🟢')

    msg = (
        f"🔔 *Nueva Solicitud BuscaPieza RD*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 Código: *{sol.codigo}*\n"
        f"👤 Cliente: {sol.cliente.nombre}\n"
        f"📞 Tel: {sol.cliente.telefono}\n"
        f"📂 Categoría: {sol.categoria.nombre if sol.categoria else 'General'}\n"
        f"📍 Provincia: {sol.provincia.nombre if sol.provincia else 'N/A'}\n"
        f"🔍 *{sol.titulo}*\n"
        f"{urgencia_emoji} Urgencia: {sol.urgencia.replace('_',' ').title()}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📝 {sol.descripcion[:200]}"
    )

    ok = _enviar(broker_wa, msg)

    # Si tiene foto, enviarla también
    if ok and sol.fotos and sol.fotos[0].url.startswith('http'):
        caption = f"📷 Foto de: {sol.titulo} ({sol.codigo})"
        _enviar_con_imagen(broker_wa, sol.fotos[0].url, caption)

    return ok


def notificar_broker_nueva_oferta(oferta, sol) -> bool:
    """
    Avisa al broker que un proveedor hizo una oferta.
    """
    broker_wa = current_app.config.get('BROKER_WHATSAPP', '')
    if not broker_wa:
        return False

    prov = oferta.proveedor
    msg  = (
        f"💼 *Nueva Oferta Recibida*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 Solicitud: *{sol.codigo}*\n"
        f"🔍 {sol.titulo}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🏪 Proveedor: *{prov.empresa or prov.nombre}*\n"
        f"📞 WhatsApp: wa.me/{_limpiar_numero(prov.whatsapp or prov.telefono)}\n"
        f"💰 Precio: *RD${oferta.precio:,.2f}*\n"
        f"🚚 Entrega: {oferta.tiempo_entrega}\n"
        f"📦 Incluye envío: {'✅ Sí' if oferta.incluye_envio else '❌ No'}\n"
    )
    if oferta.descripcion:
        msg += f"📝 {oferta.descripcion[:150]}\n"

    return _enviar(broker_wa, msg)


def notificar_proveedor_solicitud(proveedor, sol) -> bool:
    """
    Envía solicitud a un proveedor específico para que oferte.
    El cliente NO aparece en este mensaje.
    """
    numero = proveedor.whatsapp or proveedor.telefono
    if not numero:
        return False

    urgencia_emoji = {'normal': '🟢', 'urgente': '⚡', 'muy_urgente': '🔥'}.get(sol.urgencia, '🟢')

    nombre_prov = proveedor.nombre.split()[0]
    msg = (
        f"🔍 *BuscaPieza RD — Solicitud para ti, {nombre_prov}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 {sol.codigo}\n"
        f"📂 {sol.categoria.nombre if sol.categoria else 'General'}\n"
        f"{urgencia_emoji} *{sol.titulo}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📝 {sol.descripcion[:300]}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"¿Tienes esta pieza? Responde con tu precio:\n"
        f"🔗 https://buscapieza.do/ofertas/hacer/{sol.id}\n\n"
        f"_Solo BuscaPieza verá tu oferta_"
    )

    ok = _enviar(numero, msg)

    # Enviar primera foto si existe y es URL pública
    if ok and sol.fotos and sol.fotos[0].url.startswith('http'):
        caption = f"📷 {sol.titulo}"
        _enviar_con_imagen(numero, sol.fotos[0].url, caption)

    return ok


def notificar_cliente_oferta_disponible(sol) -> bool:
    """
    El broker le avisa al cliente que tiene una respuesta.
    NO revela nada del proveedor.
    """
    numero = sol.cliente.whatsapp or sol.cliente.telefono
    if not numero:
        return False

    broker_nombre = current_app.config.get('BROKER_NOMBRE', 'BuscaPieza RD')
    broker_wa     = current_app.config.get('BROKER_WHATSAPP', '')

    msg = (
        f"✅ *{broker_nombre}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Hola {sol.cliente.nombre.split()[0]}, tenemos respuesta\n"
        f"para tu búsqueda:\n\n"
        f"🔍 *{sol.titulo}* ({sol.codigo})\n\n"
        f"Encontramos la pieza disponible. Te llamaremos\n"
        f"en breve con el precio y condiciones.\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
    )
    if broker_wa:
        msg += f"También puedes escribirnos: wa.me/{_limpiar_numero(broker_wa)}"

    return _enviar(numero, msg)
