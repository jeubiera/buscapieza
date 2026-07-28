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

# Verificar que MySQL está corriendo
echo "Verificando conexión a base de datos..."
echo ""

# Iniciar aplicación
echo "Iniciando BuscaPieza RD..."
echo ""

python3 app.py
