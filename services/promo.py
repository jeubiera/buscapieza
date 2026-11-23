"""
Kit de promoción del programa de referidos (como el kit de clientes_app de AmbarERP).

- Enlace de invitación con seguimiento: /auth/registro?ref=CODIGO&p=<plantilla>
  (p = f12 para la frase 12, i3 para la imagen 3, qr para el QR) → se guarda en usuarios.plantilla_ref
- Frases con marcadores {link}, {nombre} y {codigo}
- QR generado en el servidor (PNG), que también se incrusta en las imágenes del kit
"""
import io
import re

from flask import current_app, url_for

from extensions import db
from models import PromoPlantilla, Usuario

REF_VALIDA = re.compile(r'^[a-z0-9_-]{1,30}$')

CATEGORIAS = {
    'ganancias': '💰 Gana recomendando',
    'buscar': '🔍 Encuentra lo que buscas',
    'vender': '🏷️ Vende lo que no usas',
    'general': '✨ General',
}

FRASES_INICIALES = [
    ('ganancias', 'Estoy ganando dinero recomendando BuscatodoRD 💰 Regístrate gratis con mi enlace y empieza tú también: {link}'),
    ('ganancias', 'Cada vez que alguien que invito compra en BuscatodoRD, yo gano. Únete con mi código {codigo}: {link}'),
    ('ganancias', '¿Quieres un ingreso extra sin tener que vender nada? Recomienda BuscatodoRD y gana por las compras de tu gente 👉 {link}'),
    ('buscar', '¿Buscas una pieza, un repuesto o algo difícil de conseguir? Publícalo en BuscatodoRD y te lo consiguen en toda la RD 🔍 {link}'),
    ('buscar', 'Deja de dar vueltas buscando. En BuscatodoRD publicas lo que necesitas y te llegan las ofertas 🙌 {link}'),
    ('buscar', 'Compra seguro: BuscatodoRD verifica el artículo y coordina el pago y la entrega. Mira lo que hay a la venta: {link}'),
    ('vender', '¿Tienes cosas que ya no usas? En BuscatodoRD las publicas gratis y ellos te las venden 🏷️ {link}'),
    ('vender', 'Vende tu nevera, tu celular o tus repuestos sin regatear con desconocidos. BuscatodoRD lo hace por ti: {link}'),
]

IMAGENES_INICIALES = [
    ('ganancias', 'Recomienda y gana', 'Gana por cada compra de las personas que invites', '💰', '#0B5CAD', '#001838'),
    ('buscar', '¿No lo encuentras?', 'Publícalo gratis y te lo conseguimos en toda la RD', '🔍', '#D7141A', '#7A0B0F'),
    ('vender', 'Vende lo que ya no usas', 'Publica gratis: nosotros lo vendemos por ti', '🏷️', '#F59E0B', '#B45309'),
    ('buscar', 'Compra seguro', 'Artículos verificados, pago y entrega coordinados', '🛡️', '#10B981', '#065F46'),
]


def ref_valida(valor):
    valor = (valor or '').strip().lower()[:30]
    return valor if REF_VALIDA.match(valor) else None


def enlace(usuario: Usuario, ref=None) -> str:
    from services.referidos import asegurar_codigo
    base = current_app.config.get('APP_URL', '').rstrip('/')
    url = f"{base}{url_for('auth.registro')}?ref={asegurar_codigo(usuario)}"
    ref = ref_valida(ref)
    return f'{url}&p={ref}' if ref else url


def personalizar(texto: str, usuario: Usuario, ref=None) -> str:
    from services.referidos import asegurar_codigo
    nombre = (usuario.nombre or '').split()[0] if usuario.nombre else ''
    return (texto.replace('{link}', enlace(usuario, ref))
                 .replace('{nombre}', nombre)
                 .replace('{codigo}', asegurar_codigo(usuario)))


def qr_png(texto: str, tamano_modulo: int = 10, borde: int = 2) -> bytes:
    import qrcode
    from qrcode.image.pure import PyPNGImage
    img = qrcode.make(texto, image_factory=PyPNGImage, box_size=tamano_modulo, border=borde,
                      error_correction=qrcode.constants.ERROR_CORRECT_M)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue()


def activas(tipo: str):
    return (PromoPlantilla.query.filter_by(tipo=tipo, activa=True)
            .order_by(PromoPlantilla.orden, PromoPlantilla.id).all())


def estadisticas() -> dict:
    """{ref: nº de personas que se registraron con ese material}"""
    from sqlalchemy import func
    return dict(db.session.query(Usuario.plantilla_ref, func.count(Usuario.id))
                .filter(Usuario.plantilla_ref.isnot(None)).group_by(Usuario.plantilla_ref).all())


def sembrar():
    if PromoPlantilla.query.first():
        return
    for i, (cat, texto) in enumerate(FRASES_INICIALES):
        db.session.add(PromoPlantilla(tipo='frase', categoria=cat, texto=texto, orden=i, activa=True, con_qr=False))
    for i, (cat, titulo, sub, emoji, c1, c2) in enumerate(IMAGENES_INICIALES):
        db.session.add(PromoPlantilla(tipo='imagen', categoria=cat, texto='Únete a BuscatodoRD con mi enlace: {link}',
                                      titulo=titulo, subtitulo=sub, emoji=emoji, color_ini=c1, color_fin=c2,
                                      orden=i, activa=True, con_qr=True))
