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
# Roles: analista_rrhh, directora_rrhh, tecnico_informatica
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
            sql = """
                SELECT t.*, c.nombre AS cargo_nombre, u.usuario_id AS cuenta_usuario_id, u.nombre_usuario
                FROM trabajador t
                INNER JOIN cargo c ON t.cargo_id = c.cargo_id
                LEFT JOIN usuario u ON t.trabajador_id = u.trabajador_id
                WHERE t.activo = true
                ORDER BY t.tipo_personal ASC, t.apellidos ASC, t.nombres ASC;
            """
            cursor.execute(sql)
            trabajadores = cursor.fetchall()
            return render_template('trabajadores_lista.html', trabajadores=trabajadores)
    finally:
        conexion.close()

# -------------------------------------------------------------------------
# 2. CREAR NUEVO TRABAJADOR
# Roles: directora_rrhh, tecnico_informatica
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

                # Validar unicidad de cedula
                cursor.execute("SELECT trabajador_id FROM trabajador WHERE cedula = %s;", (cedula,))
                if cursor.fetchone():
                    flash(f'La cédula {cedula} ya se encuentra registrada en el sistema.', 'warning')
                    cursor.execute("SELECT cargo_id, nombre, sueldo_base FROM cargo WHERE activo = true;")
                    cargos = cursor.fetchall()
                    return render_template('trabajadores_form.html', modo='crear', cargos=cargos,
                                           tipos_personal=TIPOS_PERSONAL, niveles=NIVELES_INSTRUCCION)

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

                # Auditoría obligatoria en bitácora
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

            # Si es GET: consultar cargos activos para el selector
            cursor.execute("SELECT cargo_id, nombre, sueldo_base FROM cargo WHERE activo = true ORDER BY nombre;")
            cargos = cursor.fetchall()
            return render_template('trabajadores_form.html', modo='crear', cargos=cargos,
                                   tipos_personal=TIPOS_PERSONAL, niveles=NIVELES_INSTRUCCION)
    except Exception as e:
        conexion.rollback()
        flash(f'Error al registrar trabajador: {e}', 'danger')
        return redirect(url_for('trabajadores.listar'))
    finally:
        conexion.close()

# -------------------------------------------------------------------------
# 3. EDITAR TRABAJADOR EXISTENTE (Con auditoría JSON en bitácora)
# Roles: directora_rrhh, tecnico_informatica
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
            # Obtener estado previo completo
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

                # Obtener estado posterior exacto
                cursor.execute("SELECT * FROM trabajador WHERE trabajador_id = %s;", (id,))
                valor_nuevo = cursor.fetchone()

                # Registro en bitácora exigido por auditoría fiscal
                sql_bitacora = """
                    INSERT INTO bitacora (usuario_id, tabla, registro_id, accion, valor_previo, valor_nuevo, fecha_hora, ip)
                    VALUES (%s, 'trabajador', %s, 'modificar', %s, %s, %s, %s);
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
                flash(f'Expediente de {nombres} {apellidos} actualizado y registrado en auditoría.', 'success')
                return redirect(url_for('trabajadores.listar'))

            # Si es GET: consultar cargos y cargar formulario con datos previos
            cursor.execute("SELECT cargo_id, nombre, sueldo_base FROM cargo WHERE activo = true ORDER BY nombre;")
            cargos = cursor.fetchall()
            return render_template('trabajadores_form.html', modo='editar', trabajador=valor_previo,
                                   cargos=cargos, tipos_personal=TIPOS_PERSONAL, niveles=NIVELES_INSTRUCCION)
    except Exception as e:
        conexion.rollback()
        flash(f'Error al modificar trabajador: {e}', 'danger')
        return redirect(url_for('trabajadores.listar'))
    finally:
        conexion.close()

# -------------------------------------------------------------------------
# 4. DESACTIVAR TRABAJADOR (Baja lógica inalterable para Contraloría)
# Roles: directora_rrhh, tecnico_informatica
# -------------------------------------------------------------------------
@trabajadores_bp.route('/<int:id>/desactivar', methods=['POST'])
def desactivar(id):
    roles_permitidos = ['directora_rrhh', 'tecnico_informatica']
    if 'usuario_id' not in session or session.get('rol') not in roles_permitidos:
        flash('Acceso denegado: No tiene permisos para tramitar bajas de personal.', 'danger')
        return redirect(url_for('trabajadores.listar'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            cursor.execute("SELECT * FROM trabajador WHERE trabajador_id = %s AND activo = true;", (id,))
            valor_previo = cursor.fetchone()

            if not valor_previo:
                flash('El trabajador no existe o ya se encuentra egresado.', 'warning')
                return redirect(url_for('trabajadores.listar'))

            hoy = datetime.date.today()
            # Desactivar trabajador y colocar fecha_egreso (nunca DELETE)
            cursor.execute("UPDATE trabajador SET activo = false, fecha_egreso = %s WHERE trabajador_id = %s;", (hoy, id))

            # Desactivar cuenta de usuario asociada si la tuviera
            cursor.execute("UPDATE usuario SET activo = false WHERE trabajador_id = %s;", (id,))

            # Registrar en bitácora con acción eliminar
            valor_nuevo = {'activo': False, 'fecha_egreso': str(hoy)}
            sql_bitacora = """
                INSERT INTO bitacora (usuario_id, tabla, registro_id, accion, valor_previo, valor_nuevo, fecha_hora, ip)
                VALUES (%s, 'trabajador', %s, 'eliminar', %s, %s, %s, %s);
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
            flash(f"Trabajador {valor_previo['nombres']} {valor_previo['apellidos']} egresado del sistema con éxito.", 'info')
    except Exception as e:
        conexion.rollback()
        flash(f'Error al procesar egreso: {e}', 'danger')
    finally:
        conexion.close()

    return redirect(url_for('trabajadores.listar'))

