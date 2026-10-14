import datetime
import uuid
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
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

def obtener_trabajador_id_actual(cursor):
    """
    Recupera el trabajador_id de la sesión o lo busca directamente
    en la tabla 'usuario' mediante el usuario_id activo.
    """
    t_id = session.get('trabajador_id')
    if t_id:
        return t_id

    u_id = session.get('usuario_id')
    if not u_id:
        return None

    # Consultar relación en la tabla usuario
    cursor.execute("SELECT trabajador_id FROM usuario WHERE usuario_id = %s;", (u_id,))
    res = cursor.fetchone()
    if res and res.get('trabajador_id'):
        session['trabajador_id'] = res['trabajador_id']
        return res['trabajador_id']

    return None

# -------------------------------------------------------------------------
# 1. PORTAL DE INICIO (Resumen ejecutivo del trabajador)
# -------------------------------------------------------------------------
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
                dias_vacaciones_total = 0

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
# 2. CATÁLOGO HISTÓRICO DE RECIBOS DE PAGO (Art. 106 LOTTT)
# -------------------------------------------------------------------------
@portal_bp.route('/recibos')
def recibos():
    if 'usuario_id' not in session or session.get('rol') != 'trabajador':
        flash('Acceso restringido al portal del trabajador.', 'danger')
        return redirect(url_for('auth.dashboard'))

    anio_actual = datetime.date.today().year
    anio_seleccionado = request.args.get('anio', default=str(anio_actual))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            # 1. Obtener ID del trabajador asociado
            cursor.execute("""
                SELECT t.trabajador_id, t.cedula, t.nombres, t.apellidos, c.nombre AS cargo_nombre
                FROM usuario u
                INNER JOIN trabajador t ON u.trabajador_id = t.trabajador_id
                LEFT JOIN cargo c ON t.cargo_id = c.cargo_id
                WHERE u.usuario_id = %s;
            """, (session['usuario_id'],))
            trabajador = cursor.fetchone()

            if not trabajador:
                flash('No se encontró expediente laboral asociado.', 'danger')
                return redirect(url_for('auth.dashboard'))

            # 2. Historial de recibos correspondientes a nóminas aprobadas
            sql_recibos = """
                SELECT nt.nomina_trabajador_id, nt.periodo_id, nt.total_asignaciones,
                       nt.total_deducciones, nt.neto_pagar,
                       pn.descripcion, pn.fecha_inicio, pn.fecha_fin, pn.tipo_nomina,
                       pn.periodicidad, pn.estado, YEAR(pn.fecha_fin) AS anio
                FROM nomina_trabajador nt
                INNER JOIN periodo_nomina pn ON nt.periodo_id = pn.periodo_id
                WHERE nt.trabajador_id = %s 
                  AND pn.estado IN ('aprobada', 'procesada_patria')
                  AND YEAR(pn.fecha_fin) = %s
                ORDER BY pn.fecha_fin DESC;
            """
            cursor.execute(sql_recibos, (trabajador['trabajador_id'], anio_seleccionado))
            recibos_lista = cursor.fetchall()

            # 3. Años fiscales con nóminas disponibles para el filtro
            cursor.execute("""
                SELECT DISTINCT YEAR(pn.fecha_fin) AS anio
                FROM nomina_trabajador nt
                INNER JOIN periodo_nomina pn ON nt.periodo_id = pn.periodo_id
                WHERE nt.trabajador_id = %s AND pn.estado IN ('aprobada', 'procesada_patria')
                ORDER BY anio DESC;
            """, (trabajador['trabajador_id'],))
            anios_disponibles = [row['anio'] for row in cursor.fetchall()]
            if not anios_disponibles:
                anios_disponibles = [anio_actual]

            acumulado_neto = sum(float(r['neto_pagar']) for r in recibos_lista)

            return render_template(
                'portal/portal_recibos.html',
                trabajador=trabajador,
                recibos=recibos_lista,
                anios=anios_disponibles,
                anio_activo=str(anio_seleccionado),
                acumulado_neto=acumulado_neto
            )
    finally:
        conexion.close()


