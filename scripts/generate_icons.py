"""
Genera todos los iconos e imágenes de marca de BuscatodoRD a partir del logo.

    python scripts/generate_icons.py

Fuente: assets/marca/logo.png (logo completo con fondo transparente).
Del logo se recorta el símbolo (la bolsa con la lupa) para los iconos cuadrados.

Genera en static/icons/:  icon-*.png, icon-maskable-*.png, apple-touch-icon.png,
                          favicon-16/32.png, favicon.ico, badge-96.png, shortcut-*.png
y en static/img/:         logo.png (barra de navegación), og-image.png (vista previa al compartir)
"""
import os
import sys

from PIL import Image, ImageDraw

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FUENTE = os.path.join(RAIZ, 'assets', 'marca', 'logo.png')
ICONOS = os.path.join(RAIZ, 'static', 'icons')
IMG = os.path.join(RAIZ, 'static', 'img')

# Columna del logo donde termina el símbolo y empieza el texto "BuscatodoRD"
CORTE_SIMBOLO = 517

BLANCO = (255, 255, 255, 255)
NAVY = (0, 24, 56, 255)       # #001838 (texto del logo)
AZUL = (0, 72, 144, 255)      # #004890 (bolsa)
ROJO = (208, 0, 0, 255)       # #D00000 ("RD")


def recortar(img):
    return img.crop(img.getchannel('A').getbbox())


def colocar(simbolo, lado, fraccion, fondo=None, radio=0.0):
    """Centra el símbolo en un cuadrado de `lado` px ocupando `fraccion` del lado."""
    lienzo = Image.new('RGBA', (lado, lado), (0, 0, 0, 0))
    if fondo:
        d = ImageDraw.Draw(lienzo)
        if radio:
            d.rounded_rectangle([0, 0, lado - 1, lado - 1], radius=int(lado * radio), fill=fondo)
        else:
            d.rectangle([0, 0, lado - 1, lado - 1], fill=fondo)
    s = simbolo.copy()
    max_lado = int(lado * fraccion)
    s.thumbnail((max_lado, max_lado), Image.LANCZOS)
    lienzo.alpha_composite(s, ((lado - s.width) // 2, (lado - s.height) // 2))
    return lienzo


def guardar(img, ruta, opaco=False):
    if opaco:
        img = img.convert('RGB')
    img.save(ruta, optimize=True)
    print(f'  {os.path.relpath(ruta, RAIZ)}  {img.width}x{img.height}')


def insignia(simbolo, lado, color, dibujo):
    """Símbolo con un círculo de color en la esquina (atajos de la PWA)."""
    base = colocar(simbolo, lado, 0.78, fondo=BLANCO, radio=0.22)
    d = ImageDraw.Draw(base)
    r = int(lado * 0.2)
    cx, cy = lado - r - int(lado * 0.04), lado - r - int(lado * 0.04)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color, outline=BLANCO, width=max(2, lado // 48))
    dibujo(d, cx, cy, r)
    return base


def mas(d, cx, cy, r):
    g = max(3, r // 4)
    d.rectangle([cx - r // 2, cy - g // 2, cx + r // 2, cy + g // 2], fill=BLANCO)
    d.rectangle([cx - g // 2, cy - r // 2, cx + g // 2, cy + r // 2], fill=BLANCO)


def lista(d, cx, cy, r):
    g = max(2, r // 6)
    for i in (-1, 0, 1):
        y = cy + i * int(r * 0.42)
        d.rectangle([cx - r // 2, y - g // 2, cx + r // 2, y + g // 2], fill=BLANCO)


def main():
    if not os.path.exists(FUENTE):
        sys.exit(f'No se encontró {FUENTE}')
    os.makedirs(ICONOS, exist_ok=True)
    os.makedirs(IMG, exist_ok=True)

    logo = recortar(Image.open(FUENTE).convert('RGBA'))
    simbolo = recortar(Image.open(FUENTE).convert('RGBA').crop((0, 0, CORTE_SIMBOLO, logo.height + 100)))

    print('Iconos de la app:')
    for lado in (48, 72, 96, 128, 144, 152, 192, 256, 384, 512):
        guardar(colocar(simbolo, lado, 0.84, fondo=BLANCO, radio=0.22), os.path.join(ICONOS, f'icon-{lado}.png'))
    # Maskable: el sistema recorta en círculo/forma propia → zona segura del 80%, fondo a sangre
    for lado in (192, 512):
        guardar(colocar(simbolo, lado, 0.62, fondo=BLANCO), os.path.join(ICONOS, f'icon-maskable-{lado}.png'), opaco=True)
    guardar(colocar(simbolo, 180, 0.8, fondo=BLANCO), os.path.join(ICONOS, 'apple-touch-icon.png'), opaco=True)

    print('Favicon:')
    for lado in (16, 32):
        guardar(colocar(simbolo, lado, 1.0), os.path.join(ICONOS, f'favicon-{lado}.png'))
    colocar(simbolo, 256, 1.0).save(os.path.join(ICONOS, 'favicon.ico'), sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
    print('  static/icons/favicon.ico  16/32/48/64')

    # Insignia de notificaciones (Android solo usa el canal alfa): silueta blanca
    silueta = Image.new('RGBA', simbolo.size, BLANCO)
    silueta.putalpha(simbolo.getchannel('A'))
    guardar(colocar(silueta, 96, 0.9), os.path.join(ICONOS, 'badge-96.png'))

    print('Atajos:')
    guardar(insignia(simbolo, 192, ROJO, mas), os.path.join(ICONOS, 'shortcut-nueva-192.png'))
    guardar(insignia(simbolo, 192, NAVY, lista), os.path.join(ICONOS, 'shortcut-ofertas-192.png'))

    print('Imágenes de marca:')
    nav = logo.copy()
    nav.thumbnail((10000, 144), Image.LANCZOS)   # 48 px de alto en pantallas 3x
    guardar(nav, os.path.join(IMG, 'logo.png'))
    og = Image.new('RGBA', (1200, 630), BLANCO)
    l = logo.copy()
    l.thumbnail((1040, 400), Image.LANCZOS)
    og.alpha_composite(l, ((1200 - l.width) // 2, (630 - l.height) // 2))
    guardar(og, os.path.join(IMG, 'og-image.png'), opaco=True)

    # Restos de la marca anterior
    for viejo in ('icon.svg', 'mask-icon.svg'):
        ruta = os.path.join(ICONOS, viejo)
        if os.path.exists(ruta):
            os.remove(ruta)
            print(f'  eliminado static/icons/{viejo} (marca anterior)')


if __name__ == '__main__':
    main()
