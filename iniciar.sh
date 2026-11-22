#!/bin/bash

echo "============================================"
echo "  BUSCAPIEZA RD - INICIANDO SERVIDOR"
echo "============================================"
echo ""

# Verificar que existe el entorno virtual
if [ ! -d "venv" ]; then
    echo "❌ ERROR: Entorno virtual no encontrado"
    echo "Ejecuta primero: ./instalar.sh"
    exit 1
fi

# Verificar que existe .env
if [ ! -f ".env" ]; then
    echo "❌ ERROR: Archivo .env no encontrado"
    echo "Copia .env.example a .env y configura tus credenciales:"
    echo "   cp .env.example .env"
    echo "   nano .env"
    exit 1
fi

# Activar entorno virtual
echo "Activando entorno virtual..."
source venv/bin/activate

# Aplicar migraciones pendientes y datos iniciales (idempotente)
echo "Preparando base de datos PostgreSQL..."
if ! flask --app "app:create_app" db upgrade; then
    echo "❌ No se pudo preparar la base de datos."
    echo "   - ¿PostgreSQL está en ejecución?  sudo systemctl status postgresql"
    echo "   - Revisa DATABASE_URL en .env"
    echo "   - Si la base no existe: python3 scripts/crear_db_postgres.py"
    exit 1
fi
flask --app "app:create_app" seed
echo ""

# Iniciar aplicación
echo "Iniciando BuscaPieza RD..."
echo ""

python3 app.py
