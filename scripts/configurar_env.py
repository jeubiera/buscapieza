"""
Genera el archivo .env de producción haciendo preguntas.

    python scripts/configurar_env.py                 # asistente
    python scripts/configurar_env.py --borrar-admin-password

- SECRET_KEY y la contraseña del usuario de PostgreSQL se generan al azar.
- Las contraseñas se escriben ocultas y nunca se muestran.
- Si ya existe un .env, se ofrece conservarlo (no se pisa sin preguntar).
- --borrar-admin-password: vacía ADMIN_PASSWORD una vez creado el admin
  (solo se necesita para el primer arranque).
"""
import getpass
import os
import re
import secrets
import sys
from urllib.parse import quote

# La salida puede no ser una consola UTF-8 (tarea programada, redirección): no fallar por ✓ o tildes
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors='replace')
    except (AttributeError, ValueError):
        pass

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUTA_ENV = os.path.join(RAIZ, '.env')

DOMINIO_RE = re.compile(r'^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$')
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _q(valor: str) -> str:
    """Entre comillas dobles con escapes (python-dotenv): admite espacios, #, comillas y barras."""
    if not valor:
        return ''
    return '"' + valor.replace('\\', '\\\\').replace('"', '\\"') + '"'


def generar_env(d: dict) -> str:
    """Construye el contenido del .env a partir de las respuestas (función pura, testeable)."""
    db_url = (f"postgresql+psycopg2://{quote(d['db_usuario'], safe='')}:{quote(d['db_clave'], safe='')}"
              f"@{d.get('db_host', 'localhost')}:{d.get('db_puerto', 5432)}/{d['db_nombre']}")
    lineas = [
        '# Generado por scripts/configurar_env.py — NO subir a git',
        '',
        '# --- Seguridad ---',
        f"SECRET_KEY={d['secret_key']}",
        'FLASK_ENV=production',
        'FLASK_DEBUG=False',
        'SESSION_COOKIE_SECURE=True',
        '',
        '# --- Servidor (solo local: el público entra por el túnel de Cloudflare) ---',
        'FLASK_HOST=127.0.0.1',
        f"FLASK_PORT={d.get('puerto_app', 5050)}",
        f"APP_URL=https://{d['dominio']}",
        '',
        '# --- Base de datos PostgreSQL ---',
        f'DATABASE_URL={db_url}',
        '',
        '# --- Admin inicial (ADMIN_PASSWORD se vacía tras el primer arranque) ---',
        f"ADMIN_EMAIL={d['admin_email']}",
        f"ADMIN_PASSWORD={_q(d.get('admin_password', ''))}",
        '',
        '# --- Broker ---',
        f"BROKER_WHATSAPP={d.get('broker_whatsapp', '')}",
        f"BROKER_NOMBRE={_q(d.get('broker_nombre', 'BuscatodoRD'))}",
        '',
        '# --- Integraciones (también se pueden configurar en /admin/configuracion) ---',
        f"GREEN_API_INSTANCE={d.get('green_instance', '')}",
        f"GREEN_API_TOKEN={_q(d.get('green_token', ''))}",
        f"CLOUDINARY_CLOUD_NAME={d.get('cloud_name', '')}",
        f"CLOUDINARY_API_KEY={d.get('cloud_key', '')}",
        f"CLOUDINARY_API_SECRET={_q(d.get('cloud_secret', ''))}",
        'FIREBASE_CREDENTIALS_PATH=',
        'FIREBASE_WEB_CONFIG=',
        'FIREBASE_VAPID_PUBLIC=',
        '',
        '# --- Respaldos ---',
        f"RESPALDOS_DIAS={d.get('respaldos_dias', 14)}",
        '',
    ]
    return '\n'.join(lineas)


def _preguntar(texto, defecto='', validar=None, error='Valor no válido'):
    while True:
        sufijo = f' [{defecto}]' if defecto else ''
        valor = input(f'{texto}{sufijo}: ').strip() or defecto
        if not validar or validar(valor):
            return valor
        print(f'  ✗ {error}')


def _preguntar_clave(texto, minimo=8, opcional=False):
    while True:
        v1 = getpass.getpass(f'{texto}{" (Enter para omitir)" if opcional else ""}: ')
        if opcional and not v1:
            return ''
        if len(v1) < minimo:
            print(f'  ✗ Mínimo {minimo} caracteres')
            continue
        if getpass.getpass('  Repítela: ') != v1:
            print('  ✗ No coinciden')
            continue
        return v1


