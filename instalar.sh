#!/bin/bash

echo "============================================"
echo "  BUSCAPIEZA RD - INSTALACIÓN"
echo "============================================"
echo ""

# Verificar Python
if ! command -v python3 &> /dev/null; then
    echo "❌ ERROR: Python 3 no está instalado"
    echo "Instálalo desde: https://www.python.org/downloads/"
    exit 1
fi

PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
echo "✓ Python detectado: $PYTHON_VERSION"

# Crear entorno virtual si no existe
if [ ! -d "venv" ]; then
    echo ""
    echo "Creando entorno virtual..."
    python3 -m venv venv
    echo "✓ Entorno virtual creado"
else
    echo "✓ Entorno virtual ya existe"
fi

# Activar entorno virtual
echo ""
echo "Activando entorno virtual..."
source venv/bin/activate

# Actualizar pip
echo ""
echo "Actualizando pip..."
pip install --upgrade pip --quiet

# Instalar dependencias
echo ""
echo "Instalando dependencias desde requirements.txt..."
pip install -r requirements.txt

echo ""
echo "✓ Dependencias instaladas correctamente"

# Crear carpetas necesarias
echo ""
echo "Creando carpetas necesarias..."
mkdir -p static/uploads
mkdir -p static/icons
mkdir -p logs
echo "✓ Carpetas creadas"

# Copiar .env.example a .env si no existe
if [ ! -f ".env" ]; then
    echo ""
    echo "Creando archivo .env desde .env.example..."
    cp .env.example .env
    echo "✓ Archivo .env creado"
    echo ""
    echo "⚠️  IMPORTANTE: Edita el archivo .env con tus credenciales"
    echo "   Genera una SECRET_KEY con:"
    echo "   python3 -c \"import secrets; print(secrets.token_hex(32))\""
else
    echo "✓ Archivo .env ya existe"
fi

# Crear archivo .gitkeep para carpetas vacías
touch static/uploads/.gitkeep
touch static/icons/.gitkeep
touch logs/.gitkeep

echo ""
echo "============================================"
echo "  ✓ INSTALACIÓN COMPLETADA"
echo "============================================"
echo ""
echo "Próximos pasos:"
echo ""
echo "1. Configura tu base de datos MySQL/MariaDB"
echo "   mysql -u root -p"
echo "   CREATE DATABASE buscapieza_db;"
echo ""
echo "2. Edita el archivo .env con tus credenciales"
echo "   nano .env"
echo ""
echo "3. Genera una SECRET_KEY segura:"
echo "   python3 -c \"import secrets; print(secrets.token_hex(32))\""
echo ""
echo "4. Inicia la aplicación:"
echo "   ./iniciar.sh"
echo ""
echo "============================================"
