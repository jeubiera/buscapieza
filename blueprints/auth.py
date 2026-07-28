from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from models import db, Usuario, Provincia

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET','POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    if request.method == 'POST':
        email = request.form.get('email','').lower().strip()
        pw    = request.form.get('password','')
        user  = Usuario.query.filter_by(email=email, activo=True).first()
        if user and user.check_password(pw):
            login_user(user, remember=True)
            next_page = request.args.get('next')
            if user.rol == 'admin':
                return redirect(next_page or url_for('admin.dashboard'))
            elif user.rol == 'proveedor':
                return redirect(next_page or url_for('ofertas.mis_ofertas'))
            else:
                return redirect(next_page or url_for('solicitudes.mis_solicitudes'))
        flash('Correo o contraseña incorrectos', 'danger')
    return render_template('auth/login.html')

@auth_bp.route('/registro', methods=['GET','POST'])
def registro():
    provincias = Provincia.query.order_by(Provincia.nombre).all()
    if request.method == 'POST':
        rol      = request.form.get('rol','cliente')
        nombre   = request.form.get('nombre','').strip()
        email    = request.form.get('email','').lower().strip()
        telefono = request.form.get('telefono','').strip()
        pw       = request.form.get('password','')
        prov_id  = request.form.get('provincia_id')
        empresa  = request.form.get('empresa','').strip()
        whatsapp = request.form.get('whatsapp','').strip() or telefono

        if Usuario.query.filter_by(email=email).first():
            flash('Este correo ya está registrado', 'danger')
            return render_template('auth/registro.html', provincias=provincias)

        user = Usuario(
            nombre=nombre, email=email, telefono=telefono,
            rol=rol, provincia_id=prov_id or None,
            empresa=empresa, whatsapp=whatsapp
        )
        user.set_password(pw)
        db.session.add(user)
        db.session.commit()
        login_user(user, remember=True)
        flash(f'¡Bienvenido, {nombre}!', 'success')
        if rol == 'proveedor':
            return redirect(url_for('ofertas.mis_ofertas'))
        return redirect(url_for('solicitudes.nueva'))
    return render_template('auth/registro.html', provincias=provincias)

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('main.index'))
