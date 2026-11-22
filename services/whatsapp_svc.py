"""
Servicio WhatsApp usando Green API (green-api.com)
- Plan gratuito: 300 mensajes/día
- Registro en: https://green-api.com/
"""
import requests
from flask import current_app
from services.notificaciones_log import log

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
        log('whatsapp', num, mensaje, True)
        return True
    except requests.RequestException as e:
        # No registrar la URL completa: contiene el token
        error = f"{type(e).__name__}: {getattr(e.response, 'status_code', '')}".strip()
        current_app.logger.error(f"Error WhatsApp → {num}: {error}")
        log('whatsapp', num, mensaje, False, error)
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
        "fileName": "articulo.jpg",
        "caption" : caption
    }
    try:
        r = requests.post(url, json=body, timeout=10)
        r.raise_for_status()
        return True
    except requests.RequestException as e:
        error = f"{type(e).__name__}: {getattr(e.response, 'status_code', '')}".strip()
        current_app.logger.error(f"Error WhatsApp imagen → {num}: {error}")
        log('whatsapp', num, f"[imagen] {caption}", False, error)
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
        f"🔔 *Nueva Solicitud BuscatodoRD*\n"
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
        f"🔍 *BuscatodoRD — Solicitud para ti, {nombre_prov}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 {sol.codigo}\n"
        f"📂 {sol.categoria.nombre if sol.categoria else 'General'}\n"
        f"{urgencia_emoji} *{sol.titulo}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📝 {sol.descripcion[:300]}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"¿Lo tienes? Envía tu precio aquí:\n"
        f"🔗 {current_app.config.get('APP_URL', '')}/ofertas/hacer/{sol.id}\n\n"
        f"_Solo BuscatodoRD verá tu oferta_"
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

    broker_nombre = current_app.config.get('BROKER_NOMBRE', 'BuscatodoRD')
    broker_wa     = current_app.config.get('BROKER_WHATSAPP', '')

    msg = (
        f"✅ *{broker_nombre}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Hola {sol.cliente.nombre.split()[0]}, tenemos respuesta\n"
        f"para tu búsqueda:\n\n"
        f"🔍 *{sol.titulo}* ({sol.codigo})\n\n"
    )
    trans = sol.transaccion_activa()
    if trans:
        msg += (
            f"💰 Precio: *RD${trans.precio_cliente:,.2f}*\n"
            f"Te contactaremos en breve para coordinar\n"
            f"el pago y la entrega.\n"
        )
    else:
        msg += (
            f"Encontramos lo que buscas. Te llamaremos\n"
            f"en breve con el precio y condiciones.\n"
        )
    msg += "━━━━━━━━━━━━━━━━━━━━\n"
    if broker_wa:
        msg += f"También puedes escribirnos: wa.me/{_limpiar_numero(broker_wa)}"

    return _enviar(numero, msg)


# ── Compraventa ───────────────────────────────────────────────────────────────

def _url(ruta: str) -> str:
    return f"{current_app.config.get('APP_URL', '').rstrip('/')}{ruta}"


def notificar_broker_nueva_publicacion(pub) -> bool:
    """Avisa al broker que un usuario quiere vender algo (pendiente de revisión)."""
    broker_wa = current_app.config.get('BROKER_WHATSAPP', '')
    if not broker_wa:
        return False
    v = pub.vendedor
    msg = (
        f"🏷️ *Nueva publicación para revisar*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 {pub.codigo} · {pub.condicion.title()}\n"
        f"📦 *{pub.titulo}*\n"
        f"💰 Pide: *RD${pub.precio_pedido:,.2f}*\n"
        f"👤 {v.nombre} · 📞 wa.me/{_limpiar_numero(v.whatsapp or v.telefono)}\n"
        f"📍 {pub.provincia.nombre if pub.provincia else 'N/A'}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔗 {_url(f'/admin/publicacion/{pub.id}')}"
    )
    ok = _enviar(broker_wa, msg)
    if ok and pub.fotos and pub.fotos[0].url.startswith('http'):
        _enviar_con_imagen(broker_wa, pub.fotos[0].url, f"📷 {pub.titulo} ({pub.codigo})")
    return ok


