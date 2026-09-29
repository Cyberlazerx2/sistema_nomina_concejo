from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from decimal import Decimal
import datetime
import json
from app.database import get_db_connection

organizacion_bp = Blueprint('organizacion', __name__)

ROLES_PERMITIDOS = ['directora_rrhh', 'tecnico_informatica']

def verificar_acceso():
    """Valida la sesion activa y la pertenencia a los roles autorizados."""
    if 'usuario_id' not in session or session.get('rol') not in ROLES_PERMITIDOS:
        return False
    return True

# -------------------------------------------------------------------------
# 1. LISTAR DEPARTAMENTOS
# -------------------------------------------------------------------------
@organizacion_bp.route('/departamentos')
def departamentos():
    if not verificar_acceso():
        flash('Acceso denegado: Se requieren permisos directivos o de soporte técnico.', 'danger')
        return redirect(url_for('auth.dashboard'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            sql = """
                SELECT d.departamento_id, d.nombre, d.activo,
                       COUNT(c.cargo_id) AS total_cargos
                FROM departamento d
                LEFT JOIN cargo c ON d.departamento_id = c.departamento_id
                GROUP BY d.departamento_id, d.nombre, d.activo
                ORDER BY d.nombre ASC;
            """
            cursor.execute(sql)
            lista_deptos = cursor.fetchall()
            return render_template('organizacion_departamentos.html', departamentos=lista_deptos)
    finally:
        conexion.close()

# -------------------------------------------------------------------------
# 2. CREAR DEPARTAMENTO
# -------------------------------------------------------------------------
@organizacion_bp.route('/departamentos/nuevo', methods=['GET', 'POST'])
def nuevo_departamento():
    if not verificar_acceso():
        flash('Acceso denegado: No tiene autorización para crear dependencias.', 'danger')
        return redirect(url_for('organizacion.departamentos'))

    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()

        if not nombre:
            flash('El nombre del departamento es obligatorio.', 'warning')
            return render_template('organizacion_departamento_form.html')

        conexion = get_db_connection()
        try:
            with conexion.cursor() as cursor:
                # Validar unicidad del departamento
                cursor.execute("SELECT departamento_id FROM departamento WHERE nombre = %s;", (nombre,))
                if cursor.fetchone():
                    flash(f"El departamento '{nombre}' ya se encuentra registrado.", 'warning')
                    return render_template('organizacion_departamento_form.html')

                # Insercion del departamento
                sql_insert = "INSERT INTO departamento (nombre, activo) VALUES (%s, true);"
                cursor.execute(sql_insert, (nombre,))
                nuevo_id = cursor.lastrowid

                # Auditoria en bitacora
                sql_bitacora = """
                    INSERT INTO bitacora (usuario_id, tabla, registro_id, accion, valor_previo, valor_nuevo, fecha_hora, ip)
                    VALUES (%s, 'departamento', %s, 'insertar', NULL, %s, %s, %s);
                """
                datos_nuevos = {'departamento_id': nuevo_id, 'nombre': nombre, 'activo': True}
                cursor.execute(sql_bitacora, (
                    session['usuario_id'],
                    nuevo_id,
                    json.dumps(datos_nuevos, default=str),
                    datetime.datetime.now(),
                    request.remote_addr
                ))

                conexion.commit()
                flash(f"Departamento '{nombre}' creado con éxito.", 'success')
                return redirect(url_for('organizacion.departamentos'))
        except Exception as e:
            conexion.rollback()
            flash(f'Error al registrar departamento: {e}', 'danger')
            return redirect(url_for('organizacion.departamentos'))
        finally:
            conexion.close()

    return render_template('organizacion_departamento_form.html')

# -------------------------------------------------------------------------
# 3. LISTAR CARGOS CON SU DEPARTAMENTO
# -------------------------------------------------------------------------
@organizacion_bp.route('/cargos')
def cargos():
    if not verificar_acceso():
        flash('Acceso denegado: No tiene autorización para consultar los cargos del RAC.', 'danger')
        return redirect(url_for('auth.dashboard'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            sql = """
                SELECT c.cargo_id, c.nombre, c.sueldo_base, c.activo,
                       d.departamento_id, d.nombre AS departamento_nombre
                FROM cargo c
                INNER JOIN departamento d ON c.departamento_id = d.departamento_id
                ORDER BY d.nombre ASC, c.nombre ASC;
            """
            cursor.execute(sql)
            lista_cargos = cursor.fetchall()
            return render_template('organizacion_cargos.html', cargos=lista_cargos)
    finally:
        conexion.close()

# -------------------------------------------------------------------------
# 4. CREAR CARGO
# -------------------------------------------------------------------------
@organizacion_bp.route('/cargos/nuevo', methods=['GET', 'POST'])
def nuevo_cargo():
    if not verificar_acceso():
        flash('Acceso denegado: No tiene autorización para crear cargos.', 'danger')
        return redirect(url_for('organizacion.cargos'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            if request.method == 'POST':
                nombre = request.form.get('nombre', '').strip()
                departamento_id = request.form.get('departamento_id')
                sueldo_base_raw = request.form.get('sueldo_base', '').strip()

                if not nombre or not departamento_id or not sueldo_base_raw:
                    flash('Todos los campos del cargo son obligatorios.', 'warning')
                    cursor.execute("SELECT departamento_id, nombre FROM departamento WHERE activo = true ORDER BY nombre ASC;")
                    departamentos_activos = cursor.fetchall()
                    return render_template('organizacion_cargo_form.html', modo='crear', departamentos=departamentos_activos)

                try:
                    sueldo_base = Decimal(sueldo_base_raw)
                except Exception:
                    flash('El sueldo base de referencia debe ser un valor numérico válido.', 'danger')
                    cursor.execute("SELECT departamento_id, nombre FROM departamento WHERE activo = true ORDER BY nombre ASC;")
                    departamentos_activos = cursor.fetchall()
                    return render_template('organizacion_cargo_form.html', modo='crear', departamentos=departamentos_activos)

                sql_insert = """
                    INSERT INTO cargo (departamento_id, nombre, sueldo_base, activo)
                    VALUES (%s, %s, %s, true);
                """
                cursor.execute(sql_insert, (departamento_id, nombre, sueldo_base))
                nuevo_id = cursor.lastrowid

                # Auditoria en bitacora
                sql_bitacora = """
                    INSERT INTO bitacora (usuario_id, tabla, registro_id, accion, valor_previo, valor_nuevo, fecha_hora, ip)
                    VALUES (%s, 'cargo', %s, 'insertar', NULL, %s, %s, %s);
                """
                datos_nuevos = {
                    'cargo_id': nuevo_id,
                    'departamento_id': departamento_id,
                    'nombre': nombre,
                    'sueldo_base': str(sueldo_base),
                    'activo': True
                }
                cursor.execute(sql_bitacora, (
                    session['usuario_id'],
                    nuevo_id,
                    json.dumps(datos_nuevos, default=str),
                    datetime.datetime.now(),
                    request.remote_addr
                ))

                conexion.commit()
                flash(f"Cargo '{nombre}' creado con éxito.", 'success')
                return redirect(url_for('organizacion.cargos'))

            cursor.execute("SELECT departamento_id, nombre FROM departamento WHERE activo = true ORDER BY nombre ASC;")
            departamentos_activos = cursor.fetchall()
            return render_template('organizacion_cargo_form.html', modo='crear', departamentos=departamentos_activos)
    except Exception as e:
        conexion.rollback()
        flash(f'Error al crear cargo: {e}', 'danger')
        return redirect(url_for('organizacion.cargos'))
    finally:
        conexion.close()

# -------------------------------------------------------------------------
# 5. EDITAR CARGO EXISTENTE
# -------------------------------------------------------------------------
@organizacion_bp.route('/cargos/<int:id>/editar', methods=['GET', 'POST'])
def editar_cargo(id):
    if not verificar_acceso():
        flash('Acceso denegado: No tiene autorización para modificar cargos.', 'danger')
        return redirect(url_for('organizacion.cargos'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            cursor.execute("SELECT * FROM cargo WHERE cargo_id = %s;", (id,))
            valor_previo = cursor.fetchone()

            if not valor_previo:
                flash('El cargo solicitado no existe.', 'warning')
                return redirect(url_for('organizacion.cargos'))

            if request.method == 'POST':
                nombre = request.form.get('nombre', '').strip()
                departamento_id = request.form.get('departamento_id')
                sueldo_base_raw = request.form.get('sueldo_base', '').strip()

                if not nombre or not departamento_id or not sueldo_base_raw:
                    flash('Todos los campos son obligatorios.', 'warning')
                    cursor.execute("SELECT departamento_id, nombre FROM departamento WHERE activo = true ORDER BY nombre ASC;")
                    deptos = cursor.fetchall()
                    return render_template('organizacion_cargo_form.html', modo='editar', cargo=valor_previo, departamentos=deptos)

                try:
                    sueldo_base = Decimal(sueldo_base_raw)
                except Exception:
                    flash('El sueldo base de referencia debe ser numérico.', 'danger')
                    cursor.execute("SELECT departamento_id, nombre FROM departamento WHERE activo = true ORDER BY nombre ASC;")
                    deptos = cursor.fetchall()
                    return render_template('organizacion_cargo_form.html', modo='editar', cargo=valor_previo, departamentos=deptos)

                sql_update = """
                    UPDATE cargo 
                    SET departamento_id = %s, nombre = %s, sueldo_base = %s
                    WHERE cargo_id = %s;
                """
                cursor.execute(sql_update, (departamento_id, nombre, sueldo_base, id))

                # Obtener estado posterior exacto
                cursor.execute("SELECT * FROM cargo WHERE cargo_id = %s;", (id,))
                valor_nuevo = cursor.fetchone()

                # Auditoria en bitacora
                sql_bitacora = """
                    INSERT INTO bitacora (usuario_id, tabla, registro_id, accion, valor_previo, valor_nuevo, fecha_hora, ip)
                    VALUES (%s, 'cargo', %s, 'modificar', %s, %s, %s, %s);
                """
                cursor.execute(sql_bitacora, (
                    session['usuario_id'],
                    id,
                    json.dumps(valor_previo, default=str),
                    json.dumps(valor_nuevo, default=str),
                    datetime.datetime.now(),
                    request.remote_addr
                ))

                conexion.commit()
                flash(f"Cargo '{nombre}' actualizado y registrado en auditoría.", 'success')
                return redirect(url_for('organizacion.cargos'))

            cursor.execute("SELECT departamento_id, nombre FROM departamento WHERE activo = true ORDER BY nombre ASC;")
            departamentos_activos = cursor.fetchall()
            return render_template('organizacion_cargo_form.html', modo='editar', cargo=valor_previo, departamentos=departamentos_activos)
    except Exception as e:
        conexion.rollback()
        flash(f'Error al modificar cargo: {e}', 'danger')
        return redirect(url_for('organizacion.cargos'))
    finally:
        conexion.close()

# -------------------------------------------------------------------------
# 6. DESACTIVAR CARGO (Baja logica inalterable)
# -------------------------------------------------------------------------
@organizacion_bp.route('/cargos/<int:id>/desactivar', methods=['POST'])
def desactivar_cargo(id):
    if not verificar_acceso():
        flash('Acceso denegado: No tiene autorización para desactivar cargos.', 'danger')
        return redirect(url_for('organizacion.cargos'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            cursor.execute("SELECT * FROM cargo WHERE cargo_id = %s AND activo = true;", (id,))
            valor_previo = cursor.fetchone()

            if not valor_previo:
                flash('El cargo no existe o ya se encuentra inactivo.', 'warning')
                return redirect(url_for('organizacion.cargos'))

            # Desactivacion logica obligatoria (preserva relaciones historicas de nomina y trabajadores)
            cursor.execute("UPDATE cargo SET activo = false WHERE cargo_id = %s;", (id,))

            valor_nuevo = dict(valor_previo)
            valor_nuevo['activo'] = False

            # Auditoria en bitacora
            sql_bitacora = """
                INSERT INTO bitacora (usuario_id, tabla, registro_id, accion, valor_previo, valor_nuevo, fecha_hora, ip)
                VALUES (%s, 'cargo', %s, 'eliminar', %s, %s, %s, %s);
            """
            cursor.execute(sql_bitacora, (
                session['usuario_id'],
                id,
                json.dumps(valor_previo, default=str),
                json.dumps(valor_nuevo, default=str),
                datetime.datetime.now(),
                request.remote_addr
            ))

            conexion.commit()
            flash(f"Cargo '{valor_previo['nombre']}' desactivado correctamente.", 'info')
    except Exception as e:
        conexion.rollback()
        flash(f'Error al desactivar el cargo: {e}', 'danger')
    finally:
        conexion.close()

    return redirect(url_for('organizacion.cargos'))