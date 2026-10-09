from flask import Blueprint, render_template, request, redirect, url_for, session, flash
import datetime
from app.database import get_db_connection

portal_bp = Blueprint('portal', __name__)

def obtener_datos_trabajador(cursor, usuario_id):
    """Obtiene los datos laborales del trabajador vinculado al usuario en sesión."""
    sql = """
        SELECT t.*, c.nombre AS cargo_nombre, d.nombre AS departamento_nombre
        FROM usuario u
        INNER JOIN trabajador t ON u.trabajador_id = t.trabajador_id
        INNER JOIN cargo c ON t.cargo_id = c.cargo_id
        INNER JOIN departamento d ON c.departamento_id = d.departamento_id
        WHERE u.usuario_id = %s AND t.activo = true;
    """
    cursor.execute(sql, (usuario_id,))
    return cursor.fetchone()

@portal_bp.route('/')
def inicio():
    if 'usuario_id' not in session or session.get('rol') != 'trabajador':
        flash('Acceso denegado: El portal es exclusivo para trabajadores.', 'danger')
        return redirect(url_for('auth.dashboard'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            # 1. Obtener expediente del trabajador asociado a la sesión
            sql_trabajador = """
                SELECT t.trabajador_id, t.cedula, t.nombres, t.apellidos, t.fecha_ingreso,
                       t.telefono, t.correo, t.direccion, t.banco, t.numero_cuenta,
                       c.nombre AS cargo_nombre, d.nombre AS departamento_nombre
                FROM usuario u
                INNER JOIN trabajador t ON u.trabajador_id = t.trabajador_id
                LEFT JOIN cargo c ON t.cargo_id = c.cargo_id
                LEFT JOIN departamento d ON c.departamento_id = d.departamento_id
                WHERE u.usuario_id = %s;
            """
            cursor.execute(sql_trabajador, (session['usuario_id'],))
            trabajador = cursor.fetchone()

            if not trabajador:
                flash('No se encontró ficha laboral asociada a su cuenta de usuario.', 'warning')
                return redirect(url_for('auth.logout'))

            # 2. Cómputo de Años de Servicio (Antigüedad)
            hoy = datetime.date.today()
            fecha_ing = trabajador['fecha_ingreso']
            if fecha_ing:
                anios_servicio = hoy.year - fecha_ing.year - ((hoy.month, hoy.day) < (fecha_ing.month, fecha_ing.day))
                anios_servicio = max(0, anios_servicio)
                anio_ingreso = fecha_ing.year
            else:
                anios_servicio = 0
                anio_ingreso = hoy.year

            # 3. Balance de Vacaciones según Art. 190 LOTTT
            # 15 días hábiles base + 1 día adicional por cada año posterior (tope: 15 adicionales, total 30)
            if anios_servicio >= 1:
                dias_vacaciones_total = min(15 + (anios_servicio - 1), 30)
            else:
                dias_vacaciones_total = 0  # En curso del primer año

            # Días disfrutados aprobados (tabla solicitud_vacaciones)
            dias_disfrutados = 0
            try:
                cursor.execute("""
                    SELECT COALESCE(SUM(dias_solicitados), 0) AS total_disfrutados
                    FROM solicitud_vacaciones
                    WHERE trabajador_id = %s AND estado = 'aprobada';
                """, (trabajador['trabajador_id'],))
                res_vac = cursor.fetchone()
                if res_vac:
                    dias_disfrutados = int(res_vac['total_disfrutados'])
            except Exception:
                dias_disfrutados = 0

            dias_disponibles = max(0, dias_vacaciones_total - dias_disfrutados)
            porcentaje_usado = int(round((dias_disfrutados / dias_vacaciones_total * 100))) if dias_vacaciones_total > 0 else 0

            # 4. Último cobro quincenal o mensual registrado (nómina aprobada)
            sql_ultimo_cobro = """
                SELECT nt.neto_pagar, pn.descripcion, pn.fecha_fin
                FROM nomina_trabajador nt
                INNER JOIN periodo_nomina pn ON nt.periodo_id = pn.periodo_id
                WHERE nt.trabajador_id = %s AND pn.estado IN ('aprobada', 'procesada_patria')
                ORDER BY pn.fecha_fin DESC
                LIMIT 1;
            """
            cursor.execute(sql_ultimo_cobro, (trabajador['trabajador_id'],))
            ultimo_recibo = cursor.fetchone()

            # 5. Próximo corte de pago ordinario
            if hoy.day <= 15:
                proximo_pago = f"15 de {hoy.strftime('%B')} de {hoy.year}"
            else:
                proximo_pago = f"30 de {hoy.strftime('%B')} de {hoy.year}"

            # 6. Actividad reciente combinada (recibos + solicitudes de cambio)
            actividad = []
            if ultimo_recibo:
                actividad.append({
                    'etiqueta': f"Recibo emitido: {ultimo_recibo['descripcion']}",
                    'detalle': f"Monto acreditado: Bs. {ultimo_recibo['neto_pagar']:,.2f}",
                    'fecha': ultimo_recibo['fecha_fin'].strftime('%d/%m/%Y') if hasattr(ultimo_recibo['fecha_fin'], 'strftime') else str(ultimo_recibo['fecha_fin'])
                })

            try:
                cursor.execute("""
                    SELECT campo, valor_nuevo, estado, fecha_solicitud
                    FROM solicitud_cambio_perfil
                    WHERE trabajador_id = %s
                    ORDER BY fecha_solicitud DESC
                    LIMIT 2;
                """, (trabajador['trabajador_id'],))
                for sol in cursor.fetchall():
                    actividad.append({
                        'etiqueta': f"Actualización de {sol['campo'].capitalize()}",
                        'detalle': f"Estatus de trámite: {sol['estado'].capitalize()}",
                        'fecha': sol['fecha_solicitud'].strftime('%d/%m/%Y') if hasattr(sol['fecha_solicitud'], 'strftime') else str(sol['fecha_solicitud'])
                    })
            except Exception:
                pass

            # Iniciales para el avatar
            iniciales = (trabajador['nombres'][:1] + trabajador['apellidos'][:1]).upper() if trabajador['nombres'] and trabajador['apellidos'] else "FN"

            return render_template(
                'portal/portal_inicio.html',
                trabajador=trabajador,
                iniciales=iniciales,
                anios_servicio=anios_servicio,
                anio_ingreso=anio_ingreso,
                dias_vacaciones_total=dias_vacaciones_total,
                dias_disfrutados=dias_disfrutados,
                dias_disponibles=dias_disponibles,
                porcentaje_usado=porcentaje_usado,
                ultimo_recibo=ultimo_recibo,
                proximo_pago=proximo_pago,
                actividad=actividad
            )
    finally:
        conexion.close()

# -------------------------------------------------------------------------
# 1. LISTA DE RECIBOS DE PAGO DEL TRABAJADOR (Art. 106 LOTTT)
# Solo muestra nóminas en estado 'aprobada' o 'procesada_patria'
# -------------------------------------------------------------------------
@portal_bp.route('/recibos')
def recibos():
    if 'usuario_id' not in session:
        flash('Debe iniciar sesión para acceder al portal.', 'warning')
        return redirect(url_for('auth.login'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            trabajador = obtener_datos_trabajador(cursor, session['usuario_id'])
            if not trabajador:
                flash('Su usuario no tiene un expediente laboral activo asociado.', 'warning')
                return redirect(url_for('auth.dashboard'))

            sql_recibos = """
                SELECT p.periodo_id, p.descripcion, p.tipo_nomina, p.fecha_inicio, p.fecha_fin, p.estado,
                       nt.nomina_trabajador_id, nt.total_asignaciones, nt.total_deducciones, nt.neto_pagar
                FROM nomina_trabajador nt
                INNER JOIN periodo_nomina p ON nt.periodo_id = p.periodo_id
                WHERE nt.trabajador_id = %s 
                  AND p.estado IN ('aprobada', 'procesada_patria')
                ORDER BY p.fecha_fin DESC, p.periodo_id DESC;
            """
            cursor.execute(sql_recibos, (trabajador['trabajador_id'],))
            recibos_lista = cursor.fetchall()

            return render_template('portal/portal_recibos.html', trabajador=trabajador, recibos=recibos_lista)
    finally:
        conexion.close()

# -------------------------------------------------------------------------
# 2. RECIBO DETALLADO IMPRIMIBLE (Comprobante oficial LOTTT 106)
# -------------------------------------------------------------------------
@portal_bp.route('/recibos/<int:periodo_id>')
def recibo_detalle(periodo_id):
    if 'usuario_id' not in session:
        flash('Debe iniciar sesión para consultar el recibo.', 'warning')
        return redirect(url_for('auth.login'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            trabajador = obtener_datos_trabajador(cursor, session['usuario_id'])
            if not trabajador:
                flash('Usuario sin expediente laboral asociado.', 'warning')
                return redirect(url_for('auth.dashboard'))

            # Consultar cabecera individual de nómina para este periodo aprobado
            sql_nt = """
                SELECT nt.*, p.descripcion, p.fecha_inicio, p.fecha_fin, p.tipo_nomina, p.estado
                FROM nomina_trabajador nt
                INNER JOIN periodo_nomina p ON nt.periodo_id = p.periodo_id
                WHERE nt.trabajador_id = %s 
                  AND p.periodo_id = %s
                  AND p.estado IN ('aprobada', 'procesada_patria');
            """
            cursor.execute(sql_nt, (trabajador['trabajador_id'], periodo_id))
            recibo = cursor.fetchone()

            if not recibo:
                flash('El recibo solicitado no está disponible o el periodo aún no ha sido aprobado institucionalmente.', 'warning')
                return redirect(url_for('portal.recibos'))

            # Consultar los renglones detallados de asignaciones y deducciones
            sql_det = """
                SELECT codigo_concepto, descripcion, tipo, monto
                FROM nomina_detalle
                WHERE nomina_trabajador_id = %s
                ORDER BY tipo ASC, codigo_concepto ASC;
            """
            cursor.execute(sql_det, (recibo['nomina_trabajador_id'],))
            detalles = cursor.fetchall()

            asignaciones = [d for d in detalles if d['tipo'] == 'asignacion']
            deducciones = [d for d in detalles if d['tipo'] == 'deduccion']

            return render_template('portal/portal_recibo_detalle.html', 
                                   trabajador=trabajador, 
                                   recibo=recibo, 
                                   asignaciones=asignaciones, 
                                   deducciones=deducciones)
    finally:
        conexion.close()

# -------------------------------------------------------------------------
# 3. PERFIL Y SOLICITUD DE ACTUALIZACIÓN DE DATOS (Contacto)
# Permite solicitar cambio exclusivamente de teléfono, correo y dirección
# -------------------------------------------------------------------------
@portal_bp.route('/perfil', methods=['GET', 'POST'])
def perfil():
    if 'usuario_id' not in session:
        flash('Debe iniciar sesión para ver su perfil.', 'warning')
        return redirect(url_for('auth.login'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            trabajador = obtener_datos_trabajador(cursor, session['usuario_id'])
            if not trabajador:
                flash('No cuenta con un perfil de trabajador asociado.', 'warning')
                return redirect(url_for('auth.dashboard'))

            if request.method == 'POST':
                telefono_nuevo = request.form.get('telefono', '').strip()
                correo_nuevo = request.form.get('correo', '').strip()
                direccion_nueva = request.form.get('direccion', '').strip()

                cambios = [
                    ('telefono', (trabajador.get('telefono') or '').strip(), telefono_nuevo),
                    ('correo', (trabajador.get('correo') or '').strip(), correo_nuevo),
                    ('direccion', (trabajador.get('direccion') or '').strip(), direccion_nueva)
                ]

                solicitudes_creadas = 0
                ahora = datetime.datetime.now()

                sql_sol = """
                    INSERT INTO solicitud_cambio_perfil 
                    (trabajador_id, campo, valor_actual, valor_nuevo, estado, fecha_solicitud)
                    VALUES (%s, %s, %s, %s, 'pendiente', %s);
                """

                for campo, actual, nuevo in cambios:
                    # Se registra solicitud solo si el valor ingresado es diferente al actual
                    if nuevo and nuevo != actual:
                        cursor.execute(sql_sol, (
                            trabajador['trabajador_id'],
                            campo,
                            actual,
                            nuevo,
                            ahora
                        ))
                        solicitudes_creadas += 1

                if solicitudes_creadas > 0:
                    conexion.commit()
                    flash(f'Se remitieron {solicitudes_creadas} solicitud(es) de actualización a Recursos Humanos.', 'success')
                else:
                    flash('No se detectaron modificaciones en los datos ingresados respecto a su expediente actual.', 'info')

                return redirect(url_for('portal.perfil'))

            # Consultar historial de solicitudes del trabajador
            cursor.execute("""
                SELECT solicitud_id, campo, valor_actual, valor_nuevo, estado, 
                       fecha_solicitud, fecha_respuesta, motivo_rechazo 
                FROM solicitud_cambio_perfil 
                WHERE trabajador_id = %s 
                ORDER BY solicitud_id DESC;
            """, (trabajador['trabajador_id'],))
            solicitudes = cursor.fetchall()

            return render_template('portal/portal_perfil.html', trabajador=trabajador, solicitudes=solicitudes)
    finally:
        conexion.close()