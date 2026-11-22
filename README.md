# BuscaPieza RD

**Plataforma de intermediación para búsqueda y cotización de repuestos y piezas en República Dominicana**

BuscaPieza RD es una Progressive Web App (PWA) que conecta clientes que buscan repuestos o piezas con proveedores que las venden, actuando como broker intermediario que protege la privacidad de ambas partes.

## Características Principales

- **PWA (Progressive Web App)**: Instalable en móviles, tablets y desktop
- **Modo Offline**: Funcionalidad básica sin conexión a internet
- **Notificaciones Multi-canal**: WhatsApp, Push Notifications
- **Gestión de Imágenes**: Almacenamiento en la nube con Cloudinary
- **Sistema de Roles**: Cliente, Proveedor, Admin (Broker)
- **Cobertura Nacional**: 31 provincias de República Dominicana
- **10 Categorías**: Desde repuestos automotrices hasta equipos médicos

## Tecnologías

**Backend:**
- Flask 3.0.3 (Python)
- SQLAlchemy (ORM)
- PostgreSQL
- Flask-Login (Autenticación)
- Flask-Migrate (Migraciones)

**Integraciones:**
- Cloudinary (Almacenamiento de imágenes)
- Green API (WhatsApp Business - 300 msg/día gratis)
- Firebase Cloud Messaging (Push notifications)

**Frontend:**
- HTML5 + CSS3 + JavaScript vanilla
- Service Worker (Cache, Offline, Push)
- Responsive Design

## Requisitos Previos