def notificar_broker_interes(interes) -> bool:
    """Avisa al broker que un comprador pidió precio o mostró interés."""
    broker_wa = current_app.config.get('BROKER_WHATSAPP', '')
    if not broker_wa:
        return False
    pub, c = interes.publicacion, interes.comprador
    msg = (
        f"🛒 *Interesado en {pub.codigo}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 {pub.titulo}\n"
        f"👤 {c.nombre} · 📞 wa.me/{_limpiar_numero(c.whatsapp or c.telefono)}\n"
    )
    if interes.oferta_comprador:
        msg += f"💬 Ofrece: *RD${interes.oferta_comprador:,.2f}*\n"
    if pub.precio_publico is not None:
        msg += f"🏷️ Lista: RD${pub.precio_publico:,.2f} · Vendedor: RD${pub.precio_vendedor:,.2f}\n"
    if interes.mensaje:
        msg += f"📝 {interes.mensaje[:200]}\n"
    msg += f"━━━━━━━━━━━━━━━━━━━━\n🔗 {_url(f'/admin/publicacion/{pub.id}')}"
    return _enviar(broker_wa, msg)


def notificar_vendedor_estado(pub) -> bool:
    """Avisa al vendedor que su publicación fue aprobada o rechazada (sin revelar el margen)."""
    v = pub.vendedor
    numero = v.whatsapp or v.telefono
    if not numero:
        return False
    nombre = current_app.config.get('BROKER_NOMBRE', 'BuscatodoRD')
    if pub.estado == 'publicada':
        msg = (
            f"✅ *{nombre}*\n"
            f"Hola {v.nombre.split()[0]}, tu artículo ya está publicado:\n\n"
            f"📦 *{pub.titulo}* ({pub.codigo})\n"
            f"💰 Recibirás: *RD${pub.precio_vendedor:,.2f}* al venderse\n\n"
            f"Te avisaremos cuando haya un comprador.\n"
            f"🔗 {_url(f'/catalogo/{pub.id}')}"
        )
    elif pub.estado == 'rechazada':
        msg = (
            f"ℹ️ *{nombre}*\n"
            f"Hola {v.nombre.split()[0]}, revisamos tu publicación *{pub.titulo}* ({pub.codigo}) "
            f"y necesita cambios:\n\n{(pub.motivo_rechazo or '').strip()[:400]}\n\n"
            f"Puedes corregirla y reenviarla aquí:\n🔗 {_url('/vender/mis-publicaciones')}"
        )
    else:
        return False
    return _enviar(numero, msg)


# ── Negociación (Fase 2) ──────────────────────────────────────────────────────

def notificar_vendedor_propuesta(prop) -> bool:
    """El admin propone al vendedor cuánto recibirá."""
    pub, v = prop.publicacion, prop.publicacion.vendedor
    numero = v.whatsapp or v.telefono
    if not numero:
        return False
    nombre = current_app.config.get('BROKER_NOMBRE', 'BuscatodoRD')
    msg = (
        f"💬 *{nombre}*\n"
        f"Hola {v.nombre.split()[0]}, sobre tu artículo *{pub.titulo}* ({pub.codigo}):\n\n"
        f"Te proponemos que recibas *RD${prop.monto:,.2f}* cuando se venda.\n"
    )
    if prop.mensaje:
        msg += f"📝 {prop.mensaje[:300]}\n"
    msg += f"\nAcepta o contrapropón aquí:\n🔗 {_url('/vender/mis-publicaciones')}"
    return _enviar(numero, msg)


