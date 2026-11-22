"""
Respaldo de la base PostgreSQL (formato personalizado de pg_dump, comprimido).

    python scripts/respaldar_db.py

- Lee DATABASE_URL del .env.
- Guarda en backups/buscapieza_AAAAMMDD_HHMM.dump
- Borra respaldos con más de RESPALDOS_DIAS días (14 por defecto).
- El instalador lo programa a diario (tarea "BuscaPieza-Respaldo").

Restaurar:
    pg_restore -h localhost -U buscapieza -d buscapieza --clean --if-exists backups\\archivo.dump
"""
import glob
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime

from dotenv import load_dotenv
from sqlalchemy.engine import make_url

# La salida puede no ser una consola UTF-8 (tarea programada, redirección): no fallar por ✓ o tildes
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors='replace')
    except (AttributeError, ValueError):
        pass

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(RAIZ, '.env'))


def buscar_pg_dump():
    ruta = shutil.which('pg_dump')
    if ruta:
        return ruta
    candidatos = glob.glob(r'C:\Program Files\PostgreSQL\*\bin\pg_dump.exe')
    # La versión más alta (pg_dump debe ser >= que el servidor)
    candidatos.sort(key=lambda p: int(''.join(c for c in p.split('\\')[-3] if c.isdigit()) or 0))
    return candidatos[-1] if candidatos else None


def main():
    raw = os.environ.get('DATABASE_URL', '')
    if not raw:
        sys.exit('DATABASE_URL no está definida en .env')
    url = make_url(raw.replace('postgres://', 'postgresql://', 1))

    pg_dump = buscar_pg_dump()
    if not pg_dump:
        sys.exit('No se encontró pg_dump (instala PostgreSQL o añade su carpeta bin al PATH)')

    carpeta = os.path.join(RAIZ, 'backups')
    os.makedirs(carpeta, exist_ok=True)
    destino = os.path.join(carpeta, f"{url.database}_{datetime.now():%Y%m%d_%H%M}.dump")

    entorno = dict(os.environ, PGPASSWORD=url.password or '')
    cmd = [pg_dump, '-h', url.host or 'localhost', '-p', str(url.port or 5432),
           '-U', url.username, '-Fc', '-f', destino, url.database]
    r = subprocess.run(cmd, env=entorno, capture_output=True, text=True)
    if r.returncode != 0:
        if os.path.exists(destino):
            os.remove(destino)
        sys.exit(f'pg_dump falló: {r.stderr.strip()}')
    print(f'✓ Respaldo: {destino} ({os.path.getsize(destino) / 1024:.0f} KB)')

    dias = int(os.environ.get('RESPALDOS_DIAS', '14') or 14)
    limite = time.time() - dias * 86400
    for viejo in glob.glob(os.path.join(carpeta, '*.dump')):
        if os.path.getmtime(viejo) < limite:
            os.remove(viejo)
            print(f'  borrado respaldo antiguo: {os.path.basename(viejo)}')


if __name__ == '__main__':
    main()
