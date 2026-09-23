from flask import Blueprint, render_template, request, redirect, url_for, session, flash, send_file
import io
import datetime
from app.database import get_db_connection
from app.modules.payroll_engine import calcular_quincena_trabajador

nomina_bp = Blueprint('nomina', __name__)

@nomina_bp.route('/generar', methods=['GET', 'POST'])
def generar():
    # Seguridad RBAC: Solo el analista_rrhh y directora_rrhh pueden elaborar prenominas
    roles_permitidos = ['analista_rrhh', 'directora_rrhh']
    if 'usuario_id' not in session or session.get('rol') not in roles_permitidos:
        flash('Acceso restringido: Solo el Analista o Directora de RRHH puede elaborar prenóminas.', 'danger')
        return redirect(url_for('auth.dashboard'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            # Tipos de nomina segun el marco institucional
            tipos_nomina = [
                ('empleado_fijo', 'Empleados Fijos'),
                ('obrero_fijo', 'Obreros Fijos'),
                ('alto_nivel', 'Alto Nivel (Concejales)'),
                ('libre_remocion', 'Libre Nombramiento y Remoción'),
                ('empleado_contratado', 'Empleados Contratados'),
                ('obrero_contratado', 'Obreros Contratados')
            ]

            if request.method == 'POST':
                tipo_personal = request.form.get('tipo_personal')
                fecha_inicio = request.form.get('fecha_inicio')
                fecha_fin = request.form.get('fecha_fin')
                descripcion = request.form.get('descripcion')

                # 1. Extraer los trabajadores activos de ese tipo de nomina
                sql_trabajadores = """
                    SELECT trabajador_id, cedula, nombres, apellidos, sueldo_base, 
                           hijos, nivel_instruccion, tipo_personal 
                    FROM trabajador 
                    WHERE tipo_personal = %s AND activo = true;
                """
                cursor.execute(sql_trabajadores, (tipo_personal,))
                plantilla = cursor.fetchall()

                if not plantilla:
                    flash(f'No hay trabajadores activos registrados en la nómina: {tipo_personal}', 'warning')
                    return render_template('nomina_generar.html', tipos_nomina=tipos_nomina)

                # 2. Extraer el catalogo de conceptos activos
                cursor.execute("SELECT * FROM concepto WHERE activo = true;")
                conceptos = cursor.fetchall()

                # 3. Procesar el calculo matematico para cada trabajador
                resultados = []
                gran_total_asig = 0
                gran_total_ded = 0
                gran_total_neto = 0

                for trab in plantilla:
                    calc = calcular_quincena_trabajador(trab, conceptos)
                    resultados.append(calc)
                    gran_total_asig += calc['total_asignaciones']
                    gran_total_ded += calc['total_deducciones']
                    gran_total_neto += calc['neto_pagar']

                # 4. Si el analista confirma el guardado definitivo en estado borrador
                if 'confirmar_guardar' in request.form:
                    # Crear cabecera en periodo_nomina
                    sql_periodo = """
                        INSERT INTO periodo_nomina (
                            descripcion, tipo_nomina, periodicidad, fecha_inicio, fecha_fin, 
                            estado, elaborada_por, fecha_elaboracion, 
                            total_asignaciones, total_deducciones, total_neto
                        ) VALUES (%s, %s, 'quincenal', %s, %s, 'borrador', %s, %s, %s, %s, %s);
                    """
                    ahora = datetime.datetime.now()
                    cursor.execute(sql_periodo, (
                        descripcion, tipo_personal, fecha_inicio, fecha_fin,
                        session['usuario_id'], ahora, gran_total_asig, gran_total_ded, gran_total_neto
                    ))
                    periodo_id = cursor.lastrowid

                    # Insertar cada trabajador en nomina_trabajador y sus renglones en nomina_detalle
                    for r in resultados:
                        sql_nt = """
                            INSERT INTO nomina_trabajador (
                                periodo_id, trabajador_id, dias_trabajados, 
                                total_asignaciones, total_deducciones, neto_pagar
                            ) VALUES (%s, %s, %s, %s, %s, %s);
                        """
                        cursor.execute(sql_nt, (
                            periodo_id, r['trabajador_id'], r['dias_trabajados'],
                            r['total_asignaciones'], r['total_deducciones'], r['neto_pagar']
                        ))
                        nomina_trabajador_id = cursor.lastrowid

                        # Insertar desglose inalterable (LOTTT Art 106)
                        sql_nd = """
                            INSERT INTO nomina_detalle (
                                nomina_trabajador_id, concepto_id, codigo_concepto, 
                                descripcion, tipo, monto
                            ) VALUES (%s, %s, %s, %s, %s, %s);
                        """
                        detalles_datos = [
                            (
                                nomina_trabajador_id, d['concepto_id'], d['codigo_concepto'],
                                d['descripcion'], d['tipo'], d['monto']
                            )
                            for d in r['detalles']
                        ]
                        cursor.executemany(sql_nd, detalles_datos)

                    conexion.commit()
                    flash(f'¡Pre-nómina generada exitosamente en estado BORRADOR! Periodo #{periodo_id}', 'success')
                    return redirect(url_for('nomina.historial'))

                # Si solo pulso "Calcular", mostramos la vista previa en pantalla
                return render_template(
                    'nomina_generar.html', 
                    tipos_nomina=tipos_nomina,
                    resultados=resultados,
                    parametros={
                        'tipo_personal': tipo_personal,
                        'fecha_inicio': fecha_inicio,
                        'fecha_fin': fecha_fin,
                        'descripcion': descripcion,
                        'total_asig': gran_total_asig,
                        'total_ded': gran_total_ded,
                        'total_neto': gran_total_neto
                    }
                )

    except Exception as e:
        conexion.rollback()
        flash(f'Error en el procesamiento de nómina: {e}', 'danger')
    finally:
        conexion.close()

    return render_template('nomina_generar.html', tipos_nomina=tipos_nomina)

@nomina_bp.route('/historial')
def historial():
    """Muestra la lista de periodos calculados y sus estados actuales."""
    if 'usuario_id' not in session:
        return redirect(url_for('auth.login'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            sql = """
                SELECT p.*, u.nombre_usuario AS analista_nombre
                FROM periodo_nomina p
                LEFT JOIN usuario u ON p.elaborada_por = u.usuario_id
                ORDER BY p.periodo_id DESC;
            """
            cursor.execute(sql)
            periodos = cursor.fetchall()
            return render_template('nomina_historial.html', periodos=periodos)
    finally:
        conexion.close()
        
@nomina_bp.route('/detalle/<int:periodo_id>')
def detalle(periodo_id):
    """Muestra el desglose completo de un periodo: cabecera, trabajadores y recibos."""
    if 'usuario_id' not in session:
        return redirect(url_for('auth.login'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            # 1. Cabecera del periodo con nombres de responsables
            sql_p = """
                SELECT p.*, 
                       u1.nombre_usuario AS analista_nom,
                       u2.nombre_usuario AS directora_nom,
                       u3.nombre_usuario AS presidente_nom
                FROM periodo_nomina p
                LEFT JOIN usuario u1 ON p.elaborada_por = u1.usuario_id
                LEFT JOIN usuario u2 ON p.revisada_por = u2.usuario_id
                LEFT JOIN usuario u3 ON p.aprobada_por = u3.usuario_id
                WHERE p.periodo_id = %s;
            """
            cursor.execute(sql_p, (periodo_id,))
            periodo = cursor.fetchone()

            if not periodo:
                flash('El periodo solicitado no existe.', 'warning')
                return redirect(url_for('nomina.historial'))

            # 2. Lista de trabajadores con sus totales en este periodo
            sql_trab = """
                SELECT nt.*, t.cedula, t.nombres, t.apellidos, t.banco, t.numero_cuenta, c.nombre AS cargo_nombre
                FROM nomina_trabajador nt
                INNER JOIN trabajador t ON nt.trabajador_id = t.trabajador_id
                INNER JOIN cargo c ON t.cargo_id = c.cargo_id
                WHERE nt.periodo_id = %s;
            """
            cursor.execute(sql_trab, (periodo_id,))
            trabajadores = cursor.fetchall()

            # 3. Renglones detallados (LOTTT Art. 106)
            for trab in trabajadores:
                sql_det = """
                    SELECT codigo_concepto, descripcion, tipo, monto 
                    FROM nomina_detalle 
                    WHERE nomina_trabajador_id = %s;
                """
                cursor.execute(sql_det, (trab['nomina_trabajador_id'],))
                trab['desglose'] = cursor.fetchall()

            return render_template('nomina_detalle.html', periodo=periodo, trabajadores=trabajadores)
    finally:
        conexion.close()

@nomina_bp.route('/revisar/<int:periodo_id>', methods=['POST'])
def revisar(periodo_id):
    """Accion de la Directora: Validar o Rechazar con observaciones."""
    if 'usuario_id' not in session or session.get('rol') != 'directora_rrhh':
        flash('Acceso restringido: Solo la Directora de RRHH puede validar nóminas.', 'danger')
        return redirect(url_for('nomina.historial'))

    accion = request.form.get('accion')
    motivo = request.form.get('observaciones_rechazo', '').strip()

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            ahora = datetime.datetime.now()
            if accion == 'validar':
                sql = """
                    UPDATE periodo_nomina 
                    SET estado = 'revisada', revisada_por = %s, fecha_revision = %s,
                        observaciones_rechazo = NULL 
                    WHERE periodo_id = %s;
                """
                cursor.execute(sql, (session['usuario_id'], ahora, periodo_id))
                conexion.commit()
                flash(f'Periodo #{periodo_id} VALIDADO. Remitido a Presidencia.', 'success')

            elif accion == 'rechazar':
                if not motivo:
                    flash('Debe ingresar obligatoriamente el motivo del rechazo.', 'danger')
                    return redirect(url_for('nomina.detalle', periodo_id=periodo_id))

                sql = """
                    UPDATE periodo_nomina 
                    SET estado = 'rechazada', revisada_por = NULL, fecha_revision = NULL,
                        observaciones_rechazo = %s 
                    WHERE periodo_id = %s;
                """
                cursor.execute(sql, (motivo, periodo_id))
                conexion.commit()
                flash(f'Periodo #{periodo_id} marcado como RECHAZADO con observaciones.', 'warning')

    finally:
        conexion.close()

    return redirect(url_for('nomina.detalle', periodo_id=periodo_id))

@nomina_bp.route('/aprobar/<int:periodo_id>', methods=['POST'])
def aprobar(periodo_id):
    """Accion del Presidente: Aprobacion legal o Devolucion con observaciones."""
    if 'usuario_id' not in session or session.get('rol') != 'presidente':
        flash('Acceso restringido: Solo el Presidente del Concejo puede aprobar nóminas.', 'danger')
        return redirect(url_for('nomina.historial'))

    accion = request.form.get('accion')
    motivo = request.form.get('observaciones_rechazo', '').strip()

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            ahora = datetime.datetime.now()
            if accion == 'aprobar':
                sql = """
                    UPDATE periodo_nomina 
                    SET estado = 'aprobada', aprobada_por = %s, fecha_aprobacion = %s,
                        observaciones_rechazo = NULL 
                    WHERE periodo_id = %s AND estado = 'revisada';
                """
                cursor.execute(sql, (session['usuario_id'], ahora, periodo_id))
                conexion.commit()
                flash(f'Periodo #{periodo_id} APROBADO institucionalmente.', 'success')

            elif accion == 'devolver':
                if not motivo:
                    flash('Debe ingresar obligatoriamente el motivo de la devolución.', 'danger')
                    return redirect(url_for('nomina.detalle', periodo_id=periodo_id))

                sql = """
                    UPDATE periodo_nomina 
                    SET estado = 'rechazada', revisada_por = NULL, fecha_revision = NULL,
                        observaciones_rechazo = %s 
                    WHERE periodo_id = %s;
                """
                cursor.execute(sql, (motivo, periodo_id))
                conexion.commit()
                flash(f'Periodo #{periodo_id} devuelto y marcado como RECHAZADO.', 'warning')

    finally:
        conexion.close()

    return redirect(url_for('nomina.detalle', periodo_id=periodo_id))

@nomina_bp.route('/exportar-patria/<int:periodo_id>')
def exportar_patria(periodo_id):
    """Genera y descarga el archivo plano TXT oficial para la plataforma Patria."""
    if 'usuario_id' not in session or session.get('rol') != 'directora_rrhh':
        flash('Acceso restringido: Solo la Directora de RRHH puede exportar a Patria.', 'danger')
        return redirect(url_for('nomina.historial'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            # 1. Verificar que el periodo este aprobado
            cursor.execute("SELECT * FROM periodo_nomina WHERE periodo_id = %s;", (periodo_id,))
            periodo = cursor.fetchone()

            if not periodo or periodo['estado'] not in ['aprobada', 'procesada_patria']:
                flash('Solo se pueden exportar nóminas aprobadas formalmente por Presidencia.', 'warning')
                return redirect(url_for('nomina.detalle', periodo_id=periodo_id))

            # 2. Consultar trabajadores del periodo con sus cuentas bancarias de 20 digitos
            sql = """
                SELECT t.cedula, t.numero_cuenta, nt.neto_pagar 
                FROM nomina_trabajador nt
                INNER JOIN trabajador t ON nt.trabajador_id = t.trabajador_id
                WHERE nt.periodo_id = %s;
            """
            cursor.execute(sql, (periodo_id,))
            registros = cursor.fetchall()

            # 3. Construccion del archivo plano TXT en memoria (sin tocar disco)
            # Formato estandar Patria: CEDULA;NUMERO_CUENTA_20_DIGITOS;MONTO_NETO
            lineas = []
            for r in registros:
                cedula_limpia = r['cedula'].replace('V-', '').replace('E-', '').replace('.', '').strip()
                cuenta = str(r['numero_cuenta']).strip()
                monto = f"{r['neto_pagar']:.2f}"
                lineas.append(f"{cedula_limpia};{cuenta};{monto}")

            contenido_txt = "\r\n".join(lineas)
            buffer = io.BytesIO(contenido_txt.encode('utf-8'))

            # 4. Actualizar estado a procesada_patria
            ahora = datetime.datetime.now()
            nombre_archivo = f"PATRIA_NOMINA_{periodo['tipo_nomina']}_PERIODO_{periodo_id}.txt"
            sql_up = """
                UPDATE periodo_nomina 
                SET estado = 'procesada_patria', fecha_proceso_patria = %s, archivo_txt_patria = %s 
                WHERE periodo_id = %s;
            """
            cursor.execute(sql_up, (ahora, nombre_archivo, periodo_id))
            conexion.commit()

            return send_file(
                buffer,
                as_attachment=True,
                download_name=nombre_archivo,
                mimetype='text/plain'
            )
    finally:
        conexion.close()
        
@nomina_bp.route('/recalcular/<int:periodo_id>', methods=['POST'])
def recalcular(periodo_id):
    """Permite al Analista o Directora recalcular una nomina en estado borrador o rechazada."""
    roles_permitidos = ['analista_rrhh', 'directora_rrhh']
    if 'usuario_id' not in session or session.get('rol') not in roles_permitidos:
        flash('Acceso restringido: No tiene permisos para recalcular nóminas.', 'danger')
        return redirect(url_for('nomina.historial'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            # 1. Verificar que el periodo exista y este en borrador o rechazada
            cursor.execute("SELECT * FROM periodo_nomina WHERE periodo_id = %s;", (periodo_id,))
            periodo = cursor.fetchone()

            if not periodo:
                flash('El periodo solicitado no existe.', 'warning')
                return redirect(url_for('nomina.historial'))

            if periodo['estado'] not in ['borrador', 'rechazada']:
                flash('Solo se pueden recalcular nóminas en estado Borrador o Rechazada.', 'warning')
                return redirect(url_for('nomina.detalle', periodo_id=periodo_id))

            # 2. Consultar la plantilla activa correspondiente al tipo de nomina
            sql_trabajadores = """
                SELECT trabajador_id, cedula, nombres, apellidos, sueldo_base, 
                       hijos, nivel_instruccion, tipo_personal 
                FROM trabajador 
                WHERE tipo_personal = %s AND activo = true;
            """
            cursor.execute(sql_trabajadores, (periodo['tipo_nomina'],))
            plantilla = cursor.fetchall()

            if not plantilla:
                flash(f'No hay trabajadores activos para el tipo: {periodo["tipo_nomina"]}', 'warning')
                return redirect(url_for('nomina.detalle', periodo_id=periodo_id))

            # 3. Consultar conceptos activos
            cursor.execute("SELECT * FROM concepto WHERE activo = true;")
            conceptos = cursor.fetchall()

            # 4. Limpiar los calculos viejos de este periodo (nomina_detalle y nomina_trabajador)
            # Primero obtenemos los IDs de nomina_trabajador para borrar sus renglones
            cursor.execute("SELECT nomina_trabajador_id FROM nomina_trabajador WHERE periodo_id = %s;", (periodo_id,))
            viejos_ids = [row['nomina_trabajador_id'] for row in cursor.fetchall()]

            if viejos_ids:
                formato_in = ','.join(['%s'] * len(viejos_ids))
                cursor.execute(f"DELETE FROM nomina_detalle WHERE nomina_trabajador_id IN ({formato_in});", viejos_ids)
                cursor.execute("DELETE FROM nomina_trabajador WHERE periodo_id = %s;", (periodo_id,))

            # 5. Ejecutar nuevamente el motor de calculo
            gran_total_asig = 0
            gran_total_ded = 0
            gran_total_neto = 0

            for trab in plantilla:
                calc = calcular_quincena_trabajador(trab, conceptos)
                gran_total_asig += calc['total_asignaciones']
                gran_total_ded += calc['total_deducciones']
                gran_total_neto += calc['neto_pagar']

                # Insertar cabecera individual
                sql_nt = """
                    INSERT INTO nomina_trabajador (
                        periodo_id, trabajador_id, dias_trabajados, 
                        total_asignaciones, total_deducciones, neto_pagar
                    ) VALUES (%s, %s, %s, %s, %s, %s);
                """
                cursor.execute(sql_nt, (
                    periodo_id, calc['trabajador_id'], calc['dias_trabajados'],
                    calc['total_asignaciones'], calc['total_deducciones'], calc['neto_pagar']
                ))
                nomina_trabajador_id = cursor.lastrowid

                # Insertar renglones de detalle (LOTTT 106)
                sql_nd = """
                    INSERT INTO nomina_detalle (
                        nomina_trabajador_id, concepto_id, codigo_concepto, 
                        descripcion, tipo, monto
                    ) VALUES (%s, %s, %s, %s, %s, %s);
                """
                detalles_datos = [
                    (
                        nomina_trabajador_id, d['concepto_id'], d['codigo_concepto'],
                        d['descripcion'], d['tipo'], d['monto']
                    )
                    for d in calc['detalles']
                ]
                cursor.executemany(sql_nd, detalles_datos)

            # 6. Actualizar periodo_nomina: vuelve a BORRADOR, actualiza montos y fecha
            ahora = datetime.datetime.now()
            sql_up = """
                UPDATE periodo_nomina 
                SET estado = 'borrador',
                    total_asignaciones = %s,
                    total_deducciones = %s,
                    total_neto = %s,
                    fecha_elaboracion = %s,
                    elaborada_por = %s
                WHERE periodo_id = %s;
            """
            cursor.execute(sql_up, (
                gran_total_asig, gran_total_ded, gran_total_neto, ahora, 
                session['usuario_id'], periodo_id
            ))

            conexion.commit()
            flash(f'¡Periodo #{periodo_id} recalculado y subsanado con éxito! Ha vuelto a estado BORRADOR para nueva revisión.', 'success')

    except Exception as e:
        conexion.rollback()
        flash(f'Error al recalcular nómina: {e}', 'danger')
    finally:
        conexion.close()

    return redirect(url_for('nomina.detalle', periodo_id=periodo_id))