def asistente():
    print('=' * 60)
    print('  Configuración de BuscatodoRD (producción)')
    print('=' * 60)

    if os.path.exists(RUTA_ENV):
        r = input('Ya existe un .env. ¿Conservarlo? [S/n]: ').strip().lower()
        if r in ('', 's', 'si', 'sí', 'y', 'yes'):
            print('✓ Se conserva el .env actual')
            return 0
        os.replace(RUTA_ENV, RUTA_ENV + '.anterior')
        print('  (el anterior se guardó como .env.anterior)')

    print('\n1) Dominio público (el hostname que publicará el túnel de Cloudflare)')
    dominio = _preguntar('   Dominio, p. ej. buscatodo.com.do o app.midominio.com',
                         validar=lambda v: bool(DOMINIO_RE.match(v.lower())),
                         error='Escribe solo el dominio, sin https:// ni barras').lower()

    print('\n2) Administrador')
    admin_email = _preguntar('   Email del admin', f'admin@{dominio}',
                             validar=lambda v: bool(EMAIL_RE.match(v)), error='Email no válido').lower()
    admin_password = _preguntar_clave('   Contraseña del admin')

    print('\n3) Broker')
    broker_whatsapp = _preguntar('   WhatsApp del broker (con código de país, ej. 18095551234)',
                                 validar=lambda v: v == '' or (v.isdigit() and 10 <= len(v) <= 15),
                                 error='Solo dígitos, 10 a 15')
    broker_nombre = _preguntar('   Nombre del negocio', 'BuscatodoRD')

    print('\n4) Base de datos PostgreSQL (el usuario y la base se crean en el paso siguiente)')
    db_puerto = int(_preguntar('   Puerto de PostgreSQL', '5432', validar=str.isdigit))
    db_nombre = _preguntar('   Nombre de la base', 'buscatodo', validar=lambda v: re.match(r'^[a-z_][a-z0-9_]*$', v))
    db_usuario = _preguntar('   Usuario de la app', 'buscatodo', validar=lambda v: re.match(r'^[a-z_][a-z0-9_]*$', v))

    print('\n5) Integraciones opcionales (Enter para omitir; se pueden poner luego en el panel admin)')
    green_instance = _preguntar('   Green API — Instance ID')
    green_token = getpass.getpass('   Green API — Token (oculto, Enter para omitir): ').strip() if green_instance else ''
    cloud_name = _preguntar('   Cloudinary — Cloud name')
    cloud_key = _preguntar('   Cloudinary — API key') if cloud_name else ''
    cloud_secret = getpass.getpass('   Cloudinary — API secret (oculto): ').strip() if cloud_name else ''

    contenido = generar_env({
        'secret_key': secrets.token_hex(32),
        'dominio': dominio,
        'admin_email': admin_email, 'admin_password': admin_password,
        'broker_whatsapp': broker_whatsapp, 'broker_nombre': broker_nombre,
        'db_puerto': db_puerto, 'db_nombre': db_nombre, 'db_usuario': db_usuario,
        'db_clave': secrets.token_urlsafe(24),
        'green_instance': green_instance, 'green_token': green_token,
        'cloud_name': cloud_name, 'cloud_key': cloud_key, 'cloud_secret': cloud_secret,
    })
    with open(RUTA_ENV, 'w', encoding='utf-8', newline='\n') as f:
        f.write(contenido)
    print(f'\n✓ .env creado en {RUTA_ENV}')
    return 0


def borrar_admin_password():
    if not os.path.exists(RUTA_ENV):
        return 0
    with open(RUTA_ENV, encoding='utf-8') as f:
        lineas = f.read().splitlines()
    nuevas = ['ADMIN_PASSWORD=' if l.startswith('ADMIN_PASSWORD=') else l for l in lineas]
    if nuevas != lineas:
        with open(RUTA_ENV, 'w', encoding='utf-8', newline='\n') as f:
            f.write('\n'.join(nuevas) + '\n')
        print('✓ ADMIN_PASSWORD eliminada del .env (el admin ya existe en la base)')
    return 0


if __name__ == '__main__':
    if '--borrar-admin-password' in sys.argv:
        sys.exit(borrar_admin_password())
    try:
        sys.exit(asistente())
    except (KeyboardInterrupt, EOFError):
        print('\nCancelado.')
        sys.exit(1)
