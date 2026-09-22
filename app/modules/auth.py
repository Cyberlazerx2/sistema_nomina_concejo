from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import check_password_hash
import datetime
from app.database import get_db_connection

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    # Si el usuario ya inicio sesion previamente, no necesita volver a loguearse
    if 'usuario_id' in session:
        return redirect(url_for('auth.dashboard'))

    if request.method == 'POST':
        nombre_usuario = request.form.get('nombre_usuario', '').strip()
        clave = request.form.get('clave', '').strip()

        if not nombre_usuario or not clave:
            flash('Por favor ingrese usuario y contraseña.', 'danger')
            return render_template('login.html')

        conexion = get_db_connection()
        try:
            with conexion.cursor() as cursor:
                # Buscamos el usuario y unimos con su rol correspondiente
                sql = """
                    SELECT u.usuario_id, u.nombre_usuario, u.clave_hash, u.activo, r.nombre AS rol_nombre
                    FROM usuario u
                    INNER JOIN rol r ON u.rol_id = r.rol_id
                    WHERE u.nombre_usuario = %s;
                """
                cursor.execute(sql, (nombre_usuario,))
                usuario = cursor.fetchone()

                # 1. Validar si el usuario existe y si esta activo
                if not usuario or not usuario['activo']:
                    flash('Credenciales incorrectas o usuario deshabilitado.', 'danger')
                    return render_template('login.html')

                # 2. Validar contraseña con el hash matematico
                if not check_password_hash(usuario['clave_hash'], clave):
                    flash('Credenciales incorrectas o usuario deshabilitado.', 'danger')
                    return render_template('login.html')

                # 3. Actualizar fecha de ultimo acceso en la BD
                sql_acceso = "UPDATE usuario SET ultimo_acceso = %s WHERE usuario_id = %s;"
                cursor.execute(sql_acceso, (datetime.datetime.now(), usuario['usuario_id']))
                conexion.commit()

                # 4. Guardar datos en la sesion web
                session['usuario_id'] = usuario['usuario_id']
                session['nombre_usuario'] = usuario['nombre_usuario']
                session['rol'] = usuario['rol_nombre']

                flash(f'Bienvenido, {usuario["nombre_usuario"]}', 'success')
                return redirect(url_for('auth.dashboard'))

        except Exception as e:
            flash(f'Error al conectar con el servidor: {e}', 'danger')
        finally:
            conexion.close()

    return render_template('login.html')

@auth_bp.route('/dashboard')
def dashboard():
    # Proteccion de ruta: solo pasa quien tenga sesion activa
    if 'usuario_id' not in session:
        flash('Debe iniciar sesión para acceder al sistema.', 'warning')
        return redirect(url_for('auth.login'))

    return render_template('dashboard.html', 
                           usuario=session.get('nombre_usuario'), 
                           rol=session.get('rol'))

@auth_bp.route('/logout')
def logout():
    # Limpiar todos los datos de sesion
    session.clear()
    flash('Sesión finalizada correctamente.', 'info')
    return redirect(url_for('auth.login'))