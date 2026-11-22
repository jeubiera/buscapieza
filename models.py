from extensions import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP


def ahora_utc():
    """datetime UTC sin tzinfo (columnas "timestamp without time zone")."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


ROLES_REGISTRO = ('cliente', 'proveedor')
ESTADOS_SOLICITUD = ('pendiente', 'en_gestion', 'completada', 'cancelada')
URGENCIAS = ('normal', 'urgente', 'muy_urgente')
METODOS_PAGO = ('efectivo', 'transferencia', 'tarjeta', 'otro')

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
    rol          = db.Column(db.Enum('cliente','proveedor','admin', name='rol_usuario'), default='cliente')
    provincia_id = db.Column(db.Integer, db.ForeignKey('provincias.id'))
    empresa      = db.Column(db.String(150))   # para proveedores
    whatsapp     = db.Column(db.String(20))
    activo       = db.Column(db.Boolean, default=True)
    verificado   = db.Column(db.Boolean, default=False)
    created_at   = db.Column(db.DateTime, default=ahora_utc)

    # Programa de referidos
    codigo_referido = db.Column(db.String(12), unique=True, index=True)   # se genera al primer uso
    patrocinador_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), index=True)

    provincia    = db.relationship('Provincia', backref='usuarios')
    solicitudes  = db.relationship('Solicitud', backref='cliente', lazy='dynamic',
                                   foreign_keys='Solicitud.cliente_id')
    patrocinador = db.relationship('Usuario', remote_side=[id],
                                   backref=db.backref('referidos', lazy='dynamic'))

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
    codigo        = db.Column(db.String(20), unique=True)  # BP-2026-0001
    cliente_id    = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    categoria_id  = db.Column(db.Integer, db.ForeignKey('categorias.id'))
    provincia_id  = db.Column(db.Integer, db.ForeignKey('provincias.id'))
    titulo        = db.Column(db.String(200), nullable=False)
    descripcion   = db.Column(db.Text, nullable=False)
    presupuesto   = db.Column(db.Numeric(12,2))   # presupuesto máx opcional
    urgencia      = db.Column(db.Enum('normal','urgente','muy_urgente', name='urgencia_solicitud'), default='normal')
    estado        = db.Column(db.Enum('pendiente','en_gestion','completada','cancelada', name='estado_solicitud'), default='pendiente')
    # Campos solo visibles al admin/broker
    notas_admin   = db.Column(db.Text)
    created_at    = db.Column(db.DateTime, default=ahora_utc)
    updated_at    = db.Column(db.DateTime, default=ahora_utc, onupdate=ahora_utc)

    categoria  = db.relationship('Categoria', backref='solicitudes')
    provincia  = db.relationship('Provincia', backref='solicitudes')
    fotos      = db.relationship('SolicitudFoto', backref='solicitud', cascade='all, delete-orphan')
    ofertas    = db.relationship('Oferta', backref='solicitud', lazy='dynamic')

    def generar_codigo(self):
        año = ahora_utc().year
        self.codigo = f"BP-{año}-{str(self.id).zfill(4)}"

    def transaccion_activa(self):
        """Transacción pendiente o pagada de esta solicitud (máximo una)."""
        return next((t for t in self.transacciones if t.estado_pago != 'cancelado'), None)

    @property
    def acepta_ofertas(self):
        return self.estado in ('pendiente', 'en_gestion') and self.transaccion_activa() is None

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
    estado         = db.Column(db.Enum('nueva','vista','aceptada','rechazada', name='estado_oferta'), default='nueva')
    notas_broker   = db.Column(db.Text)          # solo visible al broker

    # Campos para monetización del broker
    precio_cliente = db.Column(db.Numeric(12,2))  # precio que se cotiza al cliente (precio + margen)
    margen_broker  = db.Column(db.Numeric(12,2))  # margen/comisión del broker
    porcentaje_margen = db.Column(db.Numeric(5,2), default=15.00)  # % de margen (ej: 15%)

    created_at     = db.Column(db.DateTime, default=ahora_utc)

    proveedor = db.relationship('Usuario', backref='ofertas')

    def calcular_precio_cliente(self, porcentaje=None):
        """
        Calcula el precio al cliente aplicando margen
        Args:
            porcentaje: % de margen (si None, usa self.porcentaje_margen o default 15%)
        """
        if porcentaje is None:
            porcentaje = self.porcentaje_margen if self.porcentaje_margen is not None else 15
        porcentaje = Decimal(str(porcentaje))
        precio = Decimal(str(self.precio))
        centavo = Decimal('0.01')

        self.porcentaje_margen = porcentaje
        self.margen_broker  = (precio * porcentaje / 100).quantize(centavo, ROUND_HALF_UP)
        self.precio_cliente = precio + self.margen_broker
        return self.precio_cliente


class Transaccion(db.Model):
    """
    Registro de transacciones cerradas y comisiones del broker
    """
    __tablename__ = 'transacciones'
    id              = db.Column(db.Integer, primary_key=True)
    # Origen de la venta: una solicitud (oferta de proveedor) o una publicación de compraventa
    solicitud_id    = db.Column(db.Integer, db.ForeignKey('solicitudes.id'), nullable=True)
    oferta_id       = db.Column(db.Integer, db.ForeignKey('ofertas.id'), nullable=True)
    publicacion_id  = db.Column(db.Integer, db.ForeignKey('publicaciones.id'), nullable=True)
    cliente_id      = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    proveedor_id    = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)

    # Precios y comisiones
    precio_proveedor = db.Column(db.Numeric(12,2), nullable=False)  # lo que paga el broker al proveedor
    precio_cliente   = db.Column(db.Numeric(12,2), nullable=False)  # lo que cobra el broker al cliente
    comision_broker  = db.Column(db.Numeric(12,2), nullable=False)  # ganancia del broker
    porcentaje_comision = db.Column(db.Numeric(5,2))                # % de comisión aplicado

    # Detalles de pago
    metodo_pago      = db.Column(db.Enum('efectivo','transferencia','tarjeta','otro', name='metodo_pago'), default='efectivo')
    estado_pago      = db.Column(db.Enum('pendiente','pagado','cancelado', name='estado_pago'), default='pendiente')
    fecha_pago       = db.Column(db.DateTime)

    # Metadata
    notas            = db.Column(db.Text)
    created_at       = db.Column(db.DateTime, default=ahora_utc)
    updated_at       = db.Column(db.DateTime, default=ahora_utc, onupdate=ahora_utc)

    # Relaciones
    solicitud = db.relationship('Solicitud', backref='transacciones')
    oferta    = db.relationship('Oferta', backref='transaccion', uselist=False)
    publicacion = db.relationship('Publicacion', backref='transacciones')
    cliente   = db.relationship('Usuario', foreign_keys=[cliente_id], backref='transacciones_como_cliente')
    proveedor = db.relationship('Usuario', foreign_keys=[proveedor_id], backref='transacciones_como_proveedor')

    def calcular_comision(self):
        """Calcula la comisión del broker"""
        precio_cliente   = Decimal(str(self.precio_cliente))
        precio_proveedor = Decimal(str(self.precio_proveedor))
        self.comision_broker = precio_cliente - precio_proveedor
        if precio_proveedor > 0:
            self.porcentaje_comision = (self.comision_broker / precio_proveedor * 100).quantize(
                Decimal('0.01'), ROUND_HALF_UP)
        return self.comision_broker

    @property
    def codigo_origen(self):
        if self.publicacion:
            return self.publicacion.codigo
        return self.solicitud.codigo if self.solicitud else '—'

    @property
    def titulo_origen(self):
        if self.publicacion:
            return self.publicacion.titulo
        return self.solicitud.titulo if self.solicitud else ''


# ═════════════════════════════ COMPRAVENTA ════════════════════════════════════

ESTADOS_PUBLICACION = ('pendiente', 'publicada', 'rechazada', 'reservada', 'vendida', 'retirada')
CONDICIONES = ('nuevo', 'usado', 'reacondicionado')
ESTADOS_INTERES = ('nuevo', 'contactado', 'descartado', 'convertido')


class Publicacion(db.Model):
    """
    Artículo que un usuario quiere vender a través de BuscatodoRD.

    Flujo: pendiente → (admin acuerda precio y comisión) → publicada → reservada → vendida
           pendiente → rechazada (el vendedor puede corregir y reenviar)
           publicada/pendiente → retirada (vendedor o admin)

    Precios:
      precio_pedido   lo que el vendedor dice que quiere (referencia)
      precio_vendedor lo acordado con el vendedor = lo que recibe al venderse
      precio_publico  precio de lista = precio_vendedor + comisión
      mostrar_precio  si es False, el catálogo dice "Precio a consultar" y se negocia con cada interesado
    """
    __tablename__ = 'publicaciones'
    id             = db.Column(db.Integer, primary_key=True)
    codigo         = db.Column(db.String(20), unique=True)   # BV-2026-0001
    vendedor_id    = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    categoria_id   = db.Column(db.Integer, db.ForeignKey('categorias.id'))
    provincia_id   = db.Column(db.Integer, db.ForeignKey('provincias.id'))
    titulo         = db.Column(db.String(200), nullable=False)
    descripcion    = db.Column(db.Text, nullable=False)
    condicion      = db.Column(db.Enum(*CONDICIONES, name='condicion_articulo'), default='usado')
    precio_pedido  = db.Column(db.Numeric(12, 2), nullable=False)

    # Lo fija el admin al aprobar
    precio_vendedor   = db.Column(db.Numeric(12, 2))
    porcentaje_margen = db.Column(db.Numeric(5, 2))
    precio_publico    = db.Column(db.Numeric(12, 2))
    mostrar_precio    = db.Column(db.Boolean, default=True, nullable=False)

    estado         = db.Column(db.Enum(*ESTADOS_PUBLICACION, name='estado_publicacion'),
                               default='pendiente', nullable=False, index=True)
    destacado_hasta = db.Column(db.DateTime, index=True)   # sale primero en el catálogo hasta esta fecha
    motivo_rechazo = db.Column(db.Text)
    notas_admin    = db.Column(db.Text)
    vistas         = db.Column(db.Integer, default=0, nullable=False)
    publicada_en   = db.Column(db.DateTime)
    created_at     = db.Column(db.DateTime, default=ahora_utc)
    updated_at     = db.Column(db.DateTime, default=ahora_utc, onupdate=ahora_utc)

    vendedor  = db.relationship('Usuario', backref=db.backref('publicaciones', lazy='dynamic'))
    categoria = db.relationship('Categoria')
    provincia = db.relationship('Provincia')
    fotos     = db.relationship('PublicacionFoto', backref='publicacion', cascade='all, delete-orphan',
                                order_by='PublicacionFoto.orden')
    intereses = db.relationship('Interes', backref='publicacion', lazy='dynamic', cascade='all, delete-orphan')

    def generar_codigo(self):
        self.codigo = f"BV-{ahora_utc().year}-{str(self.id).zfill(4)}"

    def fijar_precio(self, precio_vendedor, porcentaje):
        """Precio acordado con el vendedor + comisión → precio público (redondeado al peso)."""
        precio_vendedor = Decimal(str(precio_vendedor)).quantize(Decimal('0.01'))
        porcentaje = Decimal(str(porcentaje))
        self.precio_vendedor = precio_vendedor
        self.porcentaje_margen = porcentaje
        self.precio_publico = (precio_vendedor * (1 + porcentaje / 100)).quantize(Decimal('1'), ROUND_HALF_UP)
        return self.precio_publico

    @property
    def comision_estimada(self):
        if self.precio_publico is None or self.precio_vendedor is None:
            return None
        return Decimal(self.precio_publico) - Decimal(self.precio_vendedor)

    @property
    def visible_en_catalogo(self):
        return self.estado in ('publicada', 'reservada')

    @property
    def destacada(self):
        return self.destacado_hasta is not None and self.destacado_hasta > ahora_utc()

    @property
    def editable_por_vendedor(self):
        return self.estado in ('pendiente', 'rechazada')

    def transaccion_activa(self):
        return next((t for t in self.transacciones if t.estado_pago != 'cancelado'), None)

    def propuestas_vendedor(self):
        return self.propuestas.filter_by(tipo='vendedor').order_by(Propuesta.created_at).all()

    def propuesta_vendedor_pendiente(self):
        return self.propuestas.filter_by(tipo='vendedor', estado='pendiente').first()


class PublicacionFoto(db.Model):
    __tablename__ = 'publicacion_fotos'
    id             = db.Column(db.Integer, primary_key=True)
    publicacion_id = db.Column(db.Integer, db.ForeignKey('publicaciones.id'), nullable=False)
    url            = db.Column(db.String(500), nullable=False)
    public_id      = db.Column(db.String(200))
    es_principal   = db.Column(db.Boolean, default=False)
    orden          = db.Column(db.Integer, default=0)


class Interes(db.Model):
    """Un comprador pide precio / muestra interés en una publicación (lo gestiona el broker)."""
    __tablename__ = 'intereses'
    __table_args__ = (db.UniqueConstraint('publicacion_id', 'comprador_id', name='uq_interes_publicacion_comprador'),)
    id             = db.Column(db.Integer, primary_key=True)
    publicacion_id = db.Column(db.Integer, db.ForeignKey('publicaciones.id'), nullable=False)
    comprador_id   = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    mensaje        = db.Column(db.Text)
    oferta_comprador = db.Column(db.Numeric(12, 2))   # "Ofrezco RD$..." (opcional)
    estado         = db.Column(db.Enum(*ESTADOS_INTERES, name='estado_interes'), default='nuevo', nullable=False)
    notas_admin    = db.Column(db.Text)
    created_at     = db.Column(db.DateTime, default=ahora_utc)
    updated_at     = db.Column(db.DateTime, default=ahora_utc, onupdate=ahora_utc)

    comprador = db.relationship('Usuario', backref=db.backref('intereses', lazy='dynamic'))

    def __init__(self, **kwargs):
        kwargs.setdefault('estado', 'nuevo')     # el default de la columna solo se aplica al guardar
        super().__init__(**kwargs)

    def propuesta_pendiente(self):
        return next((p for p in self.propuestas if p.estado == 'pendiente'), None)


TIPOS_PROPUESTA = ('vendedor', 'comprador')
AUTORES_PROPUESTA = ('admin', 'usuario')
ESTADOS_PROPUESTA = ('pendiente', 'aceptada', 'rechazada', 'contraofertada', 'retirada')
ESTADOS_COINCIDENCIA = ('nueva', 'ofrecida', 'descartada')


class Propuesta(db.Model):
    """
    Un mensaje de precio dentro de una negociación.

    tipo='vendedor':  BuscatodoRD ↔ vendedor sobre cuánto RECIBE el vendedor (precio_vendedor).
                      Las propuestas del admin llevan además la comisión y si se muestra el precio,
                      para publicar automáticamente cuando el vendedor acepta.
    tipo='comprador': BuscatodoRD ↔ un interesado sobre cuánto PAGA (precio final). Va ligada al Interes.
    Solo hay una propuesta 'pendiente' por hilo; al responder, la anterior pasa a 'contraofertada'.
    """
    __tablename__ = 'propuestas'
    id             = db.Column(db.Integer, primary_key=True)
    tipo           = db.Column(db.Enum(*TIPOS_PROPUESTA, name='tipo_propuesta'), nullable=False)
    publicacion_id = db.Column(db.Integer, db.ForeignKey('publicaciones.id'), nullable=False, index=True)
    interes_id     = db.Column(db.Integer, db.ForeignKey('intereses.id'), index=True)
    autor          = db.Column(db.Enum(*AUTORES_PROPUESTA, name='autor_propuesta'), nullable=False)
    monto          = db.Column(db.Numeric(12, 2), nullable=False)
    porcentaje     = db.Column(db.Numeric(5, 2))      # solo propuestas del admin al vendedor
    mostrar_precio = db.Column(db.Boolean)             # idem
    mensaje        = db.Column(db.Text)
    estado         = db.Column(db.Enum(*ESTADOS_PROPUESTA, name='estado_propuesta'), default='pendiente', nullable=False)
    created_at     = db.Column(db.DateTime, default=ahora_utc)
    respondida_en  = db.Column(db.DateTime)

    publicacion = db.relationship('Publicacion', backref=db.backref('propuestas', lazy='dynamic',
                                                                     cascade='all, delete-orphan'))

    def __init__(self, **kwargs):
        kwargs.setdefault('estado', 'pendiente')  # visible como pendiente antes de guardar (misma sesión)
        super().__init__(**kwargs)
    interes     = db.relationship('Interes', backref=db.backref('propuestas', order_by='Propuesta.created_at',
                                                                 cascade='all, delete-orphan'))


class Coincidencia(db.Model):
    """Un artículo en venta que parece ser lo que busca una solicitud abierta (cruce oferta ↔ demanda)."""
    __tablename__ = 'coincidencias'
    __table_args__ = (db.UniqueConstraint('solicitud_id', 'publicacion_id', name='uq_coincidencia_par'),)
    id             = db.Column(db.Integer, primary_key=True)
    solicitud_id   = db.Column(db.Integer, db.ForeignKey('solicitudes.id'), nullable=False, index=True)
    publicacion_id = db.Column(db.Integer, db.ForeignKey('publicaciones.id'), nullable=False, index=True)
    puntaje        = db.Column(db.Integer, nullable=False)
    palabras       = db.Column(db.String(300))   # términos en común, para que el admin vea por qué
    estado         = db.Column(db.Enum(*ESTADOS_COINCIDENCIA, name='estado_coincidencia'), default='nueva', nullable=False)
    created_at     = db.Column(db.DateTime, default=ahora_utc)

    solicitud   = db.relationship('Solicitud', backref=db.backref('coincidencias', lazy='dynamic',
                                                                   cascade='all, delete-orphan'))

    def __init__(self, **kwargs):
        kwargs.setdefault('estado', 'nueva')
        super().__init__(**kwargs)
    publicacion = db.relationship('Publicacion', backref=db.backref('coincidencias', lazy='dynamic',
                                                                     cascade='all, delete-orphan'))


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

    created_at      = db.Column(db.DateTime, default=ahora_utc)

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
            promedio = Decimal(sum(ratings_validos)) / len(ratings_validos)
            self.calificacion_general = int(promedio.quantize(Decimal('1'), ROUND_HALF_UP))
        return self.calificacion_general


class Notificacion(db.Model):
    __tablename__ = 'notificaciones'
    id           = db.Column(db.Integer, primary_key=True)
    tipo         = db.Column(db.Enum('whatsapp','push','email', name='tipo_notificacion'), default='whatsapp')
    destinatario = db.Column(db.String(20))   # número WA o token push
    mensaje      = db.Column(db.Text)
    enviado      = db.Column(db.Boolean, default=False)
    error        = db.Column(db.Text)
    created_at   = db.Column(db.DateTime, default=ahora_utc)

class PushToken(db.Model):
    __tablename__ = 'push_tokens'
    id         = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    token      = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=ahora_utc)
    usuario    = db.relationship('Usuario', backref='push_tokens')


class Configuracion(db.Model):
    """Claves de configuración dinámicas guardadas en BD."""
    __tablename__ = 'configuracion'
    id    = db.Column(db.Integer, primary_key=True)
    clave = db.Column(db.String(80), unique=True, nullable=False)
    valor = db.Column(db.Text, default='')


# ═════════════════════════════ PAGOS Y DESTACADOS (Fase 3) ════════════════════

METODOS_PAGO_EN_LINEA = ('transferencia', 'azul', 'cardnet')
CONCEPTOS_PAGO = ('venta', 'destacado')
ESTADOS_PAGO_EN_LINEA = ('pendiente', 'en_revision', 'aprobado', 'rechazado', 'cancelado')
ESTADOS_DESTACADO = ('pendiente', 'activo', 'cancelado')


class PlanDestacado(db.Model):
    """Planes para destacar una publicación (los define el admin)."""
    __tablename__ = 'planes_destacado'
    id     = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(80), nullable=False)
    dias   = db.Column(db.Integer, nullable=False)
    precio = db.Column(db.Numeric(12, 2), nullable=False)
    activo = db.Column(db.Boolean, default=True, nullable=False)
    orden  = db.Column(db.Integer, default=0, nullable=False)


class Destacado(db.Model):
    """Una compra de destacado. Se activa cuando su pago se aprueba."""
    __tablename__ = 'destacados'
    id             = db.Column(db.Integer, primary_key=True)
    publicacion_id = db.Column(db.Integer, db.ForeignKey('publicaciones.id'), nullable=False, index=True)
    plan_id        = db.Column(db.Integer, db.ForeignKey('planes_destacado.id'))
    usuario_id     = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    nombre_plan    = db.Column(db.String(80), nullable=False)   # copia: el plan puede cambiar después
    dias           = db.Column(db.Integer, nullable=False)
    precio         = db.Column(db.Numeric(12, 2), nullable=False)
    estado         = db.Column(db.Enum(*ESTADOS_DESTACADO, name='estado_destacado'), default='pendiente', nullable=False)
    inicio         = db.Column(db.DateTime)
    fin            = db.Column(db.DateTime)
    created_at     = db.Column(db.DateTime, default=ahora_utc)

    publicacion = db.relationship('Publicacion', backref=db.backref('destacados', lazy='dynamic'))
    plan        = db.relationship('PlanDestacado')
    usuario     = db.relationship('Usuario')

    def __init__(self, **kwargs):
        kwargs.setdefault('estado', 'pendiente')
        super().__init__(**kwargs)


class Pago(db.Model):
    """
    Pago en línea de una venta (lo paga el comprador) o de un destacado (lo paga el vendedor).

    subtotal: importe base · itbis: impuesto calculado (configurable, 0 por defecto) · monto: total cobrado.
    Para tarjeta guarda la referencia de la pasarela y su respuesta (nunca datos de la tarjeta).
    """
    __tablename__ = 'pagos'
    id             = db.Column(db.Integer, primary_key=True)
    referencia     = db.Column(db.String(24), unique=True, index=True)   # PG-2026-000001
    concepto       = db.Column(db.Enum(*CONCEPTOS_PAGO, name='concepto_pago'), nullable=False)
    transaccion_id = db.Column(db.Integer, db.ForeignKey('transacciones.id'), index=True)
    destacado_id   = db.Column(db.Integer, db.ForeignKey('destacados.id'), index=True)
    usuario_id     = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False, index=True)
    metodo         = db.Column(db.Enum(*METODOS_PAGO_EN_LINEA, name='metodo_pago_en_linea'), nullable=False)
    subtotal       = db.Column(db.Numeric(12, 2), nullable=False)
    itbis          = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    monto          = db.Column(db.Numeric(12, 2), nullable=False)
    estado         = db.Column(db.Enum(*ESTADOS_PAGO_EN_LINEA, name='estado_pago_en_linea'),
                               default='pendiente', nullable=False, index=True)
    comprobante_url       = db.Column(db.String(500))
    comprobante_public_id = db.Column(db.String(200))
    pasarela_ref   = db.Column(db.String(120))   # Azul: AzulOrderId · CardNet: SESSION
    pasarela_clave = db.Column(db.String(200))   # CardNet: session-key (para consultar el resultado)
    autorizacion   = db.Column(db.String(60))
    respuesta      = db.Column(db.Text)          # respuesta de la pasarela (JSON, sin datos de tarjeta)
    motivo_rechazo = db.Column(db.Text)
    revisado_por_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    created_at     = db.Column(db.DateTime, default=ahora_utc)
    pagado_en      = db.Column(db.DateTime)

    usuario     = db.relationship('Usuario', foreign_keys=[usuario_id], backref=db.backref('pagos', lazy='dynamic'))
    revisado_por = db.relationship('Usuario', foreign_keys=[revisado_por_id])
    transaccion = db.relationship('Transaccion', backref=db.backref('pagos', lazy='dynamic'))
    destacado   = db.relationship('Destacado', backref=db.backref('pagos', lazy='dynamic'))

    def __init__(self, **kwargs):
        kwargs.setdefault('estado', 'pendiente')
        kwargs.setdefault('itbis', 0)
        super().__init__(**kwargs)

    def generar_referencia(self):
        self.referencia = f"PG-{ahora_utc().year}-{str(self.id).zfill(6)}"

    @property
    def descripcion(self):
        if self.concepto == 'venta' and self.transaccion:
            return f'Compra {self.transaccion.codigo_origen}: {self.transaccion.titulo_origen}'
        if self.concepto == 'destacado' and self.destacado:
            return f'Destacar {self.destacado.publicacion.codigo} · {self.destacado.nombre_plan}'
        return self.concepto


# ═════════════════════════════ PROGRAMA DE REFERIDOS ══════════════════════════

ESTADOS_COMISION_REFERIDO = ('pendiente_calificacion', 'acumulada', 'disponible', 'pagada', 'vencida', 'reversada')


class ComisionReferido(db.Model):
    """
    Comisión que gana un usuario porque alguien de su red (hasta N niveles) pagó una compra.

    Ciclo (igual que el motor de AmbarERP):
      pendiente_calificacion → al cerrar el mes: si el beneficiario califica → disponible
                                                  si no → acumulada (hasta vence_periodo)
      acumulada → en un cierre posterior: si califica → disponible; si pasó vence_periodo → vencida
      disponible → el admin registra el pago → pagada
      cualquiera salvo pagada → reversada (anulación manual)
    """
    __tablename__ = 'comisiones_referido'
    __table_args__ = (db.UniqueConstraint('transaccion_id', 'beneficiario_id', name='uq_comision_trans_beneficiario'),)
    id              = db.Column(db.Integer, primary_key=True)
    beneficiario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False, index=True)
    comprador_id    = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    transaccion_id  = db.Column(db.Integer, db.ForeignKey('transacciones.id'), nullable=False, index=True)
    nivel           = db.Column(db.Integer, nullable=False)
    porcentaje      = db.Column(db.Numeric(5, 2), nullable=False)
    base            = db.Column(db.Numeric(12, 2), nullable=False)    # sobre qué se calculó
    monto           = db.Column(db.Numeric(12, 2), nullable=False)
    periodo         = db.Column(db.String(7), nullable=False, index=True)     # AAAA-MM
    vence_periodo   = db.Column(db.String(7), nullable=False)
    estado          = db.Column(db.Enum(*ESTADOS_COMISION_REFERIDO, name='estado_comision_referido'),
                                default='pendiente_calificacion', nullable=False, index=True)
    liquidacion_id  = db.Column(db.Integer, db.ForeignKey('liquidaciones_referido.id'))
    created_at      = db.Column(db.DateTime, default=ahora_utc)

    beneficiario = db.relationship('Usuario', foreign_keys=[beneficiario_id],
                                   backref=db.backref('comisiones_referido', lazy='dynamic'))
    comprador    = db.relationship('Usuario', foreign_keys=[comprador_id])
    transaccion  = db.relationship('Transaccion')

    def __init__(self, **kwargs):
        kwargs.setdefault('estado', 'pendiente_calificacion')
        super().__init__(**kwargs)


class LiquidacionReferido(db.Model):
    """Pago al beneficiario de sus comisiones disponibles (lo registra el admin)."""
    __tablename__ = 'liquidaciones_referido'
    id              = db.Column(db.Integer, primary_key=True)
    beneficiario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False, index=True)
    monto           = db.Column(db.Numeric(12, 2), nullable=False)
    metodo          = db.Column(db.String(40), nullable=False, default='transferencia')
    referencia      = db.Column(db.String(120))
    notas           = db.Column(db.Text)
    registrado_por_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    created_at      = db.Column(db.DateTime, default=ahora_utc)

    beneficiario   = db.relationship('Usuario', foreign_keys=[beneficiario_id])
    registrado_por = db.relationship('Usuario', foreign_keys=[registrado_por_id])
    comisiones     = db.relationship('ComisionReferido', backref='liquidacion')


class CierreReferido(db.Model):
    """Registro de cada cierre mensual del programa."""
    __tablename__ = 'cierres_referido'
    id           = db.Column(db.Integer, primary_key=True)
    periodo      = db.Column(db.String(7), unique=True, nullable=False)
    disponibles  = db.Column(db.Integer, default=0)
    acumuladas   = db.Column(db.Integer, default=0)
    vencidas     = db.Column(db.Integer, default=0)
    cerrado_por_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    created_at   = db.Column(db.DateTime, default=ahora_utc)
