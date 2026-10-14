import datetime
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from app.database import get_db_connection

asistencia_bp = Blueprint('asistencia', __name__)

@asistencia_bp.route('/')
@asistencia_bp.route('/listar')
def listar():
    if 'usuario_id' not in session or session.get('rol') not in ['analista_rrhh', 'directora_rrhh']:
        flash('Acceso denegado: Módulo restringido a Recursos Humanos.', 'danger')
        return redirect(url_for('auth.dashboard'))

    # Fecha seleccionada (por defecto hoy)
    fecha_str = request.args.get('fecha')
    hoy = datetime.date.today()
    try:
        fecha_activa = datetime.datetime.strptime(fecha_str, '%Y-%m-%d').date() if fecha_str else hoy
    except ValueError:
        fecha_activa = hoy

    fecha_anterior = (fecha_activa - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
    fecha_siguiente = (fecha_activa + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
    es_futuro = fecha_activa > hoy

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            # 1. Obtener departamentos para el filtro de categorias
            cursor.execute("SELECT departamento_id, nombre FROM departamento ORDER BY nombre ASC;")
            departamentos = cursor.fetchall()

            # 2. Consultar todos los trabajadores activos y cruzar con la asistencia del día
            sql = """
                SELECT t.trabajador_id, t.cedula, t.nombres, t.apellidos,
                       c.nombre AS cargo_nombre, d.nombre AS departamento_nombre,
                       a.asistencia_id, a.estado, a.justificacion
                FROM trabajador t
                LEFT JOIN cargo c ON t.cargo_id = c.cargo_id
                LEFT JOIN departamento d ON c.departamento_id = d.departamento_id
                LEFT JOIN asistencia a ON t.trabajador_id = a.trabajador_id AND a.fecha = %s
                WHERE t.activo = true
                ORDER BY d.nombre ASC, t.apellidos ASC;
            """
            cursor.execute(sql, (fecha_activa,))
            filas = cursor.fetchall()

            # 3. Procesar datos y conteos de estado
            conteos = {
                'todos': len(filas),
                'presente': 0,
                'reposo': 0,
                'falta': 0,
                'vacaciones': 0,
                'sin_marcar': 0
            }

            for f in filas:
                estado = f['estado'] or 'sin_marcar'
                f['estado_normalizado'] = estado
                if estado in conteos:
                    conteos[estado] += 1
                else:
                    conteos['sin_marcar'] += 1

                # Iniciales para avatar
                nom = f['nombres'].split()[0] if f['nombres'] else ''
                ape = f['apellidos'].split()[0] if f['apellidos'] else ''
                f['iniciales'] = (nom[:1] + ape[:1]).upper() or 'TR'

            return render_template(
                'asistencia/asistencia_lista.html',
                fecha_activa=fecha_activa.strftime('%Y-%m-%d'),
                fecha_formateada=fecha_activa.strftime('%d/%m/%Y'),
                fecha_anterior=fecha_anterior,
                fecha_siguiente=fecha_siguiente,
                es_futuro=es_futuro,
                es_hoy=(fecha_activa == hoy),
                departamentos=departamentos,
                trabajadores=filas,
                conteos=conteos
            )
    finally:
        conexion.close()

# -------------------------------------------------------------------------
# Marcado Masivo de Asistencia (Bulk Presence)
# -------------------------------------------------------------------------
@asistencia_bp.route('/marcar-masivo', methods=['POST'])
def marcar_masivo():
    if 'usuario_id' not in session or session.get('rol') not in ['analista_rrhh', 'directora_rrhh']:
        return jsonify({'error': 'No autorizado'}), 403

    datos = request.get_json() or {}
    fecha = datos.get('fecha')
    trabajador_ids = datos.get('trabajador_ids', [])

    if not fecha or not trabajador_ids:
        return jsonify({'error': 'Datos incompletos para el registro'}), 400

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            for trab_id in trabajador_ids:
                # Comprobar si ya existe registro para actualizarlo o insertarlo
                cursor.execute("""
                    SELECT asistencia_id FROM asistencia 
                    WHERE trabajador_id = %s AND fecha = %s;
                """, (trab_id, fecha))
                existe = cursor.fetchone()

                if existe:
                    cursor.execute("""
                        UPDATE asistencia 
                        SET estado = 'presente', justificacion = 'Marcado masivo ordinario'
                        WHERE asistencia_id = %s;
                    """, (existe['asistencia_id'],))
                else:
                    cursor.execute("""
                        INSERT INTO asistencia (trabajador_id, fecha, estado, justificacion)
                        VALUES (%s, %s, 'presente', 'Marcado masivo ordinario');
                    """, (trab_id, fecha))

            conexion.commit()
            return jsonify({'success': True, 'total': len(trabajador_ids)})
    except Exception as e:
        conexion.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conexion.close()

# -------------------------------------------------------------------------
# Registro de Novedades (Reposos Médicos / Faltas Injustificadas)
# -------------------------------------------------------------------------
@asistencia_bp.route('/registrar-novedad', methods=['POST'])
def registrar_novedad():
    if 'usuario_id' not in session or session.get('rol') not in ['analista_rrhh', 'directora_rrhh']:
        flash('Acceso denegado.', 'danger')
        return redirect(url_for('asistencia.listar'))

    trabajador_id = request.form.get('trabajador_id')
    tipo = request.form.get('tipo')  # 'reposo' o 'falta'
    fecha_desde = request.form.get('desde')
    fecha_hasta = request.form.get('hasta') or fecha_desde
    certificado = request.form.get('certificado', '').strip()
    observaciones = request.form.get('observaciones', '').strip()

    if not trabajador_id or not fecha_desde:
        flash('Debe seleccionar el trabajador y la fecha correspondiente.', 'danger')
        return redirect(url_for('asistencia.listar'))

    # Formatear la justificación
    if tipo == 'reposo':
        estado_bd = 'reposo'
        detalles = []
        if certificado:
            detalles.append(f"Certificado IVSS/Médico: {certificado}")
        if observaciones:
            detalles.append(observaciones)
        justificacion = " · ".join(detalles) if detalles else "Reposo Médico Avalado"
    else:
        estado_bd = 'falta'
        justificacion = observaciones or "Inasistencia injustificada sin soporte"

    # Generar rango de días
    try:
        f_inicio = datetime.datetime.strptime(fecha_desde, '%Y-%m-%d').date()
        f_fin = datetime.datetime.strptime(fecha_hasta, '%Y-%m-%d').date()
    except ValueError:
        flash('Formato de fecha inválido.', 'danger')
        return redirect(url_for('asistencia.listar'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            actual = f_inicio
            dias_registrados = 0
            while actual <= f_fin:
                # Omitir fines de semana (sábado=5, domingo=6)
                if actual.weekday() < 5:
                    cursor.execute("""
                        SELECT asistencia_id FROM asistencia 
                        WHERE trabajador_id = %s AND fecha = %s;
                    """, (trabajador_id, actual))
                    reg = cursor.fetchone()

                    if reg:
                        cursor.execute("""
                            UPDATE asistencia 
                            SET estado = %s, justificacion = %s
                            WHERE asistencia_id = %s;
                        """, (estado_bd, justificacion, reg['asistencia_id']))
                    else:
                        cursor.execute("""
                            INSERT INTO asistencia (trabajador_id, fecha, estado, justificacion)
                            VALUES (%s, %s, %s, %s);
                        """, (trabajador_id, actual, estado_bd, justificacion))
                    dias_registrados += 1
                actual += datetime.timedelta(days=1)

            conexion.commit()
            flash(f"Novedad ({estado_bd.upper()}) registrada exitosamente para {dias_registrados} día(s) hábil(es).", 'success')
    except Exception as e:
        conexion.rollback()
        flash(f"Error al registrar la incidencia: {e}", 'danger')
    finally:
        conexion.close()

    return redirect(url_for('asistencia.listar', fecha=fecha_desde))