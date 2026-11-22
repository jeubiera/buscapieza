# Guía de Deployment - BuscatodoRD

Esta guía cubre el despliegue de BuscatodoRD en ambiente de producción.

## Tabla de Contenidos

1. [Prerequisitos](#prerequisitos)
2. [Despliegue con Docker](#despliegue-con-docker)
3. [Despliegue Manual (Linux/Ubuntu)](#despliegue-manual-linuxubuntu)
4. [Configuración de Nginx](#configuración-de-nginx)
5. [SSL/HTTPS con Let's Encrypt](#sslhttps-con-lets-encrypt)
6. [Variables de Entorno de Producción](#variables-de-entorno-de-producción)
7. [Monitoreo y Mantenimiento](#monitoreo-y-mantenimiento)
8. [Backups](#backups)
9. [Troubleshooting](#troubleshooting)

---

## Prerequisitos

### Hardware Recomendado

**Mínimo:**
- 1 CPU core
- 2GB RAM
- 20GB almacenamiento
- Conexión a internet estable

**Recomendado para producción:**
- 2+ CPU cores
- 4GB+ RAM
- 50GB+ almacenamiento SSD
- 100 Mbps conexión

### Software

- Ubuntu 20.04/22.04 LTS o CentOS 7+
- Docker & Docker Compose (para deployment con contenedores)
- Python 3.8+
- PostgreSQL 14+
- Nginx (como reverse proxy)
- Certbot (para SSL)

---

## Despliegue con Docker

El método más rápido y recomendado.

### 1. Clonar el Repositorio

```bash
git clone https://github.com/tu-usuario/buscapieza.git
cd buscapieza
```

### 2. Configurar Variables de Entorno

```bash
cp .env.example .env
nano .env
```

**Variables críticas en producción:**

```bash
# OBLIGATORIO: Clave secreta fuerte
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")

# Base de datos (Docker Compose la crea automáticamente con esta contraseña;
# DATABASE_URL del contenedor web se arma sola a partir de ella)
POSTGRES_PASSWORD=PASSWORD_SEGURO

# URL pública (https) y admin inicial
APP_URL=https://tu-dominio.com
ADMIN_EMAIL=admin@tu-dominio.com
ADMIN_PASSWORD=UNA_CLAVE_FUERTE

# Entorno
FLASK_ENV=production
FLASK_DEBUG=False

# Cloudinary (RECOMENDADO para producción)
CLOUDINARY_CLOUD_NAME=tu-cloud-name
CLOUDINARY_API_KEY=tu-api-key
CLOUDINARY_API_SECRET=tu-api-secret

# WhatsApp Business
GREEN_API_INSTANCE=tu-instance-id
GREEN_API_TOKEN=tu-token

# Firebase
FIREBASE_SERVER_KEY=tu-firebase-server-key

# Broker
BROKER_WHATSAPP=18091234567
BROKER_NOMBRE=BuscatodoRD
```

### 3. Iniciar con Docker Compose

```bash
# Build y start en background
docker-compose up -d

# Ver logs
docker-compose logs -f

# Verificar status
docker-compose ps
```

### 4. Verificar Instalación

```bash
# La aplicación debe estar corriendo en http://localhost:5050
curl http://localhost:5050
```

### 5. Configurar Nginx (opcional pero recomendado)

Ver sección [Configuración de Nginx](#configuración-de-nginx) más abajo.

---

## Despliegue Manual (Linux/Ubuntu)

Para servidores sin Docker.

### 1. Actualizar Sistema

```bash
sudo apt update && sudo apt upgrade -y
```

### 2. Instalar Dependencias

```bash
# Python 3 y pip
sudo apt install python3 python3-pip python3-venv -y

# PostgreSQL
sudo apt install postgresql postgresql-contrib -y

# Nginx
sudo apt install nginx -y

# Supervisor (para mantener app corriendo)
sudo apt install supervisor -y

# Certbot (SSL)
sudo apt install certbot python3-certbot-nginx -y
```

### 3. Configurar PostgreSQL

```bash
sudo -u postgres psql
```

```sql
CREATE ROLE buscapieza WITH LOGIN PASSWORD 'PASSWORD_SEGURO';
CREATE DATABASE buscapieza OWNER buscapieza ENCODING 'UTF8' TEMPLATE template0;
\q
```

En `.env`: `DATABASE_URL=postgresql+psycopg2://buscapieza:PASSWORD_SEGURO@localhost:5432/buscapieza`

(Alternativa: con `DATABASE_URL` ya en `.env`, `python3 scripts/crear_db_postgres.py` hace lo mismo.)

Después, desde la carpeta de la app:

```bash
flask --app "app:create_app" db upgrade
flask --app "app:create_app" seed
```

### 4. Configurar Aplicación

```bash
# Crear usuario para la app
sudo useradd -m -s /bin/bash buscapieza

# Cambiar a directorio del usuario
sudo su - buscapieza

# Clonar repo
git clone https://github.com/tu-usuario/buscapieza.git
cd buscapieza

# Crear virtual environment
python3 -m venv venv
source venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt

# Configurar .env
cp .env.example .env
nano .env
# (Configurar todas las variables)

# Crear carpetas necesarias
mkdir -p static/uploads static/icons logs
```

### 5. Configurar Gunicorn

```bash
# Crear archivo de configuración
nano gunicorn_config.py
```

```python
# gunicorn_config.py
import multiprocessing

bind = "127.0.0.1:8000"
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "sync"
worker_connections = 1000
timeout = 120
keepalive = 5

# Logging
accesslog = "logs/gunicorn_access.log"
errorlog = "logs/gunicorn_error.log"
loglevel = "info"

# Process naming
proc_name = "buscapieza"

# Server mechanics
daemon = False
pidfile = "gunicorn.pid"
```

### 6. Configurar Supervisor

```bash
# Salir del usuario buscapieza
exit

# Crear configuración de supervisor
sudo nano /etc/supervisor/conf.d/buscapieza.conf
```

```ini
[program:buscapieza]
directory=/home/buscapieza/buscapieza
command=/home/buscapieza/buscapieza/venv/bin/gunicorn -c gunicorn_config.py "app:create_app('production')"
user=buscapieza
autostart=true
autorestart=true
stopasgroup=true
killasgroup=true
stderr_logfile=/var/log/buscapieza/err.log
stdout_logfile=/var/log/buscapieza/out.log
```

```bash
# Crear directorio de logs
sudo mkdir -p /var/log/buscapieza
sudo chown buscapieza:buscapieza /var/log/buscapieza

# Recargar supervisor
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start buscapieza

# Verificar status
sudo supervisorctl status buscapieza
```

---

## Configuración de Nginx

### 1. Crear Configuración de Sitio

```bash
sudo nano /etc/nginx/sites-available/buscapieza
```

```nginx
# Redirigir HTTP a HTTPS
server {
    listen 80;
    server_name buscapieza.do www.buscapieza.do;

    return 301 https://$server_name$request_uri;
}

# HTTPS
server {
    listen 443 ssl http2;
    server_name buscapieza.do www.buscapieza.do;

    # SSL certificates (Let's Encrypt las agregará automáticamente)
    # ssl_certificate /etc/letsencrypt/live/buscapieza.do/fullchain.pem;
    # ssl_certificate_key /etc/letsencrypt/live/buscapieza.do/privkey.pem;

    # SSL configuration
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers on;
    ssl_ciphers ECDHE-RSA-AES256-GCM-SHA512:DHE-RSA-AES256-GCM-SHA512:ECDHE-RSA-AES256-GCM-SHA384:DHE-RSA-AES256-GCM-SHA384;

    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;

    # Max upload size (para fotos)
    client_max_body_size 20M;

    # Logs
    access_log /var/log/nginx/buscapieza_access.log;
    error_log /var/log/nginx/buscapieza_error.log;

    # Static files
    location /static {
        alias /home/buscapieza/buscapieza/static;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # Proxy to Gunicorn
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_redirect off;

        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
}
```

### 2. Habilitar Sitio

```bash
# Crear enlace simbólico
sudo ln -s /etc/nginx/sites-available/buscapieza /etc/nginx/sites-enabled/

# Test configuración
sudo nginx -t

# Reiniciar nginx
sudo systemctl restart nginx
```

---

## SSL/HTTPS con Let's Encrypt

```bash
# Obtener certificado
sudo certbot --nginx -d buscapieza.do -d www.buscapieza.do

# Certbot configurará automáticamente nginx
# Seguir las instrucciones en pantalla

# Test auto-renewal
sudo certbot renew --dry-run

# Los certificados se renuevan automáticamente
```

---

## Variables de Entorno de Producción

### Checklist de Seguridad

- [ ] `SECRET_KEY` generada aleatoriamente (32+ caracteres)
- [ ] `FLASK_DEBUG=False`
- [ ] `FLASK_ENV=production`
- [ ] Contraseña fuerte para el usuario de PostgreSQL
- [ ] Cloudinary configurado (no guardar imágenes localmente)
- [ ] Credenciales de Green API y Firebase configuradas
- [ ] Backup automático configurado
- [ ] Logs rotando correctamente

---

## Monitoreo y Mantenimiento

### Logs

```bash
# Logs de la aplicación
tail -f /home/buscapieza/buscapieza/logs/app.log

# Logs de Gunicorn
tail -f /home/buscapieza/buscapieza/logs/gunicorn_error.log

# Logs de Nginx
tail -f /var/log/nginx/buscapieza_error.log

# Logs de Supervisor
tail -f /var/log/buscapieza/err.log
```

### Comandos Útiles

```bash
# Reiniciar aplicación
sudo supervisorctl restart buscapieza

# Ver status
sudo supervisorctl status

# Reiniciar Nginx
sudo systemctl restart nginx

# Ver uso de recursos
htop
```

### Monitoreo Automático (opcional)

Instalar herramientas de monitoreo:

```bash
# Netdata (monitoreo en tiempo real)
bash <(curl -Ss https://my-netdata.io/kickstart.sh)

# Accesible en http://tu-servidor:19999
```

---

## Backups

### Script de Backup Automático

```bash
# Crear script
sudo nano /usr/local/bin/backup-buscapieza.sh
```

```bash
#!/bin/bash

# Configuración
BACKUP_DIR="/backups/buscapieza"
DATE=$(date +%Y%m%d_%H%M%S)
DB_NAME="buscapieza"
DB_USER="buscapieza"
export PGPASSWORD="PASSWORD_SEGURO"

# Crear directorio de backups
mkdir -p $BACKUP_DIR

# Backup de base de datos
pg_dump -h localhost -U $DB_USER -Fc $DB_NAME > $BACKUP_DIR/db_$DATE.dump

# Backup de archivos subidos
tar -czf $BACKUP_DIR/uploads_$DATE.tar.gz /home/buscapieza/buscapieza/static/uploads

# Eliminar backups antiguos (más de 30 días)
find $BACKUP_DIR -type f -mtime +30 -delete

echo "Backup completado: $DATE"
```

```bash
# Dar permisos
sudo chmod +x /usr/local/bin/backup-buscapieza.sh

# Agregar a crontab (backup diario a las 2 AM)
sudo crontab -e

# Agregar línea:
0 2 * * * /usr/local/bin/backup-buscapieza.sh >> /var/log/backups.log 2>&1
```

### Restaurar desde Backup

```bash
# Restaurar base de datos
pg_restore -h localhost -U buscapieza -d buscapieza --clean --if-exists /backups/buscapieza/db_20240101_020000.dump

# Restaurar archivos
tar -xzf /backups/buscapieza/uploads_20240101_020000.tar.gz -C /
```

---

## Troubleshooting

### Aplicación no arranca

```bash
# Ver logs de error
sudo supervisorctl tail -f buscapieza stderr

# Verificar que PostgreSQL esté corriendo
sudo systemctl status postgresql

# Verificar que el .env esté configurado
sudo -u buscapieza cat /home/buscapieza/buscapieza/.env
```

### Error 502 Bad Gateway

```bash
# Verificar que Gunicorn esté corriendo
sudo supervisorctl status buscapieza

# Verificar conexión a PostgreSQL
psql -h localhost -U buscapieza -d buscapieza -c "SELECT 1"
```

### Imágenes no cargan

- Verificar permisos de `static/uploads/`
- Verificar que Cloudinary esté configurado
- Revisar logs: `tail -f logs/app.log`

### Notificaciones WhatsApp no funcionan

- Verificar credenciales de Green API en `.env`
- Verificar límite de mensajes (300/día en plan gratuito)
- Revisar logs: `tail -f logs/notifications.log`

---

## Actualizaciones

### Actualizar la Aplicación

```bash
# Cambiar a usuario buscapieza
sudo su - buscapieza
cd buscapieza

# Pull últimos cambios
git pull origin main

# Activar virtual environment
source venv/bin/activate

# Actualizar dependencias
pip install -r requirements.txt --upgrade

# Aplicar migraciones de BD
flask db upgrade

# Salir
exit

# Reiniciar aplicación
sudo supervisorctl restart buscapieza
```

---

## Soporte

Para problemas de deployment:
- Email: soporte@buscatodo.com.do
- Documentación: GitHub Wiki
- Issues: GitHub Issues

---

**BuscatodoRD - Deployment Guide v1.0**