def notificar_comprador_cotizacion(prop) -> bool:
    """El admin envía un precio privado a un interesado."""
    it = prop.interes
    pub, c = it.publicacion, it.comprador
    numero = c.whatsapp or c.telefono
    if not numero:
        return False
    nombre = current_app.config.get('BROKER_NOMBRE', 'BuscatodoRD')
    msg = (
        f"🏷️ *{nombre}*\n"
        f"Hola {c.nombre.split()[0]}, tenemos precio para ti:\n\n"
        f"📦 *{pub.titulo}* ({pub.codigo})\n"
        f"💰 *RD${prop.monto:,.2f}*\n"
    )
    if prop.mensaje:
        msg += f"📝 {prop.mensaje[:300]}\n"
    msg += f"\nAcéptalo o haz tu oferta aquí:\n🔗 {_url('/catalogo/mis-consultas')}"
    return _enviar(numero, msg)


def notificar_broker_respuesta(prop, evento: str) -> bool:
    """Un vendedor o comprador respondió en el panel (aceptó, contrapropuso o rechazó)."""
    broker_wa = current_app.config.get('BROKER_WHATSAPP', '')
    if not broker_wa:
        return False
    pub = prop.publicacion
    quien = 'Vendedor' if prop.tipo == 'vendedor' else 'Comprador'
    persona = pub.vendedor if prop.tipo == 'vendedor' else prop.interes.comprador
    icono = {'aceptada': '✅', 'contraofertada': '↔️', 'rechazada': '❌'}.get(evento, '💬')
    texto = {'aceptada': 'aceptó', 'contraofertada': 'contrapropone', 'rechazada': 'rechazó'}.get(evento, evento)
    msg = (
        f"{icono} *{quien} {texto}* · {pub.codigo}\n"
        f"📦 {pub.titulo}\n"
        f"👤 {persona.nombre}\n"
        f"💰 RD${prop.monto:,.2f}\n"
    )
    if evento == 'aceptada' and prop.tipo == 'comprador':
        msg += "🤝 Venta registrada, pendiente de pago\n"
    if evento == 'aceptada' and prop.tipo == 'vendedor':
        msg += "📢 Artículo publicado en el catálogo\n"
    if prop.mensaje:
        msg += f"📝 {prop.mensaje[:200]}\n"
    msg += f"🔗 {_url(f'/admin/publicacion/{pub.id}')}"
    return _enviar(broker_wa, msg)


def notificar_broker_coincidencias(coincidencias) -> bool:
    broker_wa = current_app.config.get('BROKER_WHATSAPP', '')
    if not broker_wa or not coincidencias:
        return False
    lineas = [f"🎯 *{len(coincidencias)} coincidencia(s) nueva(s)*", "━━━━━━━━━━━━━━━━━━━━"]
    for c in coincidencias[:5]:
        lineas.append(f"🔍 {c.solicitud.codigo} {c.solicitud.titulo[:40]}\n   ↔ 🏷️ {c.publicacion.codigo} {c.publicacion.titulo[:40]}")
    if len(coincidencias) > 5:
        lineas.append(f"... y {len(coincidencias) - 5} más")
    lineas.append(f"🔗 {_url('/admin/coincidencias')}")
    return _enviar(broker_wa, '\n'.join(lineas))


def notificar_cliente_coincidencia(coinc) -> bool:
    """Ofrece al cliente que buscaba algo un artículo en venta (sin datos del vendedor)."""
    sol, pub = coinc.solicitud, coinc.publicacion
    c = sol.cliente
    numero = c.whatsapp or c.telefono
    if not numero:
        return False
    nombre = current_app.config.get('BROKER_NOMBRE', 'BuscatodoRD')
    msg = (
        f"🎯 *{nombre}*\n"
        f"Hola {c.nombre.split()[0]}, para tu búsqueda *{sol.titulo}* ({sol.codigo}) "
        f"tenemos esto disponible:\n\n"
        f"📦 *{pub.titulo}* · {pub.condicion.title()}\n"
    )
    if pub.mostrar_precio and pub.precio_publico is not None:
        msg += f"💰 RD${pub.precio_publico:,.0f}\n"
    msg += f"\nMíralo y pide tu precio aquí:\n🔗 {_url(f'/catalogo/{pub.id}')}"
    ok = _enviar(numero, msg)
    if ok and pub.fotos and pub.fotos[0].url.startswith('http'):
        _enviar_con_imagen(numero, pub.fotos[0].url, f"📷 {pub.titulo}")
    return ok



