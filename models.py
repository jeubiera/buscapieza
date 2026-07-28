from extensions import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

class Provincia(db.Model):
    __tablename__ = 'provincias'
    id     = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(80), nullable=False)

class Categoria(db.Model):
    __tablename__ = 'categorias'
    id     = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    icono  = db.Column(db.String(10), default='📦')
    color  = db.Column(db.String(10), default='#FF6B35')
    activa = db.Column(db.Boolean, default=True)

class Usuario(UserMixin, db.Model):
    __tablename__ = 'usuarios'
    id           = db.Column(db.Integer, primary_key=True)
    nombre       = db.Column(db.String(120), nullable=False)
    email        = db.Column(db.String(150), unique=True, nullable=False)
    telefono     = db.Column(db.String(20), nullable=False)
    password_hash= db.Column(db.String(256))
    rol          = db.Column(db.Enum('cliente','proveedor','admin'), default='cliente')
    provincia_id = db.Column(db.Integer, db.ForeignKey('provincias.id'))
    empresa      = db.Column(db.String(150))   # para proveedores
    whatsapp     = db.Column(db.String(20))
    activo       = db.Column(db.Boolean, default=True)
    verificado   = db.Column(db.Boolean, default=False)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    provincia    = db.relationship('Provincia', backref='usuarios')
    solicitudes  = db.relationship('Solicitud', backref='cliente', lazy='dynamic',
                                   foreign_keys='Solicitud.cliente_id')

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)

    def rating_promedio(self):
        """Calcula el rating promedio del proveedor"""
        if self.rol != 'proveedor':
            return None

        ratings = [r.calificacion_general for r in self.ratings_recibidos if r.visible and r.calificacion_general]
        if ratings:
            return round(sum(ratings) / len(ratings), 1)
        return None

    def total_transacciones(self):
        """Cuenta transacciones completadas del proveedor"""
        if self.rol != 'proveedor':
            return 0
        return len([t for t in self.transacciones_como_proveedor if t.estado_pago == 'pagado'])

class Solicitud(db.Model):
    __tablename__ = 'solicitudes'
    id            = db.Column(db.Integer, primary_key=True)
    codigo        = db.Column(db.String(12), unique=True)  # BP-2024-001
    cliente_id    = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    categoria_id  = db.Column(db.Integer, db.ForeignKey('categorias.id'))
    provincia_id  = db.Column(db.Integer, db.ForeignKey('provincias.id'))
    titulo        = db.Column(db.String(200), nullable=False)
    descripcion   = db.Column(db.Text, nullable=False)
    presupuesto   = db.Column(db.Numeric(12,2))   # presupuesto máx opcional
    urgencia      = db.Column(db.Enum('normal','urgente','muy_urgente'), default='normal')
    estado        = db.Column(db.Enum('pendiente','en_gestion','completada','cancelada'), default='pendiente')
    # Campos solo visibles al admin/broker
    notas_admin   = db.Column(db.Text)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at    = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    categoria  = db.relationship('Categoria', backref='solicitudes')
    provincia  = db.relationship('Provincia', backref='solicitudes')
    fotos      = db.relationship('SolicitudFoto', backref='solicitud', cascade='all, delete-orphan')
    ofertas    = db.relationship('Oferta', backref='solicitud', lazy='dynamic')

    def generar_codigo(self):
        from datetime import date
        año = date.today().year
        self.codigo = f"BP-{año}-{str(self.id).zfill(4)}"

class SolicitudFoto(db.Model):
    __tablename__ = 'solicitud_fotos'
    id           = db.Column(db.Integer, primary_key=True)
    solicitud_id = db.Column(db.Integer, db.ForeignKey('solicitudes.id'), nullable=False)
    url          = db.Column(db.String(500), nullable=False)   # URL Cloudinary o local
    public_id    = db.Column(db.String(200))                   # Cloudinary public_id
    es_principal = db.Column(db.Boolean, default=False)
    orden        = db.Column(db.Integer, default=0)

class Oferta(db.Model):
    """Oferta que hace un proveedor AL BROKER (no al cliente)"""
    __tablename__ = 'ofertas'
    id           = db.Column(db.Integer, primary_key=True)
    solicitud_id = db.Column(db.Integer, db.ForeignKey('solicitudes.id'), nullable=False)
    proveedor_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    precio       = db.Column(db.Numeric(12,2), nullable=False)
    descripcion  = db.Column(db.Text)
    tiempo_entrega = db.Column(db.String(100))   # "2 días", "inmediato", etc
    incluye_envio  = db.Column(db.Boolean, default=False)
    foto_url       = db.Column(db.String(500))   # foto opcional de la pieza
    estado         = db.Column(db.Enum('nueva','vista','aceptada','rechazada'), default='nueva')
    notas_broker   = db.Column(db.Text)          # solo visible al broker

    # Campos para monetización del broker
    precio_cliente = db.Column(db.Numeric(12,2))  # precio que se cotiza al cliente (precio + margen)
    margen_broker  = db.Column(db.Numeric(12,2))  # margen/comisión del broker
    porcentaje_margen = db.Column(db.Numeric(5,2), default=15.00)  # % de margen (ej: 15%)

    created_at     = db.Column(db.DateTime, default=datetime.utcnow)

    proveedor = db.relationship('Usuario', backref='ofertas')

    def calcular_precio_cliente(self, porcentaje=None):
        """
        Calcula el precio al cliente aplicando margen
        Args:
            porcentaje: % de margen (si None, usa self.porcentaje_margen o default 15%)
        """
        if porcentaje is None:
            porcentaje = float(self.porcentaje_margen or 15.00)

        self.margen_broker = float(self.precio) * (porcentaje / 100)
        self.precio_cliente = float(self.precio) + self.margen_broker
        return self.precio_cliente


