import re
from urllib.parse import urlparse

from flask import Blueprint, render_template, redirect, url_for, request, flash, session
from flask_login import login_user, logout_user, login_required, current_user
from models import db, Usuario, Provincia, ROLES_REGISTRO

auth_bp = Blueprint('auth', __name__)

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
PASSWORD_MIN = 8
# Contraseña que traía el seed antiguo: se avisa para que se cambie
PASSWORD_ANTIGUA_ADMIN = 'Admin2024!'


def url_segura(destino):
    """Solo permite redirecciones a rutas internas ("/algo"), nunca a otros dominios."""
    if not destino or '\\' in destino:
        return None
    p = urlparse(destino)
    if p.scheme or p.netloc or not destino.startswith('/') or destino.startswith('//'):
        return None
    return destino


def _destino_por_rol(user):
    if user.rol == 'admin':
        return url_for('admin.dashboard')
    if user.rol == 'proveedor':
        return url_for('ofertas.mis_ofertas')
    return url_for('solicitudes.mis_solicitudes')


def validar_password(pw, pw2):
    if len(pw) < PASSWORD_MIN:
        return f'La contraseña debe tener al menos {PASSWORD_MIN} caracteres'
    if pw2 is not None and pw != pw2:
        return 'Las contraseñas no coinciden'
    return None


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(_destino_por_rol(current_user))
    if request.method == 'POST':
        email = request.form.get('email', '').lower().strip()
        pw    = request.form.get('password', '')
        user  = Usuario.query.filter_by(email=email, activo=True).first()
        if user and user.password_hash and user.check_password(pw):
            login_user(user, remember=bool(request.form.get('recordar', '1')))
            if user.rol == 'admin' and pw == PASSWORD_ANTIGUA_ADMIN:
                flash('⚠️ Estás usando la contraseña por defecto. Cámbiala ahora.', 'warning')
                return redirect(url_for('auth.cambiar_password'))
            return redirect(url_segura(request.args.get('next')) or _destino_por_rol(user))
        flash('Correo o contraseña incorrectos', 'danger')
    return render_template('auth/login.html')


@auth_bp.route('/registro', methods=['GET', 'POST'])
def registro():
    provincias = Provincia.query.order_by(Provincia.nombre).all()
    if request.method == 'POST':
        f = request.form
        rol      = f.get('rol', 'cliente')
        nombre   = f.get('nombre', '').strip()
        email    = f.get('email', '').lower().strip()
        telefono = f.get('telefono', '').strip()
        pw       = f.get('password', '')
        pw2      = f.get('password2')
        prov_id  = f.get('provincia_id', type=int)
        empresa  = f.get('empresa', '').strip()
        whatsapp = f.get('whatsapp', '').strip() or telefono

        errores = []
        if rol not in ROLES_REGISTRO:          # nunca se puede crear un admin desde aquí
            errores.append('Tipo de cuenta no válido')
        if not nombre or len(nombre) > 120:
            errores.append('El nombre es obligatorio')
        if not EMAIL_RE.match(email) or len(email) > 150:
            errores.append('Correo electrónico no válido')
        if len(re.sub(r'\D', '', telefono)) < 10:
            errores.append('Teléfono no válido (incluye el código de área, ej: 809-555-0000)')
        error_pw = validar_password(pw, pw2)
        if error_pw:
            errores.append(error_pw)
        if prov_id and not db.session.get(Provincia, prov_id):
            prov_id = None
        if not errores and Usuario.query.filter_by(email=email).first():
            errores.append('Este correo ya está registrado')

        if errores:
            for e in errores:
                flash(e, 'danger')
            return render_template('auth/registro.html', provincias=provincias, form=f,
                                   invitado_por=_invitado_por(f.get('ref'))), 400

        user = Usuario(
            nombre=nombre, email=email, telefono=telefono,
            rol=rol, provincia_id=prov_id,
            empresa=empresa[:150] if rol == 'proveedor' else None,
            whatsapp=whatsapp[:20],
            activo=True,
            verificado=(rol == 'cliente'),   # los proveedores los verifica el broker
        )
        user.set_password(pw)
        db.session.add(user)
        from services.referidos import asignar_patrocinador, asegurar_codigo
        asignar_patrocinador(user, f.get('ref') or session.get('ref'))
        asegurar_codigo(user)
        db.session.commit()
        session.pop('ref', None)
        login_user(user, remember=True)
        flash(f'¡Bienvenido, {nombre}!', 'success')
        if rol == 'proveedor':
            flash('Tu cuenta de proveedor está pendiente de verificación por el equipo de BuscatodoRD.', 'info')
            return redirect(url_for('ofertas.mis_ofertas'))
        return redirect(url_for('solicitudes.nueva'))
    return render_template('auth/registro.html', provincias=provincias, form={},
                           invitado_por=_invitado_por(request.args.get('ref') or session.get('ref')))


def _invitado_por(codigo):
    """(código, 'Ana P.') de quien invita, o None."""
    from services.referidos import resolver_codigo, nombre_privado
    u = resolver_codigo(codigo)
    return (u.codigo_referido, nombre_privado(u)) if u else None


@auth_bp.route('/cambiar-password', methods=['GET', 'POST'])
@login_required
def cambiar_password():
    if request.method == 'POST':
        actual = request.form.get('actual', '')
        nueva  = request.form.get('password', '')
        nueva2 = request.form.get('password2', '')
        if not current_user.check_password(actual):
            flash('La contraseña actual no es correcta', 'danger')
        elif nueva == actual:
            flash('La nueva contraseña debe ser distinta de la actual', 'danger')
        else:
            error = validar_password(nueva, nueva2)
            if error:
                flash(error, 'danger')
            else:
                current_user.set_password(nueva)
                db.session.commit()
                flash('✅ Contraseña actualizada', 'success')
                return redirect(_destino_por_rol(current_user))
    return render_template('auth/cambiar_password.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    # Limpia todo (mensajes pendientes, token CSRF...): el siguiente que use el navegador empieza de cero
    session.clear()
    return redirect(url_for('main.index'))
