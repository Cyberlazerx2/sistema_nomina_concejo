from flask import Blueprint, render_template, request, redirect, url_for, session, flash
import datetime
import json
from app.database import get_db_connection

asistencia_bp = Blueprint('asistencia', __name__)

ROLES_PERMITIDOS = ['analista_rrhh', 'directora_rrhh']

ESTADOS_ASISTENCIA = [
    ('presente', 'Presente'),
    ('falta_justificada', 'Falta Justificada'),
    ('falta_injustificada', 'Falta Injustificada'),
    ('reposo', 'Reposo Médico'),
    ('vacaciones', 'Vacaciones'),
    ('permiso', 'Permiso Remunerado / No Remunerado')
]

def verificar_acceso():
    if 'usuario_id' not in session or session.get('rol') not in ROLES_PERMITIDOS:
        return False
    return True

# -------------------------------------------------------------------------
# 1. LISTADO GENERAL DE ASISTENCIAS / NOVEDADES
# Permite filtrar por fecha y tipo de personal
# -------------------------------------------------------------------------
@asistencia_bp.route('/')
def listar():
    if not verificar_acceso():
        flash('Acceso denegado: Solo el personal de Recursos Humanos puede acceder a este módulo.', 'danger')
        return redirect(url_for('auth.dashboard'))

    fecha_filtro = request.args.get('fecha', datetime.date.today().strftime('%Y-%m-%d'))
    tipo_filtro = request.args.get('tipo_personal', '')

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            sql = """
                SELECT a.asistencia_id, a.fecha, a.estado, a.observacion,
                       t.trabajador_id, t.cedula, t.nombres, t.apellidos, t.tipo_personal,
                       c.nombre AS cargo_nombre
                FROM asistencia a
                INNER JOIN trabajador t ON a.trabajador_id = t.trabajador_id
                INNER JOIN cargo c ON t.cargo_id = c.cargo_id
                WHERE a.fecha = %s
            """
            params = [fecha_filtro]

            if tipo_filtro:
                sql += " AND t.tipo_personal = %s"
                params.append(tipo_filtro)

            sql += " ORDER BY t.apellidos ASC, t.nombres ASC;"
            cursor.execute(sql, tuple(params))
            registros = cursor.fetchall()

            return render_template(
                'asistencia_lista.html',
                registros=registros,
                fecha_filtro=fecha_filtro,
                tipo_filtro=tipo_filtro,
                estados=ESTADOS_ASISTENCIA
            )
    finally:
        conexion.close()

