"""
Genera el paquete de instalación (.zip) a partir del último commit.

    python scripts/crear_paquete.py

Resultado: dist/BuscatodoRD-AAAAMMDD-<commit>.zip
- Solo incluye archivos versionados en git (nunca .env, logs, respaldos ni fotos).
- Excluye lo marcado con export-ignore en .gitattributes (tests, notas de desarrollo...).
- Avisa si hay cambios sin commit (no entrarían en el paquete).
"""
import os
import subprocess
import sys
import zipfile
from datetime import datetime

# La salida puede no ser una consola UTF-8 (tarea programada, redirección): no fallar por ✓ o tildes
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors='replace')
    except (AttributeError, ValueError):
        pass

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROHIBIDOS = ('.env', 'firebase-credentials.json')


def git(*args):
    return subprocess.run(['git', *args], cwd=RAIZ, capture_output=True, text=True, check=True).stdout.strip()


def main():
    pendientes = [l for l in git('status', '--porcelain', '--untracked-files=no').splitlines() if l.strip()]
    if pendientes:
        print('⚠️  Hay cambios sin commit que NO entrarán en el paquete:')
        for l in pendientes[:15]:
            print('   ', l)
        if input('¿Continuar? [s/N]: ').strip().lower() not in ('s', 'si', 'sí', 'y'):
            sys.exit(1)

    commit = git('rev-parse', '--short', 'HEAD')
    os.makedirs(os.path.join(RAIZ, 'dist'), exist_ok=True)
    destino = os.path.join(RAIZ, 'dist', f'BuscatodoRD-{datetime.now():%Y%m%d}-{commit}.zip')
    git('archive', '--format=zip', '--prefix=BuscatodoRD/', '-o', destino, 'HEAD')

    with zipfile.ZipFile(destino) as z:
        nombres = z.namelist()
    malos = [n for n in nombres if os.path.basename(n.rstrip('/')) in PROHIBIDOS]
    if malos:
        os.remove(destino)
        sys.exit(f'❌ El paquete contenía archivos sensibles {malos}; se eliminó.')
    for imprescindible in ('BuscatodoRD/INSTALAR-SERVIDOR.bat', 'BuscatodoRD/servidor.py',
                           'BuscatodoRD/instalador/instalar-servidor.ps1', 'BuscatodoRD/requirements.txt'):
        if imprescindible not in nombres:
            os.remove(destino)
            sys.exit(f'❌ Falta {imprescindible} en el paquete (¿está commiteado?)')

    print(f'✓ Paquete: {destino}')
    print(f'  {len(nombres)} archivos · {os.path.getsize(destino) / 1024:.0f} KB · commit {commit}')


if __name__ == '__main__':
    main()
