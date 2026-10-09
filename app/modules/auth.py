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
    if 'usuario_id' not in session:
        return redirect(url_for('auth.login'))

    rol = session.get('rol')

    # Si es trabajador, entra a su portal integral
    if rol == 'trabajador':
        return redirect(url_for('portal.inicio'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            # 1. Total de trabajadores activos en nómina
            cursor.execute("SELECT COUNT(*) AS total FROM trabajador WHERE activo = true;")
            total_trabajadores = cursor.fetchone()['total']

            # 2. Nóminas pendientes por validar o aprobar
            cursor.execute("""
                SELECT COUNT(*) AS total FROM periodo_nomina 
                WHERE estado IN ('borrador', 'revisada');
            """)
            nominas_pendientes = cursor.fetchone()['total']

            # 3. Gasto acumulado en nóminas aprobadas durante el ejercicio fiscal
            cursor.execute("""
                SELECT COALESCE(SUM(total_neto), 0) AS total_gastado,
                       COALESCE(SUM(total_asignaciones), 0) AS total_bruto
                FROM periodo_nomina 
                WHERE estado IN ('aprobada', 'procesada_patria');
            """)
            finanzas = cursor.fetchone()
            total_gastado = finanzas['total_gastado']

            # 4. Conteos específicos para los filtros rápidos de la tabla
            cursor.execute("""
                SELECT 
                    COUNT(*) AS total_todos,
                    SUM(CASE WHEN estado = 'borrador' THEN 1 ELSE 0 END) AS total_borrador,
                    SUM(CASE WHEN estado = 'revisada' THEN 1 ELSE 0 END) AS total_revisada,
                    SUM(CASE WHEN estado = 'aprobada' THEN 1 ELSE 0 END) AS total_aprobada
                FROM periodo_nomina;
            """)
            conteos = cursor.fetchone()

            # 5. Últimas nóminas procesadas (máximo 10)
            cursor.execute("""
                SELECT p.periodo_id, p.descripcion, p.fecha_inicio, p.fecha_fin,
                       p.tipo_nomina, p.periodicidad, p.total_asignaciones,
                       p.total_deducciones, p.total_neto, p.estado
                FROM periodo_nomina p
                ORDER BY p.periodo_id DESC
                LIMIT 10;
            """)
            ultimas_nominas = cursor.fetchall()

            # Contar trabajadores incluidos en cada periodo para la columna "Personal"
            for nom in ultimas_nominas:
                cursor.execute("""
                    SELECT COUNT(*) AS cant FROM nomina_trabajador 
                    WHERE periodo_id = %s;
                """, (nom['periodo_id'],))
                nom['cantidad_trabajadores'] = cursor.fetchone()['cant']
                nom['analista_user'] = 'RRHH'  # Valor por defecto seguro

            return render_template(
                'dashboard.html',
                rol=rol,
                total_trabajadores=total_trabajadores,
                nominas_pendientes=nominas_pendientes,
                total_gastado=total_gastado,
                conteos=conteos,
                nominas=ultimas_nominas
            )
    finally:
        conexion.close()

@auth_bp.route('/logout')
def logout():
    # Limpiar todos los datos de sesion
    session.clear()
    flash('Sesión finalizada correctamente.', 'info')
    return redirect(url_for('auth.login'))