# -------------------------------------------------------------------------
# 5. CREAR CUENTA DE USUARIO LIGADA
# Roles: directora_rrhh, tecnico_informatica
# -------------------------------------------------------------------------
@trabajadores_bp.route('/<int:id>/crear-usuario', methods=['GET', 'POST'])
def crear_usuario(id):
    roles_permitidos = ['directora_rrhh', 'tecnico_informatica']
    if 'usuario_id' not in session or session.get('rol') not in roles_permitidos:
        flash('Acceso denegado: No tiene autorización para gestionar accesos de usuarios.', 'danger')
        return redirect(url_for('trabajadores.listar'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            cursor.execute("SELECT * FROM trabajador WHERE trabajador_id = %s AND activo = true;", (id,))
            trabajador = cursor.fetchone()

            if not trabajador:
                flash('El trabajador no existe o se encuentra inactivo.', 'warning')
                return redirect(url_for('trabajadores.listar'))

            # Verificar si ya posee cuenta
            cursor.execute("SELECT usuario_id, nombre_usuario FROM usuario WHERE trabajador_id = %s;", (id,))
            cuenta_existente = cursor.fetchone()
            if cuenta_existente:
                flash(f"Este trabajador ya posee la cuenta '{cuenta_existente['nombre_usuario']}'.", 'warning')
                return redirect(url_for('trabajadores.listar'))

            if request.method == 'POST':
                nombre_usuario = request.form.get('nombre_usuario', '').strip().lower()
                clave_temporal = request.form.get('clave', '').strip()
                rol_id = request.form.get('rol_id')

                if not nombre_usuario or not clave_temporal or not rol_id:
                    flash('Todos los campos del formulario de usuario son obligatorios.', 'warning')
                    cursor.execute("SELECT rol_id, nombre, descripcion FROM rol ORDER BY rol_id;")
                    roles = cursor.fetchall()
                    return render_template('trabajadores_usuario.html', trabajador=trabajador, roles=roles)

                # Comprobar disponibilidad de nombre_usuario
                cursor.execute("SELECT usuario_id FROM usuario WHERE nombre_usuario = %s;", (nombre_usuario,))
                if cursor.fetchone():
                    flash(f"El nombre de usuario '{nombre_usuario}' ya está en uso.", 'danger')
                    cursor.execute("SELECT rol_id, nombre, descripcion FROM rol ORDER BY rol_id;")
                    roles = cursor.fetchall()
                    return render_template('trabajadores_usuario.html', trabajador=trabajador, roles=roles)

                # Generar hash seguro e insertar
                clave_hash = generate_password_hash(clave_temporal)
                ahora = datetime.datetime.now()

                sql_usuario = """
                    INSERT INTO usuario (trabajador_id, rol_id, nombre_usuario, clave_hash, creado_en, activo)
                    VALUES (%s, %s, %s, %s, %s, true);
                """
                cursor.execute(sql_usuario, (id, rol_id, nombre_usuario, clave_hash, ahora))
                nuevo_usuario_id = cursor.lastrowid

                # Auditoría en bitácora
                sql_bitacora = """
                    INSERT INTO bitacora (usuario_id, tabla, registro_id, accion, valor_previo, valor_nuevo, fecha_hora, ip)
                    VALUES (%s, 'usuario', %s, 'insertar', NULL, %s, %s, %s);
                """
                datos_nuevos = {
                    'usuario_id': nuevo_usuario_id,
                    'trabajador_id': id,
                    'rol_id': rol_id,
                    'nombre_usuario': nombre_usuario,
                    'activo': True
                }
                cursor.execute(sql_bitacora, (
                    session['usuario_id'],
                    nuevo_usuario_id,
                    json.dumps(datos_nuevos, default=str),
                    ahora,
                    request.remote_addr
                ))

                conexion.commit()
                flash(f"Cuenta '{nombre_usuario}' creada exitosamente y vinculada al trabajador.", 'success')
                return redirect(url_for('trabajadores.listar'))

            # Si es GET: listar roles disponibles para el select
            cursor.execute("SELECT rol_id, nombre, descripcion FROM rol ORDER BY rol_id;")
            roles = cursor.fetchall()
            return render_template('trabajadores_usuario.html', trabajador=trabajador, roles=roles)
    except Exception as e:
        conexion.rollback()
        flash(f'Error al crear cuenta de usuario: {e}', 'danger')
        return redirect(url_for('trabajadores.listar'))
    finally:
        conexion.close()