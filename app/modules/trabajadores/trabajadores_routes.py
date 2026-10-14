from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash
import datetime
import json
from app.database import get_db_connection

trabajadores_bp = Blueprint('trabajadores', __name__)

TIPOS_PERSONAL = [
    ('alto_nivel', 'Alto Nivel (Concejales)'),
    ('libre_remocion', 'Libre Nombramiento y Remoción'),
    ('empleado_fijo', 'Empleado Fijo'),
    ('empleado_contratado', 'Empleado Contratado'),
    ('obrero_fijo', 'Obrero Fijo'),
    ('obrero_contratado', 'Obrero Contratado')
]

NIVELES_INSTRUCCION = ['Bachiller', 'TSU', 'Licenciado', 'Ingeniero', 'Especialista', 'Magister', 'Doctor']

# -------------------------------------------------------------------------
# 1. LISTAR TRABAJADORES ACTIVOS
# -------------------------------------------------------------------------
@trabajadores_bp.route('/')
def listar():
    roles_permitidos = ['analista_rrhh', 'directora_rrhh', 'tecnico_informatica']
    if 'usuario_id' not in session or session.get('rol') not in roles_permitidos:
        flash('Acceso denegado: No tiene permisos para consultar la nómina de trabajadores.', 'danger')
        return redirect(url_for('auth.dashboard'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            # JOIN con cargo y departamento para recuperar la adscripción real
            sql = """
                SELECT t.*, c.nombre AS cargo_nombre, d.nombre AS departamento_nombre,
                       u.usuario_id AS cuenta_usuario_id, u.nombre_usuario
                FROM trabajador t
                INNER JOIN cargo c ON t.cargo_id = c.cargo_id
                LEFT JOIN departamento d ON c.departamento_id = d.departamento_id
                LEFT JOIN usuario u ON t.trabajador_id = u.trabajador_id
                WHERE t.activo = true
                ORDER BY t.tipo_personal ASC, t.apellidos ASC, t.nombres ASC;
            """
            cursor.execute(sql)
            trabajadores = cursor.fetchall()
            return render_template('trabajadores/trabajadores_lista.html', trabajadores=trabajadores)
    finally:
        conexion.close()

# -------------------------------------------------------------------------
# 2. CREAR NUEVO TRABAJADOR
# -------------------------------------------------------------------------
@trabajadores_bp.route('/nuevo', methods=['GET', 'POST'])
def nuevo():
    roles_permitidos = ['directora_rrhh', 'tecnico_informatica']
    if 'usuario_id' not in session or session.get('rol') not in roles_permitidos:
        flash('Acceso denegado: Solo Directora de RRHH o Informática pueden dar de alta personal.', 'danger')
        return redirect(url_for('trabajadores.listar'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            if request.method == 'POST':
                cedula = request.form.get('cedula', '').strip()
                nombres = request.form.get('nombres', '').strip()
                apellidos = request.form.get('apellidos', '').strip()
                fecha_nacimiento = request.form.get('fecha_nacimiento') or None
                sexo = request.form.get('sexo')
                telefono = request.form.get('telefono', '').strip()
                correo = request.form.get('correo', '').strip()
                direccion = request.form.get('direccion', '').strip()
                cargo_id = request.form.get('cargo_id')
                tipo_personal = request.form.get('tipo_personal')
                fecha_ingreso = request.form.get('fecha_ingreso')
                sueldo_base = request.form.get('sueldo_base')
                hijos = int(request.form.get('hijos', 0) or 0)
                nivel_instruccion = request.form.get('nivel_instruccion')
                banco = request.form.get('banco', '').strip()
                numero_cuenta = request.form.get('numero_cuenta', '').strip()

                cursor.execute("SELECT trabajador_id FROM trabajador WHERE cedula = %s;", (cedula,))
                if cursor.fetchone():
                    flash(f'La cédula {cedula} ya se encuentra registrada en el sistema.', 'warning')
                    cursor.execute("SELECT cargo_id, nombre, sueldo_base FROM cargo WHERE activo = true ORDER BY nombre ASC;")
                    cargos = cursor.fetchall()
                    return render_template('trabajadores/trabajadores_form.html', modo='crear', trabajador=None,
                                           cargos=cargos, tipos_personal=TIPOS_PERSONAL, niveles=NIVELES_INSTRUCCION)

                sql_insert = """
                    INSERT INTO trabajador (
                        cedula, nombres, apellidos, fecha_nacimiento, sexo, telefono, correo,
                        direccion, cargo_id, tipo_personal, fecha_ingreso, sueldo_base, hijos,
                        nivel_instruccion, banco, numero_cuenta, activo
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, true);
                """
                cursor.execute(sql_insert, (
                    cedula, nombres, apellidos, fecha_nacimiento, sexo, telefono, correo,
                    direccion, cargo_id, tipo_personal, fecha_ingreso, sueldo_base, hijos,
                    nivel_instruccion, banco, numero_cuenta
                ))
                nuevo_id = cursor.lastrowid

                sql_bitacora = """
                    INSERT INTO bitacora (usuario_id, tabla, registro_id, accion, valor_previo, valor_nuevo, fecha_hora, ip)
                    VALUES (%s, 'trabajador', %s, 'insertar', NULL, %s, %s, %s);
                """
                datos_nuevos = {
                    'trabajador_id': nuevo_id, 'cedula': cedula, 'nombres': nombres,
                    'apellidos': apellidos, 'cargo_id': cargo_id, 'tipo_personal': tipo_personal,
                    'sueldo_base': str(sueldo_base), 'fecha_ingreso': str(fecha_ingreso)
                }
                cursor.execute(sql_bitacora, (
                    session['usuario_id'], nuevo_id, json.dumps(datos_nuevos, default=str),
                    datetime.datetime.now(), request.remote_addr
                ))

                conexion.commit()
                flash(f'Trabajador {nombres} {apellidos} incorporado con éxito.', 'success')
                return redirect(url_for('trabajadores.listar'))

            cursor.execute("SELECT cargo_id, nombre, sueldo_base FROM cargo WHERE activo = true ORDER BY nombre ASC;")
            cargos = cursor.fetchall()
            return render_template('trabajadores/trabajadores_form.html', modo='crear', trabajador=None,
                                   cargos=cargos, tipos_personal=TIPOS_PERSONAL, niveles=NIVELES_INSTRUCCION)
    except Exception as e:
        conexion.rollback()
        flash(f'Error al registrar trabajador: {e}', 'danger')
        return redirect(url_for('trabajadores.listar'))
    finally:
        conexion.close()

# -------------------------------------------------------------------------
# 3. EDITAR TRABAJADOR EXISTENTE
# -------------------------------------------------------------------------
@trabajadores_bp.route('/<int:id>/editar', methods=['GET', 'POST'])
def editar(id):
    roles_permitidos = ['directora_rrhh', 'tecnico_informatica']
    if 'usuario_id' not in session or session.get('rol') not in roles_permitidos:
        flash('Acceso denegado: No cuenta con permisos para modificar expedientes laborales.', 'danger')
        return redirect(url_for('trabajadores.listar'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            cursor.execute("SELECT * FROM trabajador WHERE trabajador_id = %s;", (id,))
            valor_previo = cursor.fetchone()

            if not valor_previo:
                flash('El trabajador solicitado no existe.', 'warning')
                return redirect(url_for('trabajadores.listar'))

            if request.method == 'POST':
                cedula = request.form.get('cedula', '').strip()
                nombres = request.form.get('nombres', '').strip()
                apellidos = request.form.get('apellidos', '').strip()
                fecha_nacimiento = request.form.get('fecha_nacimiento') or None
                sexo = request.form.get('sexo')
                telefono = request.form.get('telefono', '').strip()
                correo = request.form.get('correo', '').strip()
                direccion = request.form.get('direccion', '').strip()
                cargo_id = request.form.get('cargo_id')
                tipo_personal = request.form.get('tipo_personal')
                fecha_ingreso = request.form.get('fecha_ingreso')
                sueldo_base = request.form.get('sueldo_base')
                hijos = int(request.form.get('hijos', 0) or 0)
                nivel_instruccion = request.form.get('nivel_instruccion')
                banco = request.form.get('banco', '').strip()
                numero_cuenta = request.form.get('numero_cuenta', '').strip()

                sql_update = """
                    UPDATE trabajador SET 
                        cedula = %s, nombres = %s, apellidos = %s, fecha_nacimiento = %s,
                        sexo = %s, telefono = %s, correo = %s, direccion = %s,
                        cargo_id = %s, tipo_personal = %s, fecha_ingreso = %s,
                        sueldo_base = %s, hijos = %s, nivel_instruccion = %s,
                        banco = %s, numero_cuenta = %s
                    WHERE trabajador_id = %s;
                """
                cursor.execute(sql_update, (
                    cedula, nombres, apellidos, fecha_nacimiento, sexo, telefono, correo,
                    direccion, cargo_id, tipo_personal, fecha_ingreso, sueldo_base, hijos,
                    nivel_instruccion, banco, numero_cuenta, id
                ))

                cursor.execute("SELECT * FROM trabajador WHERE trabajador_id = %s;", (id,))
                valor_nuevo = cursor.fetchone()

                sql_bitacora = """
                    INSERT INTO bitacora (usuario_id, tabla, registro_id, accion, valor_previo, valor_nuevo, fecha_hora, ip)
                    VALUES (%s, 'trabajador', %s, 'modificar', %s, %s, %s, %s);
                """
                cursor.execute(sql_bitacora, (
                    session['usuario_id'], id,
                    json.dumps(valor_previo, default=str),
                    json.dumps(valor_nuevo, default=str),
                    datetime.datetime.now(), request.remote_addr
                ))

                conexion.commit()
                flash(f'Expediente de {nombres} {apellidos} actualizado con éxito.', 'success')
                return redirect(url_for('trabajadores.listar'))

            cursor.execute("SELECT cargo_id, nombre, sueldo_base FROM cargo WHERE activo = true ORDER BY nombre ASC;")
            cargos = cursor.fetchall()
            return render_template('trabajadores/trabajadores_form.html', modo='editar', trabajador=valor_previo,
                                   cargos=cargos, tipos_personal=TIPOS_PERSONAL, niveles=NIVELES_INSTRUCCION)
    except Exception as e:
        conexion.rollback()
        flash(f'Error al modificar trabajador: {e}', 'danger')
        return redirect(url_for('trabajadores.listar'))
    finally:
        conexion.close()

# -------------------------------------------------------------------------
# 4. DESACTIVAR TRABAJADOR (Baja Lógica)
# -------------------------------------------------------------------------
@trabajadores_bp.route('/<int:id>/desactivar', methods=['POST'])
def desactivar(id):
    roles_permitidos = ['directora_rrhh', 'tecnico_informatica']
    if 'usuario_id' not in session or session.get('rol') not in roles_permitidos:
        flash('Acceso denegado.', 'danger')
        return redirect(url_for('trabajadores.listar'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            cursor.execute("SELECT * FROM trabajador WHERE trabajador_id = %s AND activo = true;", (id,))
            valor_previo = cursor.fetchone()

            if not valor_previo:
                flash('El trabajador no existe o ya está inactivo.', 'warning')
                return redirect(url_for('trabajadores.listar'))

            hoy = datetime.date.today()
            cursor.execute("UPDATE trabajador SET activo = false, fecha_egreso = %s WHERE trabajador_id = %s;", (hoy, id))
            cursor.execute("UPDATE usuario SET activo = false WHERE trabajador_id = %s;", (id,))

            valor_nuevo = {'activo': False, 'fecha_egreso': str(hoy)}
            sql_bitacora = """
                INSERT INTO bitacora (usuario_id, tabla, registro_id, accion, valor_previo, valor_nuevo, fecha_hora, ip)
                VALUES (%s, 'trabajador', %s, 'eliminar', %s, %s, %s, %s);
            """
            cursor.execute(sql_bitacora, (
                session['usuario_id'], id,
                json.dumps(valor_previo, default=str),
                json.dumps(valor_nuevo, default=str),
                datetime.datetime.now(), request.remote_addr
            ))

            conexion.commit()
            flash(f"Trabajador {valor_previo['nombres']} {valor_previo['apellidos']} egresado con éxito.", 'info')
    except Exception as e:
        conexion.rollback()
        flash(f'Error al procesar egreso: {e}', 'danger')
    finally:
        conexion.close()

    return redirect(url_for('trabajadores.listar'))

# -------------------------------------------------------------------------
# 5. BANDEJA Y PROCESAMIENTO DE SOLICITUDES DE PERFIL
# -------------------------------------------------------------------------
@trabajadores_bp.route('/solicitudes')
def solicitudes():
    if 'usuario_id' not in session or session.get('rol') not in ['directora_rrhh', 'analista_rrhh', 'tecnico_informatica']:
        flash('Acceso restringido.', 'danger')
        return redirect(url_for('auth.dashboard'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            sql = """
                SELECT s.solicitud_id, s.trabajador_id, s.campo, s.valor_actual, 
                       s.valor_nuevo, s.estado, s.fecha_solicitud, s.fecha_respuesta, 
                       s.motivo_rechazo, t.cedula, t.nombres, t.apellidos,
                       c.nombre AS cargo_nombre, d.nombre AS departamento_nombre
                FROM solicitud_cambio_perfil s
                INNER JOIN trabajador t ON s.trabajador_id = t.trabajador_id
                LEFT JOIN cargo c ON t.cargo_id = c.cargo_id
                LEFT JOIN departamento d ON c.departamento_id = d.departamento_id
                ORDER BY s.solicitud_id DESC;
            """
            cursor.execute(sql)
            todas = cursor.fetchall()
            pendientes = [s for s in todas if s['estado'] == 'pendiente']
            procesadas = [s for s in todas if s['estado'] != 'pendiente']
            return render_template('trabajadores/trabajadores_solicitudes.html', pendientes=pendientes, procesadas=procesadas)
    finally:
        conexion.close()

@trabajadores_bp.route('/solicitudes/<int:id>/procesar', methods=['POST'])
def procesar_solicitud(id):
    if 'usuario_id' not in session or session.get('rol') not in ['directora_rrhh', 'analista_rrhh']:
        flash('Acceso no autorizado.', 'danger')
        return redirect(url_for('trabajadores.solicitudes'))

    accion = request.form.get('accion')
    motivo = request.form.get('motivo_rechazo', '').strip()

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            cursor.execute("SELECT * FROM solicitud_cambio_perfil WHERE solicitud_id = %s;", (id,))
            solicitud = cursor.fetchone()

            if not solicitud or solicitud['estado'] != 'pendiente':
                flash('La solicitud ya fue procesada o no existe.', 'warning')
                return redirect(url_for('trabajadores.solicitudes'))

            ahora = datetime.datetime.now()
            campos_permitidos = ['telefono', 'correo', 'direccion']

            if accion == 'aprobar':
                campo = solicitud['campo'].lower().strip()
                if campo in campos_permitidos:
                    sql_up = f"UPDATE trabajador SET {campo} = %s WHERE trabajador_id = %s;"
                    cursor.execute(sql_up, (solicitud['valor_nuevo'], solicitud['trabajador_id']))
                    cursor.execute("UPDATE solicitud_cambio_perfil SET estado = 'aprobada', fecha_respuesta = %s WHERE solicitud_id = %s;", (ahora, id))
                    conexion.commit()
                    flash(f"Solicitud #{id} APROBADA. Expediente actualizado con el nuevo {campo}.", 'success')
                else:
                    flash('Campo no autorizado.', 'danger')

            elif accion == 'rechazar':
                cursor.execute("""
                    UPDATE solicitud_cambio_perfil
                    SET estado = 'rechazada', fecha_respuesta = %s, motivo_rechazo = %s
                    WHERE solicitud_id = %s;
                """, (ahora, motivo or 'Rechazada por la Dirección de Recursos Humanos.', id))
                conexion.commit()
                flash(f"Solicitud #{id} rechazada.", 'warning')
    except Exception as e:
        conexion.rollback()
        flash(f'Error al procesar: {e}', 'danger')
    finally:
        conexion.close()

    return redirect(url_for('trabajadores.solicitudes'))

# -------------------------------------------------------------------------
# RRHH: Bandeja de Constancias de Trabajo
# -------------------------------------------------------------------------
@trabajadores_bp.route('/constancias')
def constancias_admin():
    roles_permitidos = ['directora_rrhh', 'analista_rrhh', 'tecnico_informatica']
    if 'usuario_id' not in session or session.get('rol') not in roles_permitidos:
        flash('Acceso denegado a la gestión de constancias.', 'danger')
        return redirect(url_for('auth.dashboard'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            sql = """
                SELECT sc.*, t.cedula, t.nombres, t.apellidos, c.nombre AS cargo_nombre
                FROM solicitud_constancia sc
                INNER JOIN trabajador t ON sc.trabajador_id = t.trabajador_id
                INNER JOIN cargo c ON t.cargo_id = c.cargo_id
                ORDER BY sc.constancia_id DESC;
            """
            cursor.execute(sql)
            todas = cursor.fetchall()
            pendientes = [c for c in todas if c['estado'] == 'pendiente']
            emitidas = [c for c in todas if c['estado'] != 'pendiente']

            return render_template('trabajadores/trabajadores_constancias.html', pendientes=pendientes, emitidas=emitidas)
    finally:
        conexion.close()

# -------------------------------------------------------------------------
# RRHH: Emitir o Rechazar Constancia de Trabajo
# -------------------------------------------------------------------------
@trabajadores_bp.route('/constancias/<int:constancia_id>/procesar', methods=['POST'])
def procesar_constancia(constancia_id):
    if 'usuario_id' not in session or session.get('rol') not in ['directora_rrhh', 'analista_rrhh']:
        flash('Acceso no autorizado.', 'danger')
        return redirect(url_for('trabajadores.constancias_admin'))

    accion = request.form.get('accion') # 'emitir' o 'rechazar'
    motivo = request.form.get('motivo_rechazo', '').strip()

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            ahora = datetime.datetime.now()
            if accion == 'emitir':
                # Generar correlativo institucional formal: DTH-CT-YYYY-XXXX
                correlativo = f"DTH-CT-{ahora.year}-{constancia_id:04d}"
                cursor.execute("""
                    UPDATE solicitud_constancia
                    SET estado = 'emitida', correlativo = %s, fecha_emision = %s,
                        emitida_por = %s, motivo_rechazo = NULL
                    WHERE constancia_id = %s;
                """, (correlativo, ahora, session['usuario_id'], constancia_id))
                conexion.commit()
                flash(f'Constancia #{constancia_id} emitida exitosamente con correlativo {correlativo}.', 'success')

            elif accion == 'rechazar':
                cursor.execute("""
                    UPDATE solicitud_constancia
                    SET estado = 'rechazada', fecha_emision = %s,
                        emitida_por = %s, motivo_rechazo = %s
                    WHERE constancia_id = %s;
                """, (ahora, session['usuario_id'], motivo or 'Rechazada por la Dirección de Talento Humano.', constancia_id))
                conexion.commit()
                flash(f'Solicitud de constancia #{constancia_id} rechazada.', 'warning')
    finally:
        conexion.close()

    return redirect(url_for('trabajadores.constancias_admin'))