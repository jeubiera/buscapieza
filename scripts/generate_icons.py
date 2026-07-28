"""
Genera el set completo de iconos PWA de BuscaPieza RD a partir de formas
vectoriales dibujadas con Pillow (supersampling 4x + downscale para anti-aliasing).

Uso: python scripts/generate_icons.py
"""
import os
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', 'static', 'icons')
os.makedirs(OUT, exist_ok=True)

NAVY   = (10, 14, 26, 255)     # #0A0E1A
ORANGE = (255, 107, 53, 255)   # #FF6B35
WHITE  = (255, 255, 255, 255)

SS = 4  # supersampling factor


def _canvas(size):
    return Image.new('RGBA', (size * SS, size * SS, ) if False else (size * SS, size * SS), (0, 0, 0, 0))


def rounded_square(size, bg, radius_frac):
    img = Image.new('RGBA', (size * SS, size * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = int(size * SS * radius_frac)
    d.rounded_rectangle([0, 0, size * SS - 1, size * SS - 1], radius=r, fill=bg)
    return img


def draw_magnifier(img, cx_frac, cy_frac, r_frac, stroke_frac, color, size):
    d = ImageDraw.Draw(img)
    S = size * SS
    cx, cy = cx_frac * S, cy_frac * S
    r = r_frac * S
    sw = max(2, int(stroke_frac * S))

    # circle (outline)
    bbox = [cx - r, cy - r, cx + r, cy + r]
    d.ellipse(bbox, outline=color, width=sw)

    # handle
    import math
    angle = math.radians(45)
    hx1 = cx + r * math.cos(angle)
    hy1 = cy + r * math.sin(angle)
    hlen = r * 0.85
    hx2 = hx1 + hlen * math.cos(angle)
    hy2 = hy1 + hlen * math.sin(angle)
    d.line([hx1, hy1, hx2, hy2], fill=color, width=sw, joint='curve')
    # round caps
    cap_r = sw / 2
    d.ellipse([hx2 - cap_r, hy2 - cap_r, hx2 + cap_r, hy2 + cap_r], fill=color)


def save(img, size, name):
    final = img.resize((size, size), Image.LANCZOS)
    path = os.path.join(OUT, name)
    final.save(path, 'PNG')
    print('  ->', name, final.size)


def make_app_icon(size, name, radius_frac=0.22, maskable=False):
    img = rounded_square(size, NAVY, 0 if maskable else radius_frac)
    if maskable:
        # safe zone: keep glyph within ~center 66% so it survives circular/squircle masks
        draw_magnifier(img, 0.46, 0.46, 0.20, 0.085, ORANGE, size)
    else:
        draw_magnifier(img, 0.44, 0.44, 0.24, 0.075, ORANGE, size)
    save(img, size, name)


def make_apple_touch_icon(size=180):
    # Apple applies its own rounding/mask; ship a full-bleed square, no transparency.
    img = rounded_square(size, NAVY, 0.0)
    draw_magnifier(img, 0.46, 0.46, 0.22, 0.08, ORANGE, size)
    save(img, size, 'apple-touch-icon.png')


def make_favicon_png(size, name):
    img = rounded_square(size, NAVY, 0.22)
    draw_magnifier(img, 0.44, 0.44, 0.26, 0.11, ORANGE, size)
    save(img, size, name)


def make_favicon_ico():
    sizes = [16, 32, 48]
    imgs = []
    for s in sizes:
        img = rounded_square(s, NAVY, 0.22)
        draw_magnifier(img, 0.44, 0.44, 0.26, 0.13, ORANGE, s)
        imgs.append(img.resize((s, s), Image.LANCZOS))
    path = os.path.join(OUT, 'favicon.ico')
    imgs[0].save(path, format='ICO', sizes=[(s, s) for s in sizes],
                 append_images=imgs[1:])
    print('  ->', 'favicon.ico', sizes)


def make_badge(size=96):
    # Monochrome white silhouette on transparent bg — Android tints this itself.
    img = Image.new('RGBA', (size * SS, size * SS), (0, 0, 0, 0))
    draw_magnifier(img, 0.5, 0.5, 0.30, 0.16, WHITE, size)
    save(img, size, f'badge-{size}.png')


def make_shortcut_nueva(size=192):
    img = rounded_square(size, NAVY, 0.22)
    d = ImageDraw.Draw(img)
    S = size * SS
    cx, cy = S * 0.5, S * 0.5
    arm = S * 0.26
    sw = int(S * 0.09)
    d.line([cx - arm, cy, cx + arm, cy], fill=ORANGE, width=sw, joint='curve')
    d.line([cx, cy - arm, cx, cy + arm], fill=ORANGE, width=sw, joint='curve')
    save(img, size, 'shortcut-nueva-192.png')


def make_shortcut_ofertas(size=192):
    img = rounded_square(size, NAVY, 0.22)
    d = ImageDraw.Draw(img)
    S = size * SS
    # tag shape
    import math
    w, h = S * 0.52, S * 0.36
    x0, y0 = S * 0.22, S * 0.32
    pts = [
        (x0, y0), (x0 + w * 0.62, y0), (x0 + w, y0 + h / 2),
        (x0 + w * 0.62, y0 + h), (x0, y0 + h),
    ]
    d.polygon(pts, fill=ORANGE)
    hole_r = S * 0.045
    hcx, hcy = x0 + w * 0.62 - hole_r * 1.6, y0 + h / 2
    d.ellipse([hcx - hole_r, hcy - hole_r, hcx + hole_r, hcy + hole_r], fill=NAVY)
    save(img, size, 'shortcut-ofertas-192.png')


def make_mask_icon_svg():
    # Safari pinned-tab mask icon: single-color glyph, no background.
    svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <circle cx="42" cy="42" r="26" fill="none" stroke="#000" stroke-width="9"/>
  <line x1="61" y1="61" x2="82" y2="82" stroke="#000" stroke-width="9" stroke-linecap="round"/>
</svg>
'''
    path = os.path.join(OUT, 'mask-icon.svg')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(svg)
    print('  ->', 'mask-icon.svg')


def make_app_icon_svg():
    # Refreshed source SVG (centered glyph) used as fallback vector icon.
    svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 192 192">
  <rect width="192" height="192" rx="42" fill="#0A0E1A"/>
  <circle cx="84" cy="84" r="42" fill="none" stroke="#FF6B35" stroke-width="15"/>
  <line x1="113" y1="113" x2="146" y2="146" stroke="#FF6B35" stroke-width="15" stroke-linecap="round"/>
</svg>
'''
    path = os.path.join(OUT, 'icon.svg')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(svg)
    print('  ->', 'icon.svg (updated)')


if __name__ == '__main__':
    print('Generando iconos en', os.path.abspath(OUT))

    for s in [48, 72, 96, 128, 144, 152, 192, 256, 384, 512]:
        make_app_icon(s, f'icon-{s}.png')

    make_app_icon(192, 'icon-maskable-192.png', maskable=True)
    make_app_icon(512, 'icon-maskable-512.png', maskable=True)

    make_apple_touch_icon(180)
    make_favicon_png(32, 'favicon-32.png')
    make_favicon_png(16, 'favicon-16.png')
    make_favicon_ico()
    make_badge(96)
    make_shortcut_nueva(192)
    make_shortcut_ofertas(192)
    make_mask_icon_svg()
    make_app_icon_svg()

    print('Listo.')
