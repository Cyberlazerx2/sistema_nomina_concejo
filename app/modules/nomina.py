import datetime
import io
from decimal import Decimal, ROUND_HALF_UP
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, send_file
from app.database import get_db_connection
from app.modules.payroll_engine import calcular_quincena_trabajador

nomina_bp = Blueprint('nomina', __name__)

@nomina_bp.route('/generar', methods=['GET', 'POST'])
def generar():
    roles_permitidos = ['analista_rrhh', 'directora_rrhh']
    if 'usuario_id' not in session or session.get('rol') not in roles_permitidos:
        flash('Acceso denegado: El Presidente y otros perfiles no tienen autorización para elaborar nóminas.', 'danger')
        return redirect(url_for('auth.dashboard'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            tipos_nomina = [
                ('empleado_fijo', 'Empleados Fijos'),
                ('obrero_fijo', 'Obreros Fijos'),
                ('alto_nivel', 'Alto Nivel (Concejales)'),
                ('libre_remocion', 'Libre Nombramiento y Remoción'),
                ('empleado_contratado', 'Empleados Contratados'),
                ('obrero_contratado', 'Obreros Contratados'),
                ('cestaticket', 'Cestaticket Mensual')
            ]

            if request.method == 'POST':
                tipo_personal = request.form.get('tipo_personal')
                fecha_inicio = request.form.get('fecha_inicio')
                fecha_fin = request.form.get('fecha_fin')
                descripcion = request.form.get('descripcion')

                es_cestaticket = (tipo_personal == 'cestaticket')
                periodicidad = 'mensual' if es_cestaticket else 'quincenal'

                # Si es cestaticket, incluye a todo el personal activo sin filtrar por tipo_personal
                if es_cestaticket:
                    sql_trabajadores = """
                        SELECT trabajador_id, cedula, nombres, apellidos, sueldo_base, 
                               hijos, nivel_instruccion, tipo_personal 
                        FROM trabajador 
                        WHERE activo = true;
                    """
                    cursor.execute(sql_trabajadores)
                else:
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

                cursor.execute("SELECT * FROM concepto WHERE activo = true;")
                conceptos = cursor.fetchall()

                resultados = []
                gran_total_asig = 0
                gran_total_ded = 0
                gran_total_neto = 0

                sql_ind = """
                    SELECT ct.valor, c.* FROM concepto_trabajador ct 
                    JOIN concepto c ON ct.concepto_id = c.concepto_id 
                    WHERE ct.trabajador_id = %s AND ct.activo = true 
                    AND (ct.fecha_fin IS NULL OR ct.fecha_fin >= CURDATE());
                """

                for trab in plantilla:
                    cursor.execute(sql_ind, (trab['trabajador_id'],))
                    conceptos_individuales = cursor.fetchall()

                    calc = calcular_quincena_trabajador(
                        trab, 
                        conceptos, 
                        conceptos_individuales, 
                        solo_cestaticket=es_cestaticket
                    )
                    resultados.append(calc)
                    gran_total_asig += calc['total_asignaciones']
                    gran_total_ded += calc['total_deducciones']
                    gran_total_neto += calc['neto_pagar']

                if 'confirmar_guardar' in request.form:
                    sql_periodo = """
                        INSERT INTO periodo_nomina (
                            descripcion, tipo_nomina, periodicidad, fecha_inicio, fecha_fin, 
                            estado, elaborada_por, fecha_elaboracion, 
                            total_asignaciones, total_deducciones, total_neto
                        ) VALUES (%s, %s, %s, %s, %s, 'borrador', %s, %s, %s, %s, %s);
                    """
                    ahora = datetime.datetime.now()
                    cursor.execute(sql_periodo, (
                        descripcion, tipo_personal, periodicidad, fecha_inicio, fecha_fin,
                        session['usuario_id'], ahora, gran_total_asig, gran_total_ded, gran_total_neto
                    ))
                    periodo_id = cursor.lastrowid

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
    if 'usuario_id' not in session:
        return redirect(url_for('auth.login'))

    roles_permitidos = ['analista_rrhh', 'directora_rrhh', 'presidente', 'tecnico_informatica']
    if session.get('rol') not in roles_permitidos:
        flash('Acceso denegado: El personal trabajador debe consultar sus recibos a través de su portal personal.', 'danger')
        return redirect(url_for('auth.dashboard'))

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
    if 'usuario_id' not in session:
        return redirect(url_for('auth.login'))

    roles_permitidos = ['analista_rrhh', 'directora_rrhh', 'presidente', 'tecnico_informatica']
    if session.get('rol') not in roles_permitidos:
        flash('Acceso denegado: El personal trabajador debe consultar sus recibos a través de su portal personal.', 'danger')
        return redirect(url_for('auth.dashboard'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
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

            sql_trab = """
                SELECT nt.*, t.cedula, t.nombres, t.apellidos, t.banco, t.numero_cuenta, c.nombre AS cargo_nombre
                FROM nomina_trabajador nt
                INNER JOIN trabajador t ON nt.trabajador_id = t.trabajador_id
                INNER JOIN cargo c ON t.cargo_id = c.cargo_id
                WHERE nt.periodo_id = %s;
            """
            cursor.execute(sql_trab, (periodo_id,))
            trabajadores = cursor.fetchall()

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
    if 'usuario_id' not in session or session.get('rol') != 'directora_rrhh':
        flash('Acceso restringido: Solo la Directora de RRHH puede exportar a Patria.', 'danger')
        return redirect(url_for('nomina.historial'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            cursor.execute("SELECT * FROM periodo_nomina WHERE periodo_id = %s;", (periodo_id,))
            periodo = cursor.fetchone()

            if not periodo or periodo['estado'] not in ['aprobada', 'procesada_patria']:
                flash('Solo se pueden exportar nóminas aprobadas formalmente por Presidencia.', 'warning')
                return redirect(url_for('nomina.detalle', periodo_id=periodo_id))

            sql = """
                SELECT t.cedula, t.numero_cuenta, nt.neto_pagar 
                FROM nomina_trabajador nt
                INNER JOIN trabajador t ON nt.trabajador_id = t.trabajador_id
                WHERE nt.periodo_id = %s;
            """
            cursor.execute(sql, (periodo_id,))
            registros = cursor.fetchall()

            lineas = []
            for r in registros:
                cedula_limpia = r['cedula'].replace('V-', '').replace('E-', '').replace('.', '').strip()
                cuenta = str(r['numero_cuenta']).strip()
                monto = f"{r['neto_pagar']:.2f}"
                lineas.append(f"{cedula_limpia};{cuenta};{monto}")

            contenido_txt = "\r\n".join(lineas)
            buffer = io.BytesIO(contenido_txt.encode('utf-8'))

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
    roles_permitidos = ['analista_rrhh', 'directora_rrhh']
    if 'usuario_id' not in session or session.get('rol') not in roles_permitidos:
        flash('Acceso restringido: No tiene permisos para recalcular nóminas.', 'danger')
        return redirect(url_for('nomina.historial'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            cursor.execute("SELECT * FROM periodo_nomina WHERE periodo_id = %s;", (periodo_id,))
            periodo = cursor.fetchone()

            if not periodo:
                flash('El periodo solicitado no existe.', 'warning')
                return redirect(url_for('nomina.historial'))

            if periodo['estado'] not in ['borrador', 'rechazada']:
                flash('Solo se pueden recalcular nóminas en estado Borrador o Rechazada.', 'warning')
                return redirect(url_for('nomina.detalle', periodo_id=periodo_id))

            es_cestaticket = (periodo['tipo_nomina'] == 'cestaticket')
            periodicidad = 'mensual' if es_cestaticket else 'quincenal'

            # Consulta condicional según tipo de nómina
            if es_cestaticket:
                sql_trabajadores = """
                    SELECT trabajador_id, cedula, nombres, apellidos, sueldo_base, 
                           hijos, nivel_instruccion, tipo_personal 
                    FROM trabajador 
                    WHERE activo = true;
                """
                cursor.execute(sql_trabajadores)
            else:
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

            cursor.execute("SELECT * FROM concepto WHERE activo = true;")
            conceptos = cursor.fetchall()

            cursor.execute("SELECT nomina_trabajador_id FROM nomina_trabajador WHERE periodo_id = %s;", (periodo_id,))
            viejos_ids = [row['nomina_trabajador_id'] for row in cursor.fetchall()]

            if viejos_ids:
                formato_in = ','.join(['%s'] * len(viejos_ids))
                cursor.execute(f"DELETE FROM nomina_detalle WHERE nomina_trabajador_id IN ({formato_in});", viejos_ids)
                cursor.execute("DELETE FROM nomina_trabajador WHERE periodo_id = %s;", (periodo_id,))

            gran_total_asig = 0
            gran_total_ded = 0
            gran_total_neto = 0

            sql_ind = """
                SELECT ct.valor, c.* FROM concepto_trabajador ct 
                JOIN concepto c ON ct.concepto_id = c.concepto_id 
                WHERE ct.trabajador_id = %s AND ct.activo = true 
                AND (ct.fecha_fin IS NULL OR ct.fecha_fin >= CURDATE());
            """

            for trab in plantilla:
                cursor.execute(sql_ind, (trab['trabajador_id'],))
                conceptos_individuales = cursor.fetchall()

                calc = calcular_quincena_trabajador(
                    trab, 
                    conceptos, 
                    conceptos_individuales, 
                    solo_cestaticket=es_cestaticket
                )
                gran_total_asig += calc['total_asignaciones']
                gran_total_ded += calc['total_deducciones']
                gran_total_neto += calc['neto_pagar']

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

            ahora = datetime.datetime.now()
            sql_up = """
                UPDATE periodo_nomina 
                SET estado = 'borrador',
                    periodicidad = %s,
                    total_asignaciones = %s,
                    total_deducciones = %s,
                    total_neto = %s,
                    fecha_elaboracion = %s,
                    elaborada_por = %s
                WHERE periodo_id = %s;
            """
            cursor.execute(sql_up, (
                periodicidad, gran_total_asig, gran_total_ded, gran_total_neto, ahora, 
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

@nomina_bp.route('/reporte-consolidado/<int:periodo_id>')
def reporte_consolidado(periodo_id):
    """Genera la sabana de nomina oficial consolidada con firmas institucionales."""
    if 'usuario_id' not in session:
        return redirect(url_for('auth.login'))

    roles_permitidos = ['analista_rrhh', 'directora_rrhh', 'presidente', 'tecnico_informatica']
    if session.get('rol') not in roles_permitidos:
        flash('Acceso denegado: El personal trabajador no tiene autorización para consultar la nómina consolidada.', 'danger')
        return redirect(url_for('auth.dashboard'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            # 1. Cabecera del periodo con trazabilidad de responsables
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

            # 2. Trabajadores incluidos en este periodo
            sql_trab = """
                SELECT nt.*, 
                       t.cedula, t.nombres, t.apellidos, t.fecha_ingreso, t.sueldo_base,
                       c.nombre AS cargo_nombre
                FROM nomina_trabajador nt
                INNER JOIN trabajador t ON nt.trabajador_id = t.trabajador_id
                INNER JOIN cargo c ON t.cargo_id = c.cargo_id
                WHERE nt.periodo_id = %s
                ORDER BY t.apellidos ASC, t.nombres ASC;
            """
            cursor.execute(sql_trab, (periodo_id,))
            trabajadores_raw = cursor.fetchall()

            es_cestaticket = (periodo['tipo_nomina'] == 'cestaticket')

            # 3. Mapear conceptos individuales de cada trabajador segun formato ODS
            filas = []
            totales = {
                'sueldo_mensual': Decimal('0.00'),
                'sueldo_quincenal': Decimal('0.00'),
                'ivss': Decimal('0.00'),
                'spf': Decimal('0.00'),
                'faov': Decimal('0.00'),
                'fejp': Decimal('0.00'),
                'total_deducciones': Decimal('0.00'),
                'subtotal': Decimal('0.00'),
                'prima_prof': Decimal('0.00'),
                'prima_antig': Decimal('0.00'),
                'prima_hijos': Decimal('0.00'),
                'otras_asig': Decimal('0.00'),
                'total_asignaciones': Decimal('0.00'),
                'neto_pagar': Decimal('0.00')
            }

            for idx, t in enumerate(trabajadores_raw, start=1):
                cursor.execute("""
                    SELECT codigo_concepto, tipo, monto 
                    FROM nomina_detalle 
                    WHERE nomina_trabajador_id = %s;
                """, (t['nomina_trabajador_id'],))
                detalles = cursor.fetchall()

                conceptos = {d['codigo_concepto']: Decimal(str(d['monto'])) for d in detalles}

                sueldo_mensual = Decimal(str(t['sueldo_base'])) if not es_cestaticket else Decimal('0.00')
                sueldo_quincenal = (sueldo_mensual / Decimal('2.00')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) if not es_cestaticket else Decimal('0.00')

                # Retenciones de ley
                ivss = conceptos.get('IVSS', Decimal('0.00'))
                spf = conceptos.get('RPE', Decimal('0.00'))
                faov = conceptos.get('FAOV', Decimal('0.00'))
                fejp = conceptos.get('FONDO_JUB', Decimal('0.00'))
                total_ded = Decimal(str(t['total_deducciones']))
                subtotal = (sueldo_quincenal - total_ded).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

                # Asignaciones y primas
                prima_prof = (
                    conceptos.get('PRIMA_PROF_TSU', Decimal('0.00')) +
                    conceptos.get('PRIMA_PROF_LIC', Decimal('0.00')) +
                    conceptos.get('PRIMA_PROF_ESP', Decimal('0.00'))
                )
                prima_antig = conceptos.get('PRIMA_ANTIG', Decimal('0.00'))
                prima_hijos = conceptos.get('PRIMA_HIJO', Decimal('0.00'))

                asignaciones_principales = prima_prof + prima_antig + prima_hijos + sueldo_quincenal
                otras_asig = Decimal(str(t['total_asignaciones'])) - asignaciones_principales
                if otras_asig < Decimal('0.00'):
                    otras_asig = Decimal('0.00')

                neto = Decimal(str(t['neto_pagar']))

                fila = {
                    'num': idx,
                    'cedula': t['cedula'],
                    'nombre_completo': f"{t['nombres']} {t['apellidos']}",
                    'cargo': t['cargo_nombre'],
                    'fecha_ingreso': t['fecha_ingreso'],
                    'sueldo_mensual': sueldo_mensual,
                    'sueldo_quincenal': sueldo_quincenal,
                    'ivss': ivss,
                    'spf': spf,
                    'faov': faov,
                    'fejp': fejp,
                    'total_deducciones': total_ded,
                    'subtotal': subtotal,
                    'prima_prof': prima_prof,
                    'prima_antig': prima_antig,
                    'prima_hijos': prima_hijos,
                    'otras_asig': otras_asig,
                    'total_asignaciones': Decimal(str(t['total_asignaciones'])),
                    'neto_pagar': neto
                }
                filas.append(fila)

                # Acumular totales de columna
                totales['sueldo_mensual'] += sueldo_mensual
                totales['sueldo_quincenal'] += sueldo_quincenal
                totales['ivss'] += ivss
                totales['spf'] += spf
                totales['faov'] += faov
                totales['fejp'] += fejp
                totales['total_deducciones'] += total_ded
                totales['subtotal'] += subtotal
                totales['prima_prof'] += prima_prof
                totales['prima_antig'] += prima_antig
                totales['prima_hijos'] += prima_hijos
                totales['otras_asig'] += otras_asig
                totales['total_asignaciones'] += Decimal(str(t['total_asignaciones']))
                totales['neto_pagar'] += neto

            # Denominaciones oficiales del Concejo
            mapa_nombres = {
                'alto_nivel': 'NÓMINA DE ALTO NIVEL (CONCEJALES Y DIRECTIVOS)',
                'libre_remocion': 'NÓMINA DE LIBRE NOMBRAMIENTO Y REMOCIÓN',
                'empleado_fijo': 'NÓMINA DE EMPLEADOS FIJOS (ORDINARIA)',
                'empleado_contratado': 'NÓMINA DE EMPLEADOS CONTRATADOS',
                'obrero_fijo': 'NÓMINA DE OBREROS FIJOS',
                'obrero_contratado': 'NÓMINA DE OBREROS CONTRATADOS ORDINARIA',
                'cestaticket': 'NÓMINA ESPECIAL DE BONO DE ALIMENTACIÓN CESTATICKET SOCIALISTA'
            }
            titulo_nomina = mapa_nombres.get(periodo['tipo_nomina'], periodo['tipo_nomina'].upper())

            return render_template(
                'nomina_consolidada.html',
                periodo=periodo,
                titulo_nomina=titulo_nomina,
                filas=filas,
                totales=totales,
                es_cestaticket=es_cestaticket
            )
    finally:
        conexion.close()