# ============================================
# BUSCAPIEZA RD - DOCKERFILE
# ============================================

# Imagen base de Python
FROM python:3.11-slim

# Información del mantenedor
LABEL maintainer="BuscaPieza RD <soporte@buscapieza.do>"
LABEL description="Plataforma de intermediación para búsqueda de repuestos y piezas"

# Variables de entorno para Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Directorio de trabajo
WORKDIR /app

# Instalar dependencias del sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    default-libmysqlclient-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Copiar archivos de dependencias
COPY requirements.txt .

# Instalar dependencias de Python
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Copiar código de la aplicación
COPY . .

# Crear carpetas necesarias
RUN mkdir -p static/uploads static/icons logs && \
    chmod -R 755 static logs

# Exponer puerto
EXPOSE 5050

# Usuario no-root para seguridad
RUN useradd -m -u 1000 buscapieza && \
    chown -R buscapieza:buscapieza /app
USER buscapieza

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5050/').read()" || exit 1

# Comando de inicio (usa gunicorn en producción)
CMD ["gunicorn", "--bind", "0.0.0.0:5050", "--workers", "4", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-", "app:create_app('production')"]