# ── Pagos (Fase 3) ────────────────────────────────────────────────────────────

def notificar_broker_pago(pago, evento: str) -> bool:
    """evento: 'comprobante' (transferencia por revisar) o 'aprobado' (tarjeta aprobada)."""
    broker_wa = current_app.config.get('BROKER_WHATSAPP', '')
    if not broker_wa:
        return False
    u = pago.usuario
    if evento == 'comprobante':
        cab = f"🧾 *Comprobante por revisar* · {pago.referencia}"
    else:
        cab = f"💳 *Pago aprobado ({pago.metodo.title()})* · {pago.referencia}"
    msg = (
        f"{cab}\n"
        f"📦 {pago.descripcion[:80]}\n"
        f"👤 {u.nombre}\n"
        f"💰 RD${pago.monto:,.2f}\n"
        f"🔗 {_url('/admin/pagos')}"
    )
    return _enviar(broker_wa, msg)


def notificar_usuario_pago(pago) -> bool:
    """Avisa al que pagó si su pago fue aprobado o rechazado."""
    u = pago.usuario
    numero = u.whatsapp or u.telefono
    if not numero:
        return False
    nombre = current_app.config.get('BROKER_NOMBRE', 'BuscatodoRD')
    if pago.estado == 'aprobado':
        msg = (
            f"✅ *{nombre}* — Pago confirmado\n"
            f"{pago.descripcion[:80]}\n"
            f"💰 RD${pago.monto:,.2f} · Ref. {pago.referencia}\n"
        )
        if pago.concepto == 'destacado' and pago.destacado and pago.destacado.fin:
            msg += f"⭐ Tu artículo está destacado hasta el {pago.destacado.fin.strftime('%d/%m/%Y')}\n"
        else:
            msg += "Te contactaremos para coordinar la entrega.\n"
        msg += f"🧾 Recibo: {_url(f'/pagos/{pago.referencia}/recibo')}"
    elif pago.estado == 'rechazado':
        msg = (
            f"⚠️ *{nombre}* — No pudimos confirmar tu pago\n"
            f"Ref. {pago.referencia} · RD${pago.monto:,.2f}\n"
            f"{(pago.motivo_rechazo or '')[:300]}\n"
            f"Revísalo aquí: {_url(f'/pagos/{pago.referencia}')}"
        )
    else:
        return False
    return _enviar(numero, msg)



# ── Referidos ─────────────────────────────────────────────────────────────────

def notificar_comision_referido(comision) -> bool:
    """'Ganaste RD$X porque alguien de tu red compró' (del comprador solo nombre y una inicial)."""
    u = comision.beneficiario
    numero = u.whatsapp or u.telefono
    if not numero:
        return False
    from services.referidos import nombre_privado, config
    nombre = current_app.config.get('BROKER_NOMBRE', 'BuscatodoRD')
    meta = config()['meta']
    msg = (
        f"🎉 *{nombre}*\n"
        f"¡Ganaste *RD${comision.monto:,.2f}*! {nombre_privado(comision.comprador)} "
        f"(nivel {comision.nivel} de tu red) hizo una compra.\n"
    )
    if meta > 0:
        msg += f"Recuerda: para cobrar este mes necesitas compras personales por RD${meta:,.0f}.\n"
    msg += f"Mira tu red y tus comisiones: {_url('/referidos')}"
    return _enviar(numero, msg)


def notificar_liquidacion_referido(liq) -> bool:
    u = liq.beneficiario
    numero = u.whatsapp or u.telefono
    if not numero:
        return False
    nombre = current_app.config.get('BROKER_NOMBRE', 'BuscatodoRD')
    ref = f" (ref. {liq.referencia})" if liq.referencia else ''
    msg = (
        f"💸 *{nombre}*\n"
        f"Te pagamos *RD${liq.monto:,.2f}* de tus comisiones por referidos{ref}.\n"
        f"¡Gracias por recomendarnos! {_url('/referidos')}"
    )
    return _enviar(numero, msg)