class Transaccion(db.Model):
    """
    Registro de transacciones cerradas y comisiones del broker
    """
    __tablename__ = 'transacciones'
    id              = db.Column(db.Integer, primary_key=True)
    solicitud_id    = db.Column(db.Integer, db.ForeignKey('solicitudes.id'), nullable=False)
    oferta_id       = db.Column(db.Integer, db.ForeignKey('ofertas.id'), nullable=False)
    cliente_id      = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    proveedor_id    = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)

    # Precios y comisiones
    precio_proveedor = db.Column(db.Numeric(12,2), nullable=False)  # lo que paga el broker al proveedor
    precio_cliente   = db.Column(db.Numeric(12,2), nullable=False)  # lo que cobra el broker al cliente
    comision_broker  = db.Column(db.Numeric(12,2), nullable=False)  # ganancia del broker
    porcentaje_comision = db.Column(db.Numeric(5,2))                # % de comisión aplicado

    # Detalles de pago
    metodo_pago      = db.Column(db.Enum('efectivo','transferencia','tarjeta','otro'), default='efectivo')
    estado_pago      = db.Column(db.Enum('pendiente','pagado','cancelado'), default='pendiente')
    fecha_pago       = db.Column(db.DateTime)

    # Metadata
    notas            = db.Column(db.Text)
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at       = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    solicitud = db.relationship('Solicitud', backref='transacciones')
    oferta    = db.relationship('Oferta', backref='transaccion', uselist=False)
    cliente   = db.relationship('Usuario', foreign_keys=[cliente_id], backref='transacciones_como_cliente')
    proveedor = db.relationship('Usuario', foreign_keys=[proveedor_id], backref='transacciones_como_proveedor')

    def calcular_comision(self):
        """Calcula la comisión del broker"""
        self.comision_broker = self.precio_cliente - self.precio_proveedor
        if self.precio_proveedor > 0:
            self.porcentaje_comision = (self.comision_broker / self.precio_proveedor) * 100
        return self.comision_broker


class Rating(db.Model):
    """
    Sistema de calificaciones para proveedores
    """
    __tablename__ = 'ratings'
    id              = db.Column(db.Integer, primary_key=True)
    transaccion_id  = db.Column(db.Integer, db.ForeignKey('transacciones.id'), nullable=False)
    proveedor_id    = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    cliente_id      = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)

    # Calificaciones (1-5 estrellas)
    calidad_producto   = db.Column(db.Integer)  # 1-5
    tiempo_entrega     = db.Column(db.Integer)  # 1-5
    atencion_cliente   = db.Column(db.Integer)  # 1-5
    precio_justo       = db.Column(db.Integer)  # 1-5
    calificacion_general = db.Column(db.Integer)  # promedio automático

    # Comentarios
    comentario      = db.Column(db.Text)
    visible         = db.Column(db.Boolean, default=True)  # el admin puede ocultar reviews inapropiadas

    created_at      = db.Column(db.DateTime, default=datetime.utcnow)

    # Relaciones
    transaccion = db.relationship('Transaccion', backref='rating')
    proveedor   = db.relationship('Usuario', foreign_keys=[proveedor_id], backref='ratings_recibidos')
    cliente     = db.relationship('Usuario', foreign_keys=[cliente_id], backref='ratings_dados')

    def calcular_promedio(self):
        """Calcula el rating general como promedio"""
        ratings = [
            self.calidad_producto,
            self.tiempo_entrega,
            self.atencion_cliente,
            self.precio_justo
        ]
        # Filtrar None values
        ratings_validos = [r for r in ratings if r is not None]
        if ratings_validos:
            self.calificacion_general = round(sum(ratings_validos) / len(ratings_validos))
        return self.calificacion_general


class Notificacion(db.Model):
    __tablename__ = 'notificaciones'
    id           = db.Column(db.Integer, primary_key=True)
    tipo         = db.Column(db.Enum('whatsapp','push','email'), default='whatsapp')
    destinatario = db.Column(db.String(20))   # número WA o token push
    mensaje      = db.Column(db.Text)
    enviado      = db.Column(db.Boolean, default=False)
    error        = db.Column(db.Text)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

class PushToken(db.Model):
    __tablename__ = 'push_tokens'
    id         = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    token      = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    usuario    = db.relationship('Usuario', backref='push_tokens')


class Configuracion(db.Model):
    """Claves de configuración dinámicas guardadas en BD."""
    __tablename__ = 'configuracion'
    id    = db.Column(db.Integer, primary_key=True)
    clave = db.Column(db.String(80), unique=True, nullable=False)
    valor = db.Column(db.Text, default='')
