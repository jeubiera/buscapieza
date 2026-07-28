# Migraciones de Base de Datos - BuscaPieza RD

Este documento explica las actualizaciones de la base de datos y cómo aplicarlas.

## Nuevos Modelos y Campos Agregados

### 1. Sistema de Comisiones en Ofertas

Se agregaron campos a la tabla `ofertas`:

```sql
ALTER TABLE ofertas
ADD COLUMN precio_cliente DECIMAL(12,2) NULL COMMENT 'Precio cotizado al cliente (con margen)',
ADD COLUMN margen_broker DECIMAL(12,2) NULL COMMENT 'Margen/comisión del broker',
ADD COLUMN porcentaje_margen DECIMAL(5,2) DEFAULT 15.00 COMMENT 'Porcentaje de margen aplicado';
```

**Uso:**
```python
# Al crear/editar oferta, calcular precio al cliente
oferta = Oferta(precio=1000, ...)
oferta.calcular_precio_cliente(porcentaje=15)  # Aplica 15% de margen
# Resultado: precio_cliente = 1150, margen_broker = 150
```

### 2. Tabla de Transacciones

Nueva tabla para registrar ventas cerradas y comisiones:

```sql
CREATE TABLE transacciones (
    id INT AUTO_INCREMENT PRIMARY KEY,
    solicitud_id INT NOT NULL,
    oferta_id INT NOT NULL,
    cliente_id INT NOT NULL,
    proveedor_id INT NOT NULL,
    precio_proveedor DECIMAL(12,2) NOT NULL COMMENT 'Precio al proveedor',
    precio_cliente DECIMAL(12,2) NOT NULL COMMENT 'Precio al cliente',
    comision_broker DECIMAL(12,2) NOT NULL COMMENT 'Ganancia del broker',
    porcentaje_comision DECIMAL(5,2) COMMENT 'Porcentaje aplicado',
    metodo_pago ENUM('efectivo','transferencia','tarjeta','otro') DEFAULT 'efectivo',
    estado_pago ENUM('pendiente','pagado','cancelado') DEFAULT 'pendiente',
    fecha_pago DATETIME NULL,
    notas TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (solicitud_id) REFERENCES solicitudes(id),
    FOREIGN KEY (oferta_id) REFERENCES ofertas(id),
    FOREIGN KEY (cliente_id) REFERENCES usuarios(id),
    FOREIGN KEY (proveedor_id) REFERENCES usuarios(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

**Uso:**
```python
# Cuando se cierra una venta
transaccion = Transaccion(
    solicitud_id=sol.id,
    oferta_id=oferta.id,
    cliente_id=cliente.id,
    proveedor_id=proveedor.id,
    precio_proveedor=1000,
    precio_cliente=1150,
    metodo_pago='transferencia'
)
transaccion.calcular_comision()  # Calcula automáticamente
db.session.add(transaccion)
db.session.commit()
```

### 3. Sistema de Ratings/Reviews

Nueva tabla para calificaciones de proveedores:

```sql
CREATE TABLE ratings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    transaccion_id INT NOT NULL,
    proveedor_id INT NOT NULL,
    cliente_id INT NOT NULL,
    calidad_producto INT COMMENT 'Calificación 1-5',
    tiempo_entrega INT COMMENT 'Calificación 1-5',
    atencion_cliente INT COMMENT 'Calificación 1-5',
    precio_justo INT COMMENT 'Calificación 1-5',
    calificacion_general INT COMMENT 'Promedio automático',
    comentario TEXT,
    visible BOOLEAN DEFAULT TRUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (transaccion_id) REFERENCES transacciones(id),
    FOREIGN KEY (proveedor_id) REFERENCES usuarios(id),
    FOREIGN KEY (cliente_id) REFERENCES usuarios(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

**Uso:**
```python
# Después de completar transacción
rating = Rating(
    transaccion_id=trans.id,
    proveedor_id=proveedor.id,
    cliente_id=cliente.id,
    calidad_producto=5,
    tiempo_entrega=4,
    atencion_cliente=5,
    precio_justo=4,
    comentario='Excelente servicio'
)
rating.calcular_promedio()  # Calcula rating general
db.session.add(rating)
db.session.commit()
```

### 4. Configuraciones de Comisión

Se agregaron configuraciones por defecto en la tabla `configuracion`:

```sql
INSERT INTO configuracion (clave, valor) VALUES
('comision_default', '15.00'),
('comision_minima', '5.00'),
('comision_maxima', '30.00'),
('moneda', 'RD$'),
('impuesto_itbis', '18.00');
```

## Aplicar Migraciones

### Opción 1: Usar Flask-Migrate (Recomendado)

```bash
# Inicializar migraciones (solo primera vez)
flask db init

# Crear migración automática
flask db migrate -m "Agregar sistema de comisiones y ratings"

# Aplicar migración
flask db upgrade
```

### Opción 2: SQL Manual

Si Flask-Migrate presenta problemas, ejecuta manualmente:

```bash
# Backup de la BD primero
mysqldump -u root -p buscapieza_db > backup_antes_migracion.sql

# Ejecutar migraciones
mysql -u root -p buscapieza_db < migraciones.sql
```

### Opción 3: Dejar que SQLAlchemy cree automáticamente

Si estás en desarrollo y no tienes datos importantes:

```python
# En Python
from app import create_app
from extensions import db

app = create_app()
with app.app_context():
    db.drop_all()  # ⚠️ CUIDADO: Borra todos los datos
    db.create_all()  # Crea todas las tablas con nuevos campos
```

## Verificar que las Migraciones se Aplicaron

```python
from app import create_app
from models import Oferta, Transaccion, Rating, Configuracion
from extensions import db

app = create_app()
with app.app_context():
    # Verificar que las tablas existen
    print("Tabla Transacciones:", db.engine.has_table('transacciones'))
    print("Tabla Ratings:", db.engine.has_table('ratings'))

    # Verificar configuraciones
    configs = Configuracion.query.all()
    for c in configs:
        print(f"{c.clave}: {c.valor}")
```

## Rollback (Revertir Cambios)

Si algo sale mal:

```bash
# Restaurar backup
mysql -u root -p buscapieza_db < backup_antes_migracion.sql

# O con Flask-Migrate
flask db downgrade -1  # Retrocede 1 migración
```

## Notas Importantes

1. **Siempre haz backup** antes de aplicar migraciones en producción
2. **Testa las migraciones** en ambiente de desarrollo primero
3. Los nuevos campos tienen valores por defecto, por lo que registros existentes no se romperán
4. Las relaciones entre tablas usan `CASCADE` para mantener integridad referencial

## Scripts SQL Completos

Los scripts SQL completos están disponibles en `migrations/manual/`:
- `001_comisiones.sql` - Sistema de comisiones
- `002_transacciones.sql` - Tabla de transacciones
- `003_ratings.sql` - Sistema de ratings
- `004_configuracion_seed.sql` - Datos de configuración

## Soporte

Si tienes problemas con las migraciones:
1. Revisa los logs de MySQL
2. Verifica que tienes permisos `ALTER TABLE`
3. Contacta al equipo de desarrollo
