from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from decimal import Decimal, ROUND_HALF_UP
import datetime
import json
from app.database import get_db_connection

trabajadores_bp = Blueprint('trabajadores', __name__)

NIVELES_INSTRUCCION = ['Bachiller', 'TSU', 'Licenciado', 'Ingeniero', 'Especialista', 'Magister', 'Doctor']

def obtener_catalogo_tipos_nomina(cursor):
    """Recupera los tipos de nómina activos directamente desde la base de datos."""
    cursor.execute("SELECT codigo, nombre FROM tipo_nomina WHERE activo = true ORDER BY nombre ASC;")
    return [(t['codigo'], t['nombre']) for t in cursor.fetchall()]

# -------------------------------------------------------------------------
# 1. LISTAR TRABAJADORES ACTIVOS
# -------------------------------------------------------------------------
@trabajadores_bp.route('/')
def listar():
    roles_permitidos = ['analista_rrhh', 'directora_rrhh', 'tecnico_informatica']
    if 'usuario_id' not in session or session.get('rol') not in roles_permitidos:
        flash('Acceso denegado: No tiene permisos para consultar la nómina.', 'danger')
        return redirect(url_for('auth.dashboard'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            sql = """
                SELECT t.*, c.nombre AS cargo_nombre, d.nombre AS departamento_nombre,
                       tn.nombre AS tipo_nomina_nombre,
                       u.usuario_id AS cuenta_usuario_id, u.nombre_usuario
                FROM trabajador t
                INNER JOIN cargo c ON t.cargo_id = c.cargo_id
                LEFT JOIN departamento d ON c.departamento_id = d.departamento_id
                LEFT JOIN tipo_nomina tn ON t.tipo_personal = tn.codigo
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
# 2. ASIGNACIÓN RAC Y PLANTILLA (Modificación rápida de adscripción)
# -------------------------------------------------------------------------
@trabajadores_bp.route('/rac', methods=['GET', 'POST'])
def rac_asignacion():
    roles_permitidos = ['directora_rrhh', 'tecnico_informatica']
    if 'usuario_id' not in session or session.get('rol') not in roles_permitidos:
        flash('Acceso restringido: Solo Dirección de RRHH puede reasignar el RAC.', 'danger')
        return redirect(url_for('auth.dashboard'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            if request.method == 'POST':
                trabajador_id = request.form.get('trabajador_id')
                nuevo_cargo_id = request.form.get('cargo_id')
                nuevo_tipo = request.form.get('tipo_personal')
                nuevo_sueldo = request.form.get('sueldo_base', '').strip()

                cursor.execute("""
                    UPDATE trabajador 
                    SET cargo_id = %s, tipo_personal = %s, sueldo_base = %s 
                    WHERE trabajador_id = %s;
                """, (nuevo_cargo_id, nuevo_tipo, nuevo_sueldo, trabajador_id))
                conexion.commit()
                flash('Asignación RAC y tipo de nómina actualizados exitosamente.', 'success')
                return redirect(url_for('trabajadores.rac_asignacion'))

            cursor.execute("SELECT cargo_id, nombre, sueldo_base FROM cargo WHERE activo = true ORDER BY nombre ASC;")
            cargos = cursor.fetchall()
            tipos_nomina = obtener_catalogo_tipos_nomina(cursor)

            cursor.execute("""
                SELECT t.trabajador_id, t.cedula, t.nombres, t.apellidos, t.tipo_personal,
                       t.sueldo_base, t.cargo_id, c.nombre AS cargo_nombre,
                       d.nombre AS departamento_nombre, tn.nombre AS tipo_nomina_nombre
                FROM trabajador t
                INNER JOIN cargo c ON t.cargo_id = c.cargo_id
                LEFT JOIN departamento d ON c.departamento_id = d.departamento_id
                LEFT JOIN tipo_nomina tn ON t.tipo_personal = tn.codigo
                WHERE t.activo = true
                ORDER BY t.apellidos ASC, t.nombres ASC;
            """)
            plantilla = cursor.fetchall()

            return render_template(
                'trabajadores/trabajadores_rac.html',
                plantilla=plantilla,
                cargos=cargos,
                tipos_nomina=tipos_nomina
            )
    finally:
        conexion.close()

# -------------------------------------------------------------------------
# 3. CREAR NUEVO TRABAJADOR
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
            tipos_personal = obtener_catalogo_tipos_nomina(cursor)

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
                                           cargos=cargos, tipos_personal=tipos_personal, niveles=NIVELES_INSTRUCCION)

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
                conexion.commit()
                flash(f'Trabajador {nombres} {apellidos} incorporado con éxito.', 'success')
                return redirect(url_for('trabajadores.listar'))

            cursor.execute("SELECT cargo_id, nombre, sueldo_base FROM cargo WHERE activo = true ORDER BY nombre ASC;")
            cargos = cursor.fetchall()
            return render_template('trabajadores/trabajadores_form.html', modo='crear', trabajador=None,
                                   cargos=cargos, tipos_personal=tipos_personal, niveles=NIVELES_INSTRUCCION)
    finally:
        conexion.close()

# -------------------------------------------------------------------------
# 4. EDITAR TRABAJADOR EXISTENTE
# -------------------------------------------------------------------------
@trabajadores_bp.route('/<int:id>/editar', methods=['GET', 'POST'])
def editar(id):
    roles_permitidos = ['directora_rrhh', 'tecnico_informatica']
    if 'usuario_id' not in session or session.get('rol') not in roles_permitidos:
        flash('Acceso denegado.', 'danger')
        return redirect(url_for('trabajadores.listar'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            cursor.execute("SELECT * FROM trabajador WHERE trabajador_id = %s;", (id,))
            valor_previo = cursor.fetchone()

            if not valor_previo:
                flash('El trabajador solicitado no existe.', 'warning')
                return redirect(url_for('trabajadores.listar'))

            tipos_personal = obtener_catalogo_tipos_nomina(cursor)

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
                conexion.commit()
                flash(f'Expediente de {nombres} {apellidos} actualizado con éxito.', 'success')
                return redirect(url_for('trabajadores.listar'))

            cursor.execute("SELECT cargo_id, nombre, sueldo_base FROM cargo WHERE activo = true ORDER BY nombre ASC;")
            cargos = cursor.fetchall()
            return render_template('trabajadores/trabajadores_form.html', modo='editar', trabajador=valor_previo,
                                   cargos=cargos, tipos_personal=tipos_personal, niveles=NIVELES_INSTRUCCION)
    finally:
        conexion.close()

# -------------------------------------------------------------------------
# 5. DESACTIVAR TRABAJADOR (Baja Lógica)
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
# 6. BANDEJA Y PROCESAMIENTO DE SOLICITUDES DE PERFIL
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
# 7. BANDEJA Y EMISIÓN DE CONSTANCIAS DE TRABAJO
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
            pendientes = [c for c in todas if c['estado'] in ['solicitada', 'pendiente']]
            emitidas = [c for c in todas if c['estado'] not in ['solicitada', 'pendiente']]

            cursor.execute("SELECT trabajador_id, cedula, nombres, apellidos FROM trabajador WHERE activo = true ORDER BY apellidos ASC, nombres ASC;")
            trabajadores = cursor.fetchall()

            return render_template('trabajadores/trabajadores_constancias.html', 
                                   pendientes=pendientes, emitidas=emitidas, trabajadores=trabajadores)
    finally:
        conexion.close()

@trabajadores_bp.route('/constancias/<int:constancia_id>/procesar', methods=['POST'])
def procesar_constancia(constancia_id):
    if 'usuario_id' not in session or session.get('rol') not in ['directora_rrhh', 'analista_rrhh']:
        flash('Acceso no autorizado.', 'danger')
        return redirect(url_for('trabajadores.constancias_admin'))

    accion = request.form.get('accion')
    motivo = request.form.get('motivo_rechazo', '').strip()

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            ahora = datetime.datetime.now()
            if accion == 'emitir':
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

@trabajadores_bp.route('/constancias/crear-directa', methods=['POST'])
def crear_constancia_directa():
    if 'usuario_id' not in session or session.get('rol') not in ['directora_rrhh', 'analista_rrhh']:
        flash('Acceso no autorizado.', 'danger')
        return redirect(url_for('auth.dashboard'))

    trabajador_id = request.form.get('trabajador_id')
    tipo = request.form.get('tipo', 'con_sueldo')
    destinatario = request.form.get('destinatario', 'A QUIEN PUEDA INTERESAR').strip()
    motivo = request.form.get('motivo', 'Trámite personal / Solicitud de oficio').strip()

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            ahora = datetime.datetime.now()
            cursor.execute("""
                INSERT INTO solicitud_constancia (trabajador_id, tipo, destinatario, motivo, estado, fecha_solicitud, fecha_emision, emitida_por)
                VALUES (%s, %s, %s, %s, 'emitida', %s, %s, %s);
            """, (trabajador_id, tipo, destinatario, motivo, ahora, ahora, session['usuario_id']))
            nueva_id = cursor.lastrowid
            correlativo = f"DTH-CT-{ahora.year}-{nueva_id:04d}"
            cursor.execute("UPDATE solicitud_constancia SET correlativo = %s WHERE constancia_id = %s;", (correlativo, nueva_id))
            conexion.commit()
            flash(f"Constancia {correlativo} emitida con éxito.", 'success')
    finally:
        conexion.close()

    return redirect(url_for('trabajadores.constancias_admin'))

# -------------------------------------------------------------------------
# 8. BANDEJA Y EMISIÓN DE PERMISOS LABORALES
# -------------------------------------------------------------------------
@trabajadores_bp.route('/permisos-admin')
def permisos_admin():
    if 'usuario_id' not in session or session.get('rol') not in ['directora_rrhh', 'analista_rrhh']:
        flash('Acceso denegado.', 'danger')
        return redirect(url_for('auth.dashboard'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            sql = """
                SELECT sp.*, t.cedula, t.nombres, t.apellidos,
                       c.nombre AS cargo_nombre, d.nombre AS departamento_nombre
                FROM solicitud_permiso sp
                INNER JOIN trabajador t ON sp.trabajador_id = t.trabajador_id
                INNER JOIN cargo c ON t.cargo_id = c.cargo_id
                LEFT JOIN departamento d ON c.departamento_id = d.departamento_id
                ORDER BY sp.permiso_id DESC;
            """
            cursor.execute(sql)
            permisos = cursor.fetchall()

            cursor.execute("SELECT trabajador_id, cedula, nombres, apellidos FROM trabajador WHERE activo = true ORDER BY apellidos ASC, nombres ASC;")
            trabajadores = cursor.fetchall()

            return render_template('trabajadores/trabajadores_permisos.html', permisos=permisos, trabajadores=trabajadores)
    finally:
        conexion.close()

@trabajadores_bp.route('/permisos-admin/<int:permiso_id>/procesar-fisico', methods=['POST'])
def procesar_permiso_fisico(permiso_id):
    if 'usuario_id' not in session or session.get('rol') not in ['directora_rrhh', 'analista_rrhh']:
        return redirect(url_for('auth.dashboard'))

    decision = request.form.get('decision')
    observaciones = request.form.get('observaciones', '').strip()

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            estado_final = 'consignado_aprobado' if decision == 'concedido' else 'negado'
            concedido_val = 1 if decision == 'concedido' else 0

            cursor.execute("""
                UPDATE solicitud_permiso
                SET estado = %s, concedido = %s, observaciones = %s,
                    fecha_aprobacion_fisica = NOW(), procesado_por = %s
                WHERE permiso_id = %s;
            """, (estado_final, concedido_val, observaciones, session['usuario_id'], permiso_id))
            conexion.commit()
            flash(f'Permiso #{permiso_id} procesado con conformidad física registrada.', 'success')
    finally:
        conexion.close()

    return redirect(url_for('trabajadores.permisos_admin'))

@trabajadores_bp.route('/permisos-admin/crear-directo', methods=['POST'])
def crear_permiso_directo():
    if 'usuario_id' not in session or session.get('rol') not in ['directora_rrhh', 'analista_rrhh']:
        return redirect(url_for('auth.dashboard'))

    trabajador_id = request.form.get('trabajador_id')
    tipo_permiso = request.form.get('tipo_permiso', 'ordinario')
    duracion = request.form.get('duracion', '').strip()
    fecha_inicio = request.form.get('fecha_inicio')
    fecha_fin = request.form.get('fecha_fin')
    motivo = request.form.get('motivo', '').strip()
    observaciones = request.form.get('observaciones', 'Concedido de oficio por la Dirección de RRHH').strip()

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            cursor.execute("""
                INSERT INTO solicitud_permiso (
                    trabajador_id, tipo_permiso, duracion, fecha_inicio, fecha_fin, 
                    motivo, observaciones, estado, concedido, fecha_solicitud, 
                    fecha_aprobacion_fisica, procesado_por
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'consignado_aprobado', 1, NOW(), NOW(), %s);
            """, (trabajador_id, tipo_permiso, duracion, fecha_inicio, fecha_fin, motivo, observaciones, session['usuario_id']))
            conexion.commit()
            flash('Permiso laboral registrado y convalidado físicamente.', 'success')
    finally:
        conexion.close()

    return redirect(url_for('trabajadores.permisos_admin'))

# -------------------------------------------------------------------------
# 9. BANDEJA Y EMISIÓN DE CERTIFICACIONES FAOV
# -------------------------------------------------------------------------
@trabajadores_bp.route('/faov-admin')
def faov_admin():
    if 'usuario_id' not in session or session.get('rol') not in ['directora_rrhh', 'analista_rrhh', 'tecnico_informatica']:
        flash('Acceso denegado.', 'danger')
        return redirect(url_for('auth.dashboard'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            sql = """
                SELECT sf.*, t.cedula, t.nombres, t.apellidos,
                       c.nombre AS cargo_nombre, d.nombre AS departamento_nombre
                FROM solicitud_faov sf
                INNER JOIN trabajador t ON sf.trabajador_id = t.trabajador_id
                INNER JOIN cargo c ON t.cargo_id = c.cargo_id
                LEFT JOIN departamento d ON c.departamento_id = d.departamento_id
                ORDER BY sf.solicitud_faov_id DESC;
            """
            cursor.execute(sql)
            solicitudes = cursor.fetchall()

            cursor.execute("SELECT trabajador_id, cedula, nombres, apellidos FROM trabajador WHERE activo = true ORDER BY apellidos ASC, nombres ASC;")
            trabajadores = cursor.fetchall()

            return render_template('trabajadores/trabajadores_faov.html', 
                                   solicitudes=solicitudes, trabajadores=trabajadores)
    finally:
        conexion.close()

@trabajadores_bp.route('/faov-admin/<int:id>/procesar', methods=['POST'])
def procesar_faov_admin(id):
    if 'usuario_id' not in session or session.get('rol') not in ['directora_rrhh', 'analista_rrhh']:
        flash('Acceso no autorizado.', 'danger')
        return redirect(url_for('trabajadores.faov_admin'))

    decision = request.form.get('decision')
    motivo = request.form.get('motivo_rechazo', '').strip()

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            ahora = datetime.datetime.now()
            if decision == 'aprobar':
                correlativo = f"DTH-FAOV-{ahora.year}-{id:04d}"
                cursor.execute("""
                    UPDATE solicitud_faov
                    SET estado = 'aprobada', correlativo = %s, fecha_aprobacion = %s,
                        aprobada_por = %s, motivo_rechazo = NULL
                    WHERE solicitud_faov_id = %s;
                """, (correlativo, ahora, session['usuario_id'], id))
                conexion.commit()
                flash(f'Certificación FAOV #{id} aprobada con éxito. Correlativo: {correlativo}', 'success')
            else:
                cursor.execute("""
                    UPDATE solicitud_faov
                    SET estado = 'rechazada', fecha_aprobacion = %s,
                        aprobada_por = %s, motivo_rechazo = %s
                    WHERE solicitud_faov_id = %s;
                """, (ahora, session['usuario_id'], motivo or 'No procedente.', id))
                conexion.commit()
                flash(f'Solicitud de certificación FAOV #{id} rechazada.', 'warning')
    finally:
        conexion.close()

    return redirect(url_for('trabajadores.faov_admin'))

@trabajadores_bp.route('/faov-admin/crear-directo', methods=['POST'])
def crear_faov_directo():
    if 'usuario_id' not in session or session.get('rol') not in ['directora_rrhh', 'analista_rrhh']:
        return redirect(url_for('auth.dashboard'))

    trabajador_id = request.form.get('trabajador_id')
    anio = request.form.get('anio', datetime.date.today().year)
    motivo = request.form.get('motivo', 'Certificación Oficial para Trámite Bancario / BANAVIH').strip()

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            ahora = datetime.datetime.now()
            cursor.execute("""
                INSERT INTO solicitud_faov (trabajador_id, anio, motivo, estado, fecha_solicitud, fecha_aprobacion, aprobada_por)
                VALUES (%s, %s, %s, 'aprobada', %s, %s, %s);
            """, (trabajador_id, anio, motivo, ahora, ahora, session['usuario_id']))
            nueva_id = cursor.lastrowid
            correlativo = f"DTH-FAOV-{ahora.year}-{nueva_id:04d}"
            cursor.execute("UPDATE solicitud_faov SET correlativo = %s WHERE solicitud_faov_id = %s;", (correlativo, nueva_id))
            conexion.commit()
            flash(f'Certificación FAOV {correlativo} generada con éxito.', 'success')
    finally:
        conexion.close()

    return redirect(url_for('trabajadores.faov_admin'))

# -------------------------------------------------------------------------
# 10. BANDEJA Y CONTROL DE VACACIONES
# -------------------------------------------------------------------------
@trabajadores_bp.route('/vacaciones-admin')
def vacaciones_admin():
    if 'usuario_id' not in session or session.get('rol') not in ['directora_rrhh', 'analista_rrhh']:
        flash('Acceso no autorizado.', 'danger')
        return redirect(url_for('auth.dashboard'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            sql = """
                SELECT sv.*, t.cedula, t.nombres, t.apellidos,
                       c.nombre AS cargo_nombre, d.nombre AS departamento_nombre
                FROM solicitud_vacaciones sv
                INNER JOIN trabajador t ON sv.trabajador_id = t.trabajador_id
                INNER JOIN cargo c ON t.cargo_id = c.cargo_id
                LEFT JOIN departamento d ON c.departamento_id = d.departamento_id
                ORDER BY sv.vacacion_id DESC;
            """
            cursor.execute(sql)
            solicitudes = cursor.fetchall()

            cursor.execute("SELECT trabajador_id, cedula, nombres, apellidos FROM trabajador WHERE activo = true ORDER BY apellidos ASC, nombres ASC;")
            trabajadores = cursor.fetchall()

            return render_template('trabajadores/trabajadores_vacaciones.html', solicitudes=solicitudes, trabajadores=trabajadores)
    finally:
        conexion.close()

@trabajadores_bp.route('/vacaciones-admin/<int:id>/procesar', methods=['POST'])
def procesar_vacaciones_admin(id):
    if 'usuario_id' not in session or session.get('rol') not in ['directora_rrhh', 'analista_rrhh']:
        return redirect(url_for('auth.dashboard'))

    decision = request.form.get('decision')
    observaciones = request.form.get('observaciones', '').strip()

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            ahora = datetime.datetime.now()
            estado_val = 'aprobada' if decision == 'aprobar' else 'rechazada'
            cursor.execute("""
                UPDATE solicitud_vacaciones
                SET estado = %s, fecha_aprobacion = %s, aprobada_por = %s, observaciones = %s
                WHERE vacacion_id = %s;
            """, (estado_val, ahora, session['usuario_id'], observaciones, id))
            conexion.commit()
            flash(f'Período vacacional #{id} actualizado a estado {estado_val.upper()}.', 'success')
    finally:
        conexion.close()

    return redirect(url_for('trabajadores.vacaciones_admin'))

@trabajadores_bp.route('/vacaciones-admin/crear-directo', methods=['POST'])
def crear_vacaciones_directo():
    if 'usuario_id' not in session or session.get('rol') not in ['directora_rrhh', 'analista_rrhh']:
        return redirect(url_for('auth.dashboard'))

    trabajador_id = request.form.get('trabajador_id')
    periodo = request.form.get('periodo', '').strip()
    fecha_inicio = request.form.get('fecha_inicio')
    fecha_fin = request.form.get('fecha_fin')
    dias_habiles = int(request.form.get('dias_habiles', 15))
    observaciones = request.form.get('observaciones', 'Asignado de oficio por cronograma institucional').strip()

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            cursor.execute("""
                INSERT INTO solicitud_vacaciones (
                    trabajador_id, periodo, fecha_inicio, fecha_fin, dias_habiles, 
                    estado, aprobada_por, observaciones, fecha_solicitud, fecha_aprobacion
                ) VALUES (%s, %s, %s, %s, %s, 'aprobada', %s, %s, NOW(), NOW());
            """, (trabajador_id, periodo, fecha_inicio, fecha_fin, dias_habiles, session['usuario_id'], observaciones))
            conexion.commit()
            flash('Período vacacional registrado y aprobado oficialmente.', 'success')
    finally:
        conexion.close()

    return redirect(url_for('trabajadores.vacaciones_admin'))

# -------------------------------------------------------------------------
# 11. BANDEJA Y EMISIÓN DE CERTIFICACIONES IVSS
# -------------------------------------------------------------------------
@trabajadores_bp.route('/ivss-admin')
def ivss_admin():
    if 'usuario_id' not in session or session.get('rol') not in ['directora_rrhh', 'analista_rrhh', 'tecnico_informatica']:
        flash('Acceso denegado.', 'danger')
        return redirect(url_for('auth.dashboard'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            sql = """
                SELECT si.*, t.cedula, t.nombres, t.apellidos,
                       c.nombre AS cargo_nombre, d.nombre AS departamento_nombre
                FROM solicitud_ivss si
                INNER JOIN trabajador t ON si.trabajador_id = t.trabajador_id
                INNER JOIN cargo c ON t.cargo_id = c.cargo_id
                LEFT JOIN departamento d ON c.departamento_id = d.departamento_id
                ORDER BY si.solicitud_ivss_id DESC;
            """
            cursor.execute(sql)
            solicitudes = cursor.fetchall()

            cursor.execute("SELECT trabajador_id, cedula, nombres, apellidos FROM trabajador WHERE activo = true ORDER BY apellidos ASC, nombres ASC;")
            trabajadores = cursor.fetchall()

            return render_template('trabajadores/trabajadores_ivss.html', solicitudes=solicitudes, trabajadores=trabajadores)
    finally:
        conexion.close()

@trabajadores_bp.route('/ivss-admin/<int:id>/procesar', methods=['POST'])
def procesar_ivss_admin(id):
    if 'usuario_id' not in session or session.get('rol') not in ['directora_rrhh', 'analista_rrhh']:
        flash('Acceso no autorizado.', 'danger')
        return redirect(url_for('trabajadores.ivss_admin'))

    decision = request.form.get('decision')
    motivo = request.form.get('motivo_rechazo', '').strip()

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            ahora = datetime.datetime.now()
            if decision == 'aprobar':
                correlativo = f"DTH-IVSS-{ahora.year}-{id:04d}"
                cursor.execute("""
                    UPDATE solicitud_ivss
                    SET estado = 'aprobada', correlativo = %s, fecha_aprobacion = %s,
                        aprobada_por = %s, motivo_rechazo = NULL
                    WHERE solicitud_ivss_id = %s;
                """, (correlativo, ahora, session['usuario_id'], id))
                conexion.commit()
                flash(f'Certificación IVSS #{id} aprobada con éxito. Correlativo: {correlativo}', 'success')
            else:
                cursor.execute("""
                    UPDATE solicitud_ivss
                    SET estado = 'rechazada', fecha_aprobacion = %s,
                        aprobada_por = %s, motivo_rechazo = %s
                    WHERE solicitud_ivss_id = %s;
                """, (ahora, session['usuario_id'], motivo or 'No procedente para el ejercicio fiscal solicitado.', id))
                conexion.commit()
                flash(f'Solicitud de certificación IVSS #{id} rechazada.', 'warning')
    finally:
        conexion.close()

    return redirect(url_for('trabajadores.ivss_admin'))

@trabajadores_bp.route('/ivss-admin/crear-directo', methods=['POST'])
def crear_ivss_directo():
    if 'usuario_id' not in session or session.get('rol') not in ['directora_rrhh', 'analista_rrhh']:
        return redirect(url_for('auth.dashboard'))

    trabajador_id = request.form.get('trabajador_id')
    anio = request.form.get('anio', datetime.date.today().year)
    motivo = request.form.get('motivo', 'Certificación Oficial de Cuenta Individual IVSS').strip()

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            ahora = datetime.datetime.now()
            cursor.execute("""
                INSERT INTO solicitud_ivss (trabajador_id, anio, motivo, estado, fecha_solicitud, fecha_aprobacion, aprobada_por)
                VALUES (%s, %s, %s, 'aprobada', %s, %s, %s);
            """, (trabajador_id, anio, motivo, ahora, ahora, session['usuario_id']))
            nueva_id = cursor.lastrowid
            correlativo = f"DTH-IVSS-{ahora.year}-{nueva_id:04d}"
            cursor.execute("UPDATE solicitud_ivss SET correlativo = %s WHERE solicitud_ivss_id = %s;", (correlativo, nueva_id))
            conexion.commit()
            flash(f'Certificación IVSS {correlativo} generada con éxito.', 'success')
    finally:
        conexion.close()

    return redirect(url_for('trabajadores.ivss_admin'))

# -------------------------------------------------------------------------
# 12. BANDEJA Y RESOLUCIONES DE JUBILACIÓN
# -------------------------------------------------------------------------
@trabajadores_bp.route('/jubilaciones-admin')
def jubilaciones_admin():
    if 'usuario_id' not in session or session.get('rol') not in ['directora_rrhh', 'analista_rrhh', 'tecnico_informatica']:
        flash('Acceso denegado.', 'danger')
        return redirect(url_for('auth.dashboard'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            sql = """
                SELECT sj.*, t.cedula, t.nombres, t.apellidos, t.fecha_ingreso,
                       c.nombre AS cargo_nombre, d.nombre AS departamento_nombre
                FROM solicitud_jubilacion sj
                INNER JOIN trabajador t ON sj.trabajador_id = t.trabajador_id
                INNER JOIN cargo c ON t.cargo_id = c.cargo_id
                LEFT JOIN departamento d ON c.departamento_id = d.departamento_id
                ORDER BY sj.jubilacion_id DESC;
            """
            cursor.execute(sql)
            solicitudes = cursor.fetchall()

            cursor.execute("""
                SELECT t.trabajador_id, t.cedula, t.nombres, t.apellidos, t.fecha_nacimiento,
                       t.fecha_ingreso, t.sexo, t.sueldo_base, c.nombre AS cargo_nombre
                FROM trabajador t
                INNER JOIN cargo c ON t.cargo_id = c.cargo_id
                WHERE t.activo = true AND t.tipo_personal != 'jubilados'
                ORDER BY t.apellidos ASC;
            """)
            trabajadores_activos = cursor.fetchall()

            return render_template(
                'trabajadores/trabajadores_jubilaciones.html',
                solicitudes=solicitudes,
                trabajadores=trabajadores_activos
            )
    finally:
        conexion.close()

@trabajadores_bp.route('/jubilaciones-admin/crear-directo', methods=['POST'])
def crear_jubilacion_directa():
    if 'usuario_id' not in session or session.get('rol') not in ['directora_rrhh', 'analista_rrhh']:
        return redirect(url_for('auth.dashboard'))

    trabajador_id = request.form.get('trabajador_id')
    porcentaje = Decimal(request.form.get('porcentaje_jubilacion', '100.00'))
    numero_gaceta = request.form.get('numero_gaceta_resolucion', '').strip()
    motivo = request.form.get('motivo', 'Pase a Retiro por Jubilación Reglamentaria').strip()
    observaciones = request.form.get('observaciones', '').strip()

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            cursor.execute("SELECT * FROM trabajador WHERE trabajador_id = %s;", (trabajador_id,))
            t = cursor.fetchone()
            if not t:
                flash('El trabajador seleccionado no existe.', 'warning')
                return redirect(url_for('trabajadores.jubilaciones_admin'))

            hoy = datetime.date.today()
            f_ing = t['fecha_ingreso']
            f_nac = t['fecha_nacimiento']

            anos_servicio = hoy.year - f_ing.year - ((hoy.month, hoy.day) < (f_ing.month, f_ing.day)) if f_ing else 0
            edad = hoy.year - f_nac.year - ((hoy.month, hoy.day) < (f_nac.month, f_nac.day)) if f_nac else 0

            sueldo_base = Decimal(str(t['sueldo_base']))
            monto_pension = (sueldo_base * (porcentaje / Decimal('100.00'))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

            ahora = datetime.datetime.now()
            cursor.execute("""
                INSERT INTO solicitud_jubilacion (
                    trabajador_id, tipo_tramite, motivo, anos_servicio, edad_trabajador,
                    porcentaje_jubilacion, monto_pension, numero_gaceta_resolucion,
                    fecha_solicitud, fecha_resolucion, estado, procesada_por, observaciones
                ) VALUES (%s, 'oficio_institucional', %s, %s, %s, %s, %s, %s, %s, %s, 'aprobada', %s, %s);
            """, (trabajador_id, motivo, anos_servicio, edad, porcentaje, monto_pension, numero_gaceta, ahora, ahora, session['usuario_id'], observaciones))
            nueva_id = cursor.lastrowid
            correlativo = f"DTH-RES-JUB-{ahora.year}-{nueva_id:04d}"
            cursor.execute("UPDATE solicitud_jubilacion SET correlativo = %s WHERE jubilacion_id = %s;", (correlativo, nueva_id))

            cursor.execute("""
                UPDATE trabajador 
                SET tipo_personal = 'jubilados', sueldo_base = %s 
                WHERE trabajador_id = %s;
            """, (monto_pension, trabajador_id))

            conexion.commit()
            flash(f"Resolución de Jubilación {correlativo} aprobada. El trabajador fue reasignado al padrón de Jubilados con pensión de Bs. {monto_pension:,.2f}.", 'success')
    finally:
        conexion.close()

    return redirect(url_for('trabajadores.jubilaciones_admin'))

@trabajadores_bp.route('/jubilaciones-admin/<int:id>/procesar', methods=['POST'])
def procesar_jubilacion_admin(id):
    if 'usuario_id' not in session or session.get('rol') not in ['directora_rrhh', 'analista_rrhh']:
        return redirect(url_for('auth.dashboard'))

    decision = request.form.get('decision')
    porcentaje = Decimal(request.form.get('porcentaje_jubilacion', '100.00'))
    numero_gaceta = request.form.get('numero_gaceta_resolucion', '').strip()
    motivo_rechazo = request.form.get('motivo_rechazo', '').strip()

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            ahora = datetime.datetime.now()
            if decision == 'aprobar':
                cursor.execute("""
                    SELECT sj.*, t.sueldo_base FROM solicitud_jubilacion sj
                    INNER JOIN trabajador t ON sj.trabajador_id = t.trabajador_id
                    WHERE sj.jubilacion_id = %s;
                """, (id,))
                sol = cursor.fetchone()

                sueldo_base = Decimal(str(sol['sueldo_base']))
                monto_pension = (sueldo_base * (porcentaje / Decimal('100.00'))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                correlativo = f"DTH-RES-JUB-{ahora.year}-{id:04d}"

                cursor.execute("""
                    UPDATE solicitud_jubilacion
                    SET estado = 'aprobada', correlativo = %s, fecha_resolucion = %s,
                        porcentaje_jubilacion = %s, monto_pension = %s,
                        numero_gaceta_resolucion = %s, procesada_por = %s
                    WHERE jubilacion_id = %s;
                """, (correlativo, ahora, porcentaje, monto_pension, numero_gaceta, session['usuario_id'], id))

                cursor.execute("UPDATE trabajador SET tipo_personal = 'jubilados', sueldo_base = %s WHERE trabajador_id = %s;", (monto_pension, sol['trabajador_id']))
                conexion.commit()
                flash(f"Solicitud #{id} aprobada con Resolución {correlativo}.", 'success')
            else:
                cursor.execute("""
                    UPDATE solicitud_jubilacion
                    SET estado = 'rechazada', fecha_resolucion = %s, procesada_por = %s, motivo_rechazo = %s
                    WHERE jubilacion_id = %s;
                """, (ahora, session['usuario_id'], motivo_rechazo or 'No cumple con el tiempo reglamentario.', id))
                conexion.commit()
                flash(f"Solicitud de jubilación #{id} rechazada.", 'warning')
    finally:
        conexion.close()

    return redirect(url_for('trabajadores.jubilaciones_admin'))