# -------------------------------------------------------------------------
# 2. REGISTRAR NOVEDAD O ASISTENCIA INDIVIDUAL
# Si ya existe registro para esa fecha y trabajador, lo actualiza
# -------------------------------------------------------------------------
@asistencia_bp.route('/nueva', methods=['GET', 'POST'])
def nueva():
    if not verificar_acceso():
        flash('Acceso denegado.', 'danger')
        return redirect(url_for('auth.dashboard'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            if request.method == 'POST':
                trabajador_id = request.form.get('trabajador_id')
                fecha = request.form.get('fecha')
                estado = request.form.get('estado')
                observacion = request.form.get('observacion', '').strip()[:150]

                if not trabajador_id or not fecha or not estado:
                    flash('Los campos de trabajador, fecha y estado son obligatorios.', 'warning')
                    cursor.execute("SELECT trabajador_id, cedula, nombres, apellidos FROM trabajador WHERE activo = true ORDER BY apellidos ASC;")
                    trabajadores = cursor.fetchall()
                    return render_template('asistencia_form.html', trabajadores=trabajadores, estados=ESTADOS_ASISTENCIA)

                # Comprobar si ya existe registro en la misma fecha
                cursor.execute("""
                    SELECT * FROM asistencia 
                    WHERE trabajador_id = %s AND fecha = %s;
                """, (trabajador_id, fecha))
                existente = cursor.fetchone()

                ahora = datetime.datetime.now()

                if existente:
                    # Actualizar estado existente
                    cursor.execute("""
                        UPDATE asistencia 
                        SET estado = %s, observacion = %s 
                        WHERE asistencia_id = %s;
                    """, (estado, observacion, existente['asistencia_id']))

                    asistencia_id = existente['asistencia_id']
                    accion = 'modificar'
                    valor_previo = existente
                    valor_nuevo = {'asistencia_id': asistencia_id, 'trabajador_id': trabajador_id, 'fecha': str(fecha), 'estado': estado, 'observacion': observacion}
                else:
                    # Insertar nuevo registro
                    cursor.execute("""
                        INSERT INTO asistencia (trabajador_id, fecha, estado, observacion)
                        VALUES (%s, %s, %s, %s);
                    """, (trabajador_id, fecha, estado, observacion))

                    asistencia_id = cursor.lastrowid
                    accion = 'insertar'
                    valor_previo = None
                    valor_nuevo = {'asistencia_id': asistencia_id, 'trabajador_id': trabajador_id, 'fecha': str(fecha), 'estado': estado, 'observacion': observacion}

                # Registro en bitacora
                sql_bitacora = """
                    INSERT INTO bitacora (usuario_id, tabla, registro_id, accion, valor_previo, valor_nuevo, fecha_hora, ip)
                    VALUES (%s, 'asistencia', %s, %s, %s, %s, %s, %s);
                """
                cursor.execute(sql_bitacora, (
                    session['usuario_id'],
                    asistencia_id,
                    accion,
                    json.dumps(valor_previo, default=str) if valor_previo else None,
                    json.dumps(valor_nuevo, default=str),
                    ahora,
                    request.remote_addr
                ))

                conexion.commit()
                flash('Novedad de asistencia registrada correctamente.', 'success')
                return redirect(url_for('asistencia.listar', fecha=fecha))

            # Si es GET
            cursor.execute("""
                SELECT trabajador_id, cedula, nombres, apellidos, tipo_personal 
                FROM trabajador 
                WHERE activo = true 
                ORDER BY apellidos ASC, nombres ASC;
            """)
            trabajadores = cursor.fetchall()
            hoy = datetime.date.today().strftime('%Y-%m-%d')
            return render_template('asistencia_form.html', trabajadores=trabajadores, estados=ESTADOS_ASISTENCIA, hoy=hoy)
    except Exception as e:
        conexion.rollback()
        flash(f'Error al registrar asistencia: {e}', 'danger')
        return redirect(url_for('asistencia.listar'))
    finally:
        conexion.close()

# -------------------------------------------------------------------------
# 3. CARGA RÁPIDA DIARIA POR TIPO DE NÓMINA
# Permite marcar la presencia por defecto a todo un grupo de personal
# -------------------------------------------------------------------------
@asistencia_bp.route('/carga-diaria', methods=['POST'])
def carga_diaria():
    if not verificar_acceso():
        flash('Acceso denegado.', 'danger')
        return redirect(url_for('auth.dashboard'))

    fecha = request.form.get('fecha_carga')
    tipo_personal = request.form.get('tipo_personal_carga')

    if not fecha or not tipo_personal:
        flash('Debe seleccionar fecha y tipo de nómina.', 'warning')
        return redirect(url_for('asistencia.listar'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            # Obtener trabajadores activos del grupo
            cursor.execute("""
                SELECT trabajador_id FROM trabajador 
                WHERE tipo_personal = %s AND activo = true;
            """, (tipo_personal,))
            plantilla = cursor.fetchall()

            insertados = 0
            for t in plantilla:
                # Verificar si ya tiene novedad cargada para no sobreescribir reposos o permisos
                cursor.execute("""
                    SELECT asistencia_id FROM asistencia 
                    WHERE trabajador_id = %s AND fecha = %s;
                """, (t['trabajador_id'], fecha))
                if not cursor.fetchone():
                    cursor.execute("""
                        INSERT INTO asistencia (trabajador_id, fecha, estado, observacion)
                        VALUES (%s, %s, 'presente', 'Asistencia ordinaria');
                    """, (t['trabajador_id'], fecha))
                    insertados += 1

            conexion.commit()
            flash(f'Se generaron {insertados} registros ordinarios para la fecha {fecha}.', 'success')
            return redirect(url_for('asistencia.listar', fecha=fecha, tipo_personal=tipo_personal))
    except Exception as e:
        conexion.rollback()
        flash(f'Error en carga diaria: {e}', 'danger')
        return redirect(url_for('asistencia.listar'))
    finally:
        conexion.close()