# -------------------------------------------------------------------------
# 3. COMPROBANTE OFICIAL DE PAGO IMPRIMIBLE (Art. 106 LOTTT)
# -------------------------------------------------------------------------
@portal_bp.route('/recibo/<int:periodo_id>')
def recibo_detalle(periodo_id):
    if 'usuario_id' not in session or session.get('rol') != 'trabajador':
        flash('Acceso restringido.', 'danger')
        return redirect(url_for('auth.dashboard'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            # 1. Obtener datos del trabajador y del periodo (sin nt.sueldo_base)
            sql = """
                    SELECT nt.nomina_trabajador_id, nt.total_asignaciones,
                        nt.total_deducciones, nt.neto_pagar,
                        t.trabajador_id, t.cedula, t.nombres, t.apellidos, t.fecha_ingreso,
                        t.banco, t.numero_cuenta, t.sueldo_base,
                        c.nombre AS cargo_nombre, d.nombre AS departamento_nombre,
                        pn.periodo_id, pn.descripcion, pn.fecha_inicio, pn.fecha_fin,
                        pn.tipo_nomina, pn.periodicidad, pn.estado
                    FROM usuario u
                    INNER JOIN trabajador t ON u.trabajador_id = t.trabajador_id
                    INNER JOIN nomina_trabajador nt ON t.trabajador_id = nt.trabajador_id
                    INNER JOIN periodo_nomina pn ON nt.periodo_id = pn.periodo_id
                    LEFT JOIN cargo c ON t.cargo_id = c.cargo_id
                    LEFT JOIN departamento d ON c.departamento_id = d.departamento_id
                    WHERE u.usuario_id = %s 
                    AND pn.periodo_id = %s
                    AND pn.estado IN ('aprobada', 'procesada_patria');
                """
            cursor.execute(sql, (session['usuario_id'], periodo_id))
            recibo = cursor.fetchone()

            if not recibo:
                flash('El comprobante solicitado no existe o no ha sido aprobado legalmente.', 'warning')
                return redirect(url_for('portal.recibos'))

            # 2. Desglose analítico de conceptos (Asignaciones y Deducciones)
            desglose = []
            try:
                cursor.execute("""
                    SELECT tipo, descripcion, monto 
                    FROM nomina_detalle 
                    WHERE nomina_trabajador_id = %s
                    ORDER BY tipo ASC, monto DESC;
                """, (recibo['nomina_trabajador_id'],))
                desglose = cursor.fetchall()
            except Exception:
                desglose = []

            asignaciones = [d for d in desglose if d.get('tipo') == 'asignacion']
            deducciones = [d for d in desglose if d.get('tipo') == 'deduccion']
            fecha_emision = datetime.date.today().strftime('%d/%m/%Y')

            return render_template(
                'portal/portal_recibo_detalle.html',
                r=recibo,
                asignaciones=asignaciones,
                deducciones=deducciones,
                fecha_emision=fecha_emision
            )
    finally:
        conexion.close()


# -------------------------------------------------------------------------
# 4. PERFIL Y SOLICITUD DE ACTUALIZACIÓN DE DATOS (Contacto)
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
        
# -------------------------------------------------------------------------
# PORTAL: Listado y Solicitud de Constancias de Trabajo
# -------------------------------------------------------------------------
@portal_bp.route('/constancias', methods=['GET', 'POST'])
def constancias():
    if 'usuario_id' not in session or session.get('rol') != 'trabajador':
        flash('Acceso restringido al portal del funcionario.', 'danger')
        return redirect(url_for('auth.login'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            trabajador_id = obtener_trabajador_id_actual(cursor)

            if not trabajador_id:
                flash('Su cuenta de usuario no tiene una ficha de trabajador vinculada en el sistema. Contacte a Recursos Humanos.', 'danger')
                return redirect(url_for('portal.inicio'))

            if request.method == 'POST':
                tipo = request.form.get('tipo', 'con_sueldo')
                destinatario = request.form.get('destinatario', 'A QUIEN PUEDA INTERESAR').strip()
                motivo = request.form.get('motivo', '').strip()

                cursor.execute("""
                    INSERT INTO solicitud_constancia (trabajador_id, tipo, destinatario, motivo, estado, fecha_solicitud)
                    VALUES (%s, %s, %s, %s, 'pendiente', NOW());
                """, (trabajador_id, tipo, destinatario or 'A QUIEN PUEDA INTERESAR', motivo or None))
                conexion.commit()
                flash('Solicitud de constancia de trabajo registrada con éxito.', 'success')
                return redirect(url_for('portal.constancias'))

            # Historial de constancias del funcionario
            cursor.execute("""
                SELECT * FROM solicitud_constancia
                WHERE trabajador_id = %s
                ORDER BY constancia_id DESC;
            """, (trabajador_id,))
            historial = cursor.fetchall()

            return render_template('portal/portal_constancias.html', constancias=historial)
    finally:
        conexion.close()


# -------------------------------------------------------------------------
# PORTAL / RRHH: Visualización e Impresión de Constancia Emitida
# -------------------------------------------------------------------------
@portal_bp.route('/constancias/<int:constancia_id>/imprimir')
def imprimir_constancia(constancia_id):
    if 'usuario_id' not in session:
        return redirect(url_for('auth.login'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            sql = """
                SELECT sc.*, 
                       t.cedula, t.nombres, t.apellidos, t.fecha_ingreso, t.sueldo_base,
                       c.nombre AS cargo_nombre, d.nombre AS departamento_nombre,
                       u.nombre_usuario AS emitido_por_usuario
                FROM solicitud_constancia sc
                INNER JOIN trabajador t ON sc.trabajador_id = t.trabajador_id
                INNER JOIN cargo c ON t.cargo_id = c.cargo_id
                LEFT JOIN departamento d ON c.departamento_id = d.departamento_id
                LEFT JOIN usuario u ON sc.emitida_por = u.usuario_id
                WHERE sc.constancia_id = %s;
            """
            cursor.execute(sql, (constancia_id,))
            constancia = cursor.fetchone()

            if not constancia or constancia['estado'] != 'emitida':
                flash('La constancia aún no ha sido emitida o no existe.', 'warning')
                return redirect(url_for('portal.constancias'))

            # Validación de pertenencia si consulta un trabajador
            trabajador_id = obtener_trabajador_id_actual(cursor)
            if session.get('rol') == 'trabajador' and constancia['trabajador_id'] != trabajador_id:
                flash('No tiene autorización para consultar este documento.', 'danger')
                return redirect(url_for('portal.constancias'))

            meses = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']
            hoy = datetime.date.today()
            fecha_texto = f"a los {hoy.day} días del mes de {meses[hoy.month - 1]} de {hoy.year}"

            return render_template(
                'portal/portal_constancia_imprimir.html',
                c=constancia,
                fecha_texto=fecha_texto
            )
    finally:
        conexion.close()