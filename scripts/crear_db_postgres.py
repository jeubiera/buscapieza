"""
Crea el usuario y la base de datos de PostgreSQL que indica DATABASE_URL (.env).

Uso (una sola vez):
    python scripts/crear_db_postgres.py

Pide la contraseña del superusuario "postgres" (la que pusiste al instalar PostgreSQL),
no la guarda en ningún sitio. Es idempotente: si el usuario o la base ya existen, no
los toca (salvo actualizar la contraseña del usuario para que coincida con el .env).

Después:
    flask --app "app:create_app" db upgrade
    flask --app "app:create_app" seed
"""
import getpass
import os
import sys

from dotenv import load_dotenv
from sqlalchemy.engine import make_url

try:
    import psycopg2
    from psycopg2 import sql
except ImportError:
    sys.exit("Falta psycopg2: pip install -r requirements.txt")

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(RAIZ, '.env'))


def main():
    raw = os.environ.get('DATABASE_URL', '')
    if not raw:
        sys.exit("DATABASE_URL no está definida en .env")
    if raw.startswith('postgres://'):
        raw = 'postgresql://' + raw[len('postgres://'):]
    url = make_url(raw)
    if not url.drivername.startswith('postgresql'):
        sys.exit(f"DATABASE_URL no es de PostgreSQL ({url.drivername})")

    usuario, clave, base = url.username, url.password, url.database
    host, puerto = url.host or 'localhost', url.port or 5432
    if not (usuario and clave and base):
        sys.exit("DATABASE_URL debe incluir usuario, contraseña y nombre de la base")

    print(f"Servidor: {host}:{puerto}  ·  usuario app: {usuario}  ·  base: {base}")
    admin = input("Superusuario de PostgreSQL [postgres]: ").strip() or 'postgres'
    admin_clave = getpass.getpass(f"Contraseña de '{admin}': ")

    try:
        conn = psycopg2.connect(host=host, port=puerto, user=admin, password=admin_clave, dbname='postgres')
    except psycopg2.OperationalError as e:
        sys.exit(f"No se pudo conectar como '{admin}': {e}")
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (usuario,))
    if cur.fetchone():
        cur.execute(sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD %s").format(sql.Identifier(usuario)), (clave,))
        print(f"✓ Usuario '{usuario}' ya existía (contraseña sincronizada con .env)")
    else:
        cur.execute(sql.SQL("CREATE ROLE {} WITH LOGIN PASSWORD %s").format(sql.Identifier(usuario)), (clave,))
        print(f"✓ Usuario '{usuario}' creado")

    bases = [base]
    test_raw = os.environ.get('TEST_DATABASE_URL', '')
    if test_raw:
        test_url = make_url(test_raw.replace('postgres://', 'postgresql://', 1))
        if test_url.database and test_url.database != base:
            bases.append(test_url.database)

    for nombre in bases:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (nombre,))
        if cur.fetchone():
            print(f"✓ Base '{nombre}' ya existía")
        else:
            cur.execute(sql.SQL("CREATE DATABASE {} OWNER {} ENCODING 'UTF8' TEMPLATE template0").format(
                sql.Identifier(nombre), sql.Identifier(usuario)))
            print(f"✓ Base '{nombre}' creada (UTF-8, dueño {usuario})")

    cur.close()
    conn.close()
    print("\nListo. Ahora ejecuta:")
    print('  flask --app "app:create_app" db upgrade')
    print('  flask --app "app:create_app" seed')


if __name__ == '__main__':
    main()