- **Python 3.8+**
- **PostgreSQL 14+** (en Windows: instalador oficial de https://www.postgresql.org/download/windows/)
- **Git** (opcional, para clonar el repositorio)

## Instalación

### 1. Clonar o Descargar el Proyecto

```bash
# HTTPS (requiere Personal Access Token)
git clone https://github.com/jeubiera/buscapieza.git

# SSH (recomendado - ver configuración abajo)
git clone git@github.com:jeubiera/buscapieza.git

cd buscapieza
```

### 2. Configurar Base de Datos (PostgreSQL)

1. Instala PostgreSQL y apunta la contraseña del superusuario `postgres`.
2. En `.env` define la conexión que usará la app (el usuario y la base se crean en el paso 3):
   ```env
   DATABASE_URL=postgresql+psycopg2://buscapieza:una-clave-segura@localhost:5432/buscapieza
   ```
3. Crea el usuario y la base (te pide la contraseña de `postgres`, no la guarda):
   ```bash
   python scripts/crear_db_postgres.py
   ```
4. Crea las tablas y los datos iniciales (`iniciar.bat` / `iniciar.sh` ya lo hacen al arrancar):
   ```bash
   flask --app "app:create_app" db upgrade
   flask --app "app:create_app" seed
   ```

### 3. Configurar Variables de Entorno

**Windows:**

```batch
instalar.bat
```

**Linux/Mac:**

```bash
chmod +x instalar.sh
./instalar.sh
```

**Configuración Manual:**

```bash
# Crear entorno virtual
python -m venv venv

# Activar entorno virtual
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt

# Copiar archivo de variables de entorno
cp .env.example .env
```

### 4. Configurar Credenciales

Edita el archivo `.env` con tus credenciales:

```bash
# Obligatorio
SECRET_KEY=genera_una_clave_aleatoria_aqui

# Base de datos
DATABASE_URL=postgresql+psycopg2://buscapieza:tu_password@localhost:5432/buscapieza

# Opcionales (pero recomendadas)
CLOUDINARY_CLOUD_NAME=tu-cloud-name
CLOUDINARY_API_KEY=tu-api-key
CLOUDINARY_API_SECRET=tu-api-secret

GREEN_API_INSTANCE=tu-instance-id
GREEN_API_TOKEN=tu-token

FIREBASE_SERVER_KEY=tu-firebase-server-key

BROKER_WHATSAPP=18091234567
BROKER_NOMBRE=BuscaPieza RD
```

**Generar SECRET_KEY segura:**

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 5. Crear Carpetas Necesarias

```bash
mkdir -p static/uploads static/icons
```

## Uso

### Desarrollo Local

**Windows:**

```batch
iniciar.bat
```

**Linux/Mac:**

```bash
chmod +x iniciar.sh
./iniciar.sh
```

**Manual:**

```bash
# Activar entorno virtual
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# Iniciar servidor
python app.py
```

La aplicación estará disponible en: `http://localhost:5050`

### Credenciales por Defecto

Al iniciar por primera vez (si no existe ningún admin) se crea un administrador con:

- **Email:** el valor de `ADMIN_EMAIL` (por defecto `admin@buscapieza.do`)
- **Password:** el valor de `ADMIN_PASSWORD`. Si lo dejas vacío, se genera una contraseña
  aleatoria y se muestra **una sola vez** en la consola al arrancar.

Puedes cambiarla después en **/auth/cambiar-password** (icono 🔑 del menú).
Si la pierdes, pon una nueva desde la terminal (se escribe oculta):

```bash
flask --app "app:create_app" admin-password
```
Si tu instalación es anterior y todavía usa `Admin2024!`, la app te pedirá cambiarla al entrar.

### Migraciones de base de datos

```bash
# Base de datos nueva
flask --app "app:create_app" db upgrade
flask --app "app:create_app" seed

# Tras cambiar models.py, genera y aplica una migración nueva:
flask --app "app:create_app" db migrate -m "describe el cambio"
flask --app "app:create_app" db upgrade
```

## Estructura del Proyecto

```
buscapieza/
│
├── app.py                  # Punto de entrada (Factory Pattern)
├── config.py               # Configuración (dev, prod, test)
├── models.py               # Modelos SQLAlchemy
├── extensions.py           # Instancias de db y login_manager
├── requirements.txt        # Dependencias Python
│
├── .env                    # Variables de entorno (NO subir a git)
├── .env.example            # Plantilla de variables
├── .gitignore              # Archivos excluidos de git
│
├── blueprints/             # Módulos de rutas
│   ├── main.py             # Landing, manifest, service worker
│   ├── auth.py             # Login, registro, logout
│   ├── solicitudes.py      # CRUD solicitudes de clientes
│   ├── ofertas.py          # Panel y ofertas de proveedores
│   └── admin.py            # Dashboard broker
│
├── services/               # Lógica de negocio
│   ├── cloudinary_svc.py   # Subida de imágenes
│   ├── whatsapp_svc.py     # Integración WhatsApp
│   ├── push_svc.py         # Push notifications
│   └── notificaciones_log.py
│
├── templates/              # Plantillas Jinja2
│   ├── base.html           # Layout maestro
│   ├── index.html          # Landing page
│   └── ...
│
├── static/                 # Recursos estáticos
│   ├── css/main.css
│   ├── js/
│   │   ├── main.js
│   │   └── sw.js           # Service Worker
│   ├── icons/              # Iconos PWA
│   └── uploads/            # Imágenes subidas
│
└── tests/                  # Tests automatizados
    ├── test_auth.py
    ├── test_solicitudes.py
    └── ...
```

## Flujo de Negocio

1. **Cliente publica solicitud**
   - Describe pieza buscada
   - Sube hasta 6 fotos
   - Especifica categoría, ubicación, presupuesto

2. **Broker recibe notificación**
   - WhatsApp automático
   - Dashboard con solicitudes activas

3. **Broker contacta proveedores**
   - Envío manual o automático vía WhatsApp
   - Proveedores NO ven info del cliente

4. **Proveedores ofertan al broker**
   - Precio, tiempo, foto de pieza
   - Ofertas SOLO visibles para broker

5. **Broker negocia con cliente**
   - Evalúa mejores ofertas
   - Contacta cliente telefónicamente
   - Cierra negocio y cobra comisión

## Testing

```bash
# Ejecutar todos los tests
pytest

# Con reporte de cobertura
pytest --cov=. --cov-report=html

# Ver reporte de cobertura
# Abre: htmlcov/index.html en tu navegador
```

## Deployment

Ver [DEPLOYMENT.md](DEPLOYMENT.md) para instrucciones detalladas de despliegue en producción.

### Resumen Rápido

**Usando Docker:**

```bash
docker-compose up -d
```

**Usando Gunicorn (Linux):**

```bash
gunicorn -w 4 -b 0.0.0.0:8000 "app:create_app('production')"
```

**Con Nginx como Proxy Inverso:**

Ver [DEPLOYMENT.md](DEPLOYMENT.md)

## Configuración de Servicios Externos

### Cloudinary

1. Crea cuenta en: https://cloudinary.com
2. Ve a Dashboard > Account Details
3. Copia: Cloud Name, API Key, API Secret
4. Pégalos en `.env`

### Green API (WhatsApp)

1. Crea cuenta en: https://green-api.com
2. Plan gratuito: 300 mensajes/día
3. Copia: Instance ID, Token
4. Pégalos en `.env`

### Firebase Cloud Messaging

1. Ve a: https://console.firebase.google.com
2. Crea proyecto o usa existente
3. Project Settings > Cloud Messaging
4. Copia Server Key (Legacy)
5. Pégalo en `.env`

## Solución de Problemas

### Error: "SECRET_KEY no está configurada"

- Asegúrate de tener un archivo `.env` en la raíz del proyecto
- Genera una SECRET_KEY: `python -c "import secrets; print(secrets.token_hex(32))"`
- Agrégala al `.env`

### Error: "No se pudo conectar a la base de datos"

- Verifica que el servicio de PostgreSQL esté en ejecución
  (Windows: `services.msc` → `postgresql-x64-NN`; Linux: `sudo systemctl status postgresql`)
- Revisa usuario, contraseña, puerto y nombre de la base en `DATABASE_URL` (.env)
- Si la base no existe todavía: `python scripts/crear_db_postgres.py`

### Las imágenes no se suben

- Si no configuraste Cloudinary, las imágenes se guardan en `static/uploads/`
- Verifica que la carpeta `static/uploads/` exista y tenga permisos de escritura

### Notificaciones WhatsApp no funcionan

- Verifica que Green API esté configurado en `.env`
- Plan gratuito tiene límite de 300 mensajes/día
- Verifica que el número de teléfono incluya código de país sin `+` ni espacios

## Contribuir

1. Fork el proyecto
2. Crea una rama para tu feature: `git checkout -b feature/nueva-funcionalidad`
3. Commit tus cambios: `git commit -am 'Agrega nueva funcionalidad'`
4. Push a la rama: `git push origin feature/nueva-funcionalidad`
5. Crea un Pull Request

## Licencia

Este proyecto es privado y confidencial.

## Soporte

Para reportar bugs o solicitar features:

- Email: soporte@buscapieza.do
- Issues: GitHub Issues

## Roadmap

- [ ] Sistema de pagos integrado
- [ ] Chat en tiempo real
- [ ] Rating y reviews de proveedores
- [ ] Dashboard de analytics avanzado
- [ ] App móvil nativa (iOS/Android)
- [ ] Exportación de reportes (PDF/Excel)
- [ ] Integración con más canales de notificación

---

**Desarrollado con Flask y ❤️ en República Dominicana**
