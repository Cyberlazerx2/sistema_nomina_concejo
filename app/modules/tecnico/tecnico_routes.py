from flask import Blueprint, render_template, request, redirect, url_for, session, flash, send_file
from werkzeug.security import generate_password_hash
import datetime
import json
import io
from app.database import get_db_connection

tecnico_bp = Blueprint('tecnico', __name__)

def verificar_tecnico():
    """Garantiza acceso exclusivo al Técnico de Informática."""
    if 'usuario_id' not in session or session.get('rol') != 'tecnico_informatica':
        return False
    return True

# -------------------------------------------------------------------------
# 1. LISTADO GENERAL DE USUARIOS
# -------------------------------------------------------------------------
@tecnico_bp.route('/usuarios')
def usuarios():
    if not verificar_tecnico():
        flash('Acceso denegado: Módulo restringido al Técnico de Informática.', 'danger')
        return redirect(url_for('auth.dashboard'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            sql = """
                SELECT u.usuario_id, u.nombre_usuario, u.activo, u.creado_en, u.ultimo_acceso,
                       r.rol_id, r.nombre AS rol_nombre, r.descripcion AS rol_descripcion,
                       t.trabajador_id, t.cedula, t.nombres, t.apellidos, c.nombre AS cargo_nombre
                FROM usuario u
                INNER JOIN rol r ON u.rol_id = r.rol_id
                LEFT JOIN trabajador t ON u.trabajador_id = t.trabajador_id
                LEFT JOIN cargo c ON t.cargo_id = c.cargo_id
                ORDER BY u.usuario_id ASC;
            """
            cursor.execute(sql)
            lista_usuarios = cursor.fetchall()

            # Trabajadores activos que aún no tienen usuario asociado
            sql_sin_usuario = """
                SELECT t.trabajador_id, t.cedula, t.nombres, t.apellidos, c.nombre AS cargo_nombre
                FROM trabajador t
                INNER JOIN cargo c ON t.cargo_id = c.cargo_id
                LEFT JOIN usuario u ON t.trabajador_id = u.trabajador_id
                WHERE t.activo = true AND u.usuario_id IS NULL
                ORDER BY t.apellidos ASC, t.nombres ASC;
            """
            cursor.execute(sql_sin_usuario)
            trabajadores_pendientes = cursor.fetchall()

            return render_template(
                'tecnico_usuarios.html',
                usuarios=lista_usuarios,
                pendientes=trabajadores_pendientes
            )
    finally:
        conexion.close()

# -------------------------------------------------------------------------
# 2. CREAR CUENTA DE USUARIO PARA UN TRABAJADOR
# -------------------------------------------------------------------------
@tecnico_bp.route('/usuarios/nuevo', methods=['GET', 'POST'])
def nuevo_usuario():
    if not verificar_tecnico():
        flash('Acceso denegado.', 'danger')
        return redirect(url_for('auth.dashboard'))

    trabajador_id_param = request.args.get('trabajador_id')

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            if request.method == 'POST':
                trabajador_id = request.form.get('trabajador_id')
                nombre_usuario = request.form.get('nombre_usuario', '').strip().lower()
                clave_temporal = request.form.get('clave', '').strip()
                rol_id = request.form.get('rol_id')

                if not trabajador_id or not nombre_usuario or not clave_temporal or not rol_id:
                    flash('Todos los campos son obligatorios para generar credenciales.', 'warning')
                    return redirect(url_for('tecnico.nuevo_usuario', trabajador_id=trabajador_id))

                # Validar disponibilidad de nombre_usuario
                cursor.execute("SELECT usuario_id FROM usuario WHERE nombre_usuario = %s;", (nombre_usuario,))
                if cursor.fetchone():
                    flash(f"El nombre de usuario '{nombre_usuario}' ya está en uso. Elija otro identificador.", 'danger')
                    return redirect(url_for('tecnico.nuevo_usuario', trabajador_id=trabajador_id))

                # Validar que el trabajador no tenga cuenta previa
                cursor.execute("SELECT usuario_id FROM usuario WHERE trabajador_id = %s;", (trabajador_id,))
                if cursor.fetchone():
                    flash('Este trabajador ya posee una cuenta de usuario asignada.', 'warning')
                    return redirect(url_for('tecnico.usuarios'))

                clave_hash = generate_password_hash(clave_temporal)
                ahora = datetime.datetime.now()

                sql_insert = """
                    INSERT INTO usuario (trabajador_id, rol_id, nombre_usuario, clave_hash, creado_en, activo)
                    VALUES (%s, %s, %s, %s, %s, true);
                """
                cursor.execute(sql_insert, (trabajador_id, rol_id, nombre_usuario, clave_hash, ahora))
                nuevo_id = cursor.lastrowid

                # Auditoría en bitácora
                sql_bitacora = """
                    INSERT INTO bitacora (usuario_id, tabla, registro_id, accion, valor_previo, valor_nuevo, fecha_hora, ip)
                    VALUES (%s, 'usuario', %s, 'insertar', NULL, %s, %s, %s);
                """
                datos_nuevos = {
                    'usuario_id': nuevo_id,
                    'trabajador_id': trabajador_id,
                    'rol_id': rol_id,
                    'nombre_usuario': nombre_usuario,
                    'activo': True
                }
                cursor.execute(sql_bitacora, (
                    session['usuario_id'],
                    nuevo_id,
                    json.dumps(datos_nuevos, default=str),
                    ahora,
                    request.remote_addr
                ))

                conexion.commit()
                flash(f"Cuenta '{nombre_usuario}' creada exitosamente y vinculada al funcionario.", 'success')
                return redirect(url_for('tecnico.usuarios'))

            # Si es GET
            cursor.execute("""
                SELECT t.trabajador_id, t.cedula, t.nombres, t.apellidos, c.nombre AS cargo_nombre
                FROM trabajador t
                INNER JOIN cargo c ON t.cargo_id = c.cargo_id
                LEFT JOIN usuario u ON t.trabajador_id = u.trabajador_id
                WHERE t.activo = true AND u.usuario_id IS NULL
                ORDER BY t.apellidos ASC;
            """)
            trabajadores_disponibles = cursor.fetchall()

            cursor.execute("SELECT rol_id, nombre, descripcion FROM rol ORDER BY rol_id ASC;")
            roles = cursor.fetchall()

            return render_template(
                'tecnico_usuario_form.html',
                trabajadores=trabajadores_disponibles,
                roles=roles,
                trabajador_id_param=trabajador_id_param
            )
    except Exception as e:
        conexion.rollback()
        flash(f'Error al registrar usuario: {e}', 'danger')
        return redirect(url_for('tecnico.usuarios'))
    finally:
        conexion.close()

# -------------------------------------------------------------------------
# 3. RESTABLECER / BLANQUEAR CONTRASEÑA
# -------------------------------------------------------------------------
@tecnico_bp.route('/usuarios/<int:id>/reset-clave', methods=['POST'])
def reset_clave(id):
    if not verificar_tecnico():
        flash('Acceso denegado.', 'danger')
        return redirect(url_for('auth.dashboard'))

    nueva_clave = request.form.get('nueva_clave', '').strip()
    if not nueva_clave:
        flash('Debe suministrar una nueva contraseña temporal válida.', 'warning')
        return redirect(url_for('tecnico.usuarios'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            cursor.execute("SELECT usuario_id, nombre_usuario, activo FROM usuario WHERE usuario_id = %s;", (id,))
            usuario = cursor.fetchone()

            if not usuario:
                flash('El usuario indicado no existe.', 'warning')
                return redirect(url_for('tecnico.usuarios'))

            clave_hash = generate_password_hash(nueva_clave)
            cursor.execute("UPDATE usuario SET clave_hash = %s WHERE usuario_id = %s;", (clave_hash, id))

            # Auditoría en bitácora
            ahora = datetime.datetime.now()
            sql_bitacora = """
                INSERT INTO bitacora (usuario_id, tabla, registro_id, accion, valor_previo, valor_nuevo, fecha_hora, ip)
                VALUES (%s, 'usuario', %s, 'modificar', %s, %s, %s, %s);
            """
            cursor.execute(sql_bitacora, (
                session['usuario_id'],
                id,
                json.dumps({'evento': 'blanqueo_clave', 'usuario': usuario['nombre_usuario']}),
                json.dumps({'evento': 'clave_temporal_asignada'}),
                ahora,
                request.remote_addr
            ))

            conexion.commit()
            flash(f"Contraseña de '{usuario['nombre_usuario']}' restablecida exitosamente.", 'success')
    except Exception as e:
        conexion.rollback()
        flash(f'Error al restablecer contraseña: {e}', 'danger')
    finally:
        conexion.close()

    return redirect(url_for('tecnico.usuarios'))

# -------------------------------------------------------------------------
# 4. ACTIVAR / DESACTIVAR CUENTA (BLOQUEO LÓGICO)
# -------------------------------------------------------------------------
@tecnico_bp.route('/usuarios/<int:id>/toggle-activo', methods=['POST'])
def toggle_activo(id):
    if not verificar_tecnico():
        flash('Acceso denegado.', 'danger')
        return redirect(url_for('auth.dashboard'))

    # Evitar que el técnico se bloquee a sí mismo
    if id == session.get('usuario_id'):
        flash('No puede bloquear su propia cuenta de técnico en sesión.', 'warning')
        return redirect(url_for('tecnico.usuarios'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            cursor.execute("SELECT usuario_id, nombre_usuario, activo FROM usuario WHERE usuario_id = %s;", (id,))
            usuario = cursor.fetchone()

            if not usuario:
                flash('Usuario no encontrado.', 'warning')
                return redirect(url_for('tecnico.usuarios'))

            nuevo_estado = not usuario['activo']
            cursor.execute("UPDATE usuario SET activo = %s WHERE usuario_id = %s;", (nuevo_estado, id))

            ahora = datetime.datetime.now()
            sql_bitacora = """
                INSERT INTO bitacora (usuario_id, tabla, registro_id, accion, valor_previo, valor_nuevo, fecha_hora, ip)
                VALUES (%s, 'usuario', %s, 'modificar', %s, %s, %s, %s);
            """
            cursor.execute(sql_bitacora, (
                session['usuario_id'],
                id,
                json.dumps({'activo': usuario['activo']}),
                json.dumps({'activo': nuevo_estado}),
                ahora,
                request.remote_addr
            ))

            conexion.commit()
            estado_txt = 'HABILITADA' if nuevo_estado else 'BLOQUEADA'
            flash(f"Cuenta '{usuario['nombre_usuario']}' marcada como {estado_txt}.", 'info')
    except Exception as e:
        conexion.rollback()
        flash(f'Error al alterar estado de la cuenta: {e}', 'danger')
    finally:
        conexion.close()

    return redirect(url_for('tecnico.usuarios'))

# -------------------------------------------------------------------------
# 5. VISOR DE AUDITORÍA (BITÁCORA INSTITUCIONAL)
# -------------------------------------------------------------------------
@tecnico_bp.route('/bitacora')
def bitacora():
    if not verificar_tecnico():
        flash('Acceso denegado.', 'danger')
        return redirect(url_for('auth.dashboard'))

    tabla_filtro = request.args.get('tabla', '')
    accion_filtro = request.args.get('accion', '')

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            sql = """
                SELECT b.bitacora_id, b.tabla, b.registro_id, b.accion,
                       b.valor_previo, b.valor_nuevo, b.fecha_hora, b.ip,
                       u.nombre_usuario, r.nombre AS rol_nombre
                FROM bitacora b
                LEFT JOIN usuario u ON b.usuario_id = u.usuario_id
                LEFT JOIN rol r ON u.rol_id = r.rol_id
                WHERE 1=1
            """
            params = []
            if tabla_filtro:
                sql += " AND b.tabla = %s"
                params.append(tabla_filtro)
            if accion_filtro:
                sql += " AND b.accion = %s"
                params.append(accion_filtro)

            sql += " ORDER BY b.bitacora_id DESC LIMIT 200;"
            cursor.execute(sql, tuple(params))
            eventos = cursor.fetchall()

            # Tablas presentes para el filtro
            cursor.execute("SELECT DISTINCT tabla FROM bitacora ORDER BY tabla ASC;")
            tablas_disponibles = [row['tabla'] for row in cursor.fetchall()]

            return render_template(
                'tecnico_bitacora.html',
                eventos=eventos,
                tablas=tablas_disponibles,
                tabla_filtro=tabla_filtro,
                accion_filtro=accion_filtro
            )
    finally:
        conexion.close()

# -------------------------------------------------------------------------
# 6. GENERADOR Y DESCARGA DE RESPALDO SQL (BACKUP NATIVO)
# -------------------------------------------------------------------------
@tecnico_bp.route('/backup')
def backup():
    if not verificar_tecnico():
        flash('Acceso denegado.', 'danger')
        return redirect(url_for('auth.dashboard'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            cursor.execute("SHOW FULL TABLES WHERE Table_type = 'BASE TABLE';")
            tablas_info = cursor.fetchall()
            tablas = [list(t.values())[0] for t in tablas_info]

            ahora = datetime.datetime.now()
            lineas_sql = [
                "-- ========================================================",
                f"-- RESPALDO DE BASE DE DATOS: CONCEJO MUNICIPAL INDEPENDENCIA",
                f"-- Fecha y Hora de Generación: {ahora.strftime('%Y-%m-%d %H:%M:%S')}",
                f"-- Generado por: {session.get('nombre_usuario')} (Técnico de Informática)",
                "-- ========================================================\n",
                "SET FOREIGN_KEY_CHECKS = 0;\n"
            ]

            for tabla in tablas:
                # Estructura DDL
                cursor.execute(f"SHOW CREATE TABLE `{tabla}`;")
                ddl = cursor.fetchone()
                create_stmt = list(ddl.values())[1]

                lineas_sql.append(f"-- Estructura de la tabla `{tabla}`")
                lineas_sql.append(f"DROP TABLE IF EXISTS `{tabla}`;")
                lineas_sql.append(f"{create_stmt};\n")

                # Datos DML
                cursor.execute(f"SELECT * FROM `{tabla}`;")
                filas = cursor.fetchall()
                if filas:
                    lineas_sql.append(f"-- Datos de la tabla `{tabla}`")
                    for fila in filas:
                        columnas = [f"`{col}`" for col in fila.keys()]
                        valores = []
                        for v in fila.values():
                            if v is None:
                                valores.append("NULL")
                            elif isinstance(v, (int, float)):
                                valores.append(str(v))
                            else:
                                v_escaped = str(v).replace("\\", "\\\\").replace("'", "''").replace("\r", "\\r").replace("\n", "\\n")
                                valores.append(f"'{v_escaped}'")
                        lineas_sql.append(f"INSERT INTO `{tabla}` ({', '.join(columnas)}) VALUES ({', '.join(valores)});")
                    lineas_sql.append("")

            lineas_sql.append("SET FOREIGN_KEY_CHECKS = 1;\n")
            contenido_backup = "\n".join(lineas_sql)

            # Registro de auditoría por descarga de respaldo
            sql_bitacora = """
                INSERT INTO bitacora (usuario_id, tabla, registro_id, accion, valor_previo, valor_nuevo, fecha_hora, ip)
                VALUES (%s, 'sistema', NULL, 'modificar', NULL, %s, %s, %s);
            """
            cursor.execute(sql_bitacora, (
                session['usuario_id'],
                json.dumps({'evento': 'generacion_backup_sql', 'tablas': len(tablas)}),
                ahora,
                request.remote_addr
            ))
            conexion.commit()

            buffer = io.BytesIO(contenido_backup.encode('utf-8'))
            nombre_archivo = f"backup_concejo_{ahora.strftime('%Y%m%d_%H%M%S')}.sql"

            return send_file(
                buffer,
                as_attachment=True,
                download_name=nombre_archivo,
                mimetype='application/sql'
            )
    except Exception as e:
        conexion.rollback()
        flash(f'Error al generar el respaldo de base de datos: {e}', 'danger')
        return redirect(url_for('auth.dashboard'))
    finally:
        conexion.close()