"""
Mantiene servidor.py en ejecución: si el proceso termina (error, BD caída al arrancar...),
lo vuelve a lanzar con una espera creciente (5 s → máx. 60 s).

Lo ejecuta la tarea programada "BuscatodoRD-Servidor" al iniciar Windows.
Registra los reinicios en logs/supervisor.log.
"""
import os
import subprocess
import sys
import time
from datetime import datetime

# La salida puede no ser una consola UTF-8 (tarea programada, redirección): no fallar por ✓ o tildes
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors='replace')
    except (AttributeError, ValueError):
        pass

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(RAIZ, 'logs', 'supervisor.log')


def registrar(msg):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(f'[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n')


def main():
    espera = 5
    registrar('Supervisor iniciado')
    while True:
        inicio = time.time()
        with open(os.path.join(RAIZ, 'logs', 'servidor-consola.log'), 'a', encoding='utf-8') as salida:
            proc = subprocess.run([sys.executable, os.path.join(RAIZ, 'servidor.py')], cwd=RAIZ,
                                  stdout=salida, stderr=subprocess.STDOUT)
        duracion = time.time() - inicio
        # Si funcionó un buen rato, el fallo es nuevo: reiniciar rápido
        espera = 5 if duracion > 300 else min(espera * 2, 60)
        registrar(f'servidor.py terminó (código {proc.returncode}, {duracion:.0f}s). Reinicio en {espera}s')
        time.sleep(espera)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        registrar('Supervisor detenido')
