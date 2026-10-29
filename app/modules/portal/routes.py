import datetime
import uuid
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from app.database import get_db_connection
from app.modules.portal.numero_letras import numero_a_letras
from decimal import ROUND_HALF_UP, Decimal

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
                    SELECT COALESCE(SUM(dias_habiles), 0) AS total_disfrutados
                    FROM solicitud_vacaciones
                    WHERE trabajador_id = %s AND estado IN ('aprobada', 'disfrutada');
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
                flash('Su cuenta de usuario no tiene una ficha de trabajador vinculada.', 'danger')
                return redirect(url_for('portal.inicio'))

            if request.method == 'POST':
                tipo = request.form.get('tipo', 'con_sueldo')
                destinatario = request.form.get('destinatario', 'A QUIEN PUEDA INTERESAR').strip()
                motivo = request.form.get('motivo', '').strip()

                cursor.execute("""
                    INSERT INTO solicitud_constancia (trabajador_id, tipo, destinatario, motivo, estado, fecha_solicitud)
                    VALUES (%s, %s, %s, %s, 'solicitada', NOW());
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
                       c.nombre AS cargo_nombre, d.nombre AS departamento_nombre
                FROM solicitud_constancia sc
                INNER JOIN trabajador t ON sc.trabajador_id = t.trabajador_id
                INNER JOIN cargo c ON t.cargo_id = c.cargo_id
                LEFT JOIN departamento d ON c.departamento_id = d.departamento_id
                WHERE sc.constancia_id = %s;
            """
            cursor.execute(sql, (constancia_id,))
            constancia = cursor.fetchone()

            # Validación correcta de existencia y estado aprobado
            if not constancia or constancia['estado'] not in ['emitida', 'firmada_entregada']:
                flash('La constancia aún no ha sido emitida por Recursos Humanos o no existe.', 'warning')
                return redirect(url_for('portal.constancias'))

            # Validación de autorización si consulta un trabajador
            trabajador_id = obtener_trabajador_id_actual(cursor)
            if session.get('rol') == 'trabajador' and constancia['trabajador_id'] != trabajador_id:
                flash('No tiene autorización para consultar este documento.', 'danger')
                return redirect(url_for('portal.constancias'))

            # Sueldo mensual base institucional (quincena * 2)
            sueldo_base_mensual = float(constancia['sueldo_base'] or 0.00)
            sueldo_en_letras = numero_a_letras(sueldo_base_mensual)

            meses = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']
            hoy = datetime.date.today()

            return render_template(
                'portal/portal_constancia_andre.html',
                c=constancia,
                sueldo_num=f"{sueldo_base_mensual:,.2f}",
                sueldo_letras=sueldo_en_letras,
                dia=f"{hoy.day:02d}",
                mes=meses[hoy.month - 1],
                ano=hoy.year
            )
    finally:
        conexion.close()
        
# -------------------------------------------------------------------------
# PORTAL: Solicitud y Lista de Permisos Laborales (Ordinarios y Pre/Postnatal)
# -------------------------------------------------------------------------
@portal_bp.route('/permisos', methods=['GET', 'POST'])
def permisos():
    if 'usuario_id' not in session or session.get('rol') != 'trabajador':
        return redirect(url_for('auth.login'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            t_id = obtener_trabajador_id_actual(cursor)
            if not t_id:
                flash('Cuenta no vinculada a una ficha de trabajador.', 'danger')
                return redirect(url_for('portal.inicio'))

            if request.method == 'POST':
                tipo_permiso = request.form.get('tipo_permiso', 'ordinario')
                fecha_inicio = request.form.get('fecha_inicio')
                fecha_fin = request.form.get('fecha_fin')
                duracion = request.form.get('duracion', '').strip()
                motivo = request.form.get('motivo', '').strip()

                cursor.execute("""
                    INSERT INTO solicitud_permiso (
                        trabajador_id, tipo_permiso, duracion, fecha_inicio, 
                        fecha_fin, motivo, estado, fecha_solicitud
                    ) VALUES (%s, %s, %s, %s, %s, %s, 'solicitado', NOW());
                """, (t_id, tipo_permiso, duracion, fecha_inicio, fecha_fin, motivo))
                conexion.commit()
                flash('Solicitud de permiso generada. Imprima la boleta oficial para la firma física de su supervisor.', 'success')
                return redirect(url_for('portal.permisos'))

            cursor.execute("""
                SELECT * FROM solicitud_permiso 
                WHERE trabajador_id = %s 
                ORDER BY permiso_id DESC;
            """, (t_id,))
            historial = cursor.fetchall()
            return render_template('portal/portal_permisos.html', permisos=historial)
    finally:
        conexion.close()

# -------------------------------------------------------------------------
# IMPRIMIR: Boleta Oficial de Permiso (Formato Exacto FORMATO DE PERMISOS.docx)
# -------------------------------------------------------------------------
@portal_bp.route('/permisos/<int:permiso_id>/imprimir-boleta')
def imprimir_boleta_permiso(permiso_id):
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
                WHERE sp.permiso_id = %s;
            """
            cursor.execute(sql, (permiso_id,))
            permiso = cursor.fetchone()
            if not permiso:
                flash('Permiso no encontrado.', 'warning')
                return redirect(url_for('portal.permisos'))

            hoy = datetime.date.today()
            return render_template('portal/portal_permiso_boleta.html', p=permiso, hoy=hoy)
    finally:
        conexion.close()

# -------------------------------------------------------------------------
# IMPRIMIR: Solicitud Pre y Postnatal (Formato Exacto EDUMARLI ALCINA)
# -------------------------------------------------------------------------
@portal_bp.route('/permisos/<int:permiso_id>/imprimir-maternidad')
def imprimir_maternidad(permiso_id):
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
                WHERE sp.permiso_id = %s;
            """
            cursor.execute(sql, (permiso_id,))
            permiso = cursor.fetchone()
            hoy = datetime.date.today()
            return render_template('portal/portal_maternidad_imprimir.html', p=permiso, hoy=hoy)
    finally:
        conexion.close()

# -------------------------------------------------------------------------
# FAOV: Estado de Cuenta Individual y Cotizaciones BANAVIH
# -------------------------------------------------------------------------
@portal_bp.route('/faov', methods=['GET', 'POST'])
def faov_estado_cuenta():
    if 'usuario_id' not in session or session.get('rol') != 'trabajador':
        flash('Acceso restringido al portal del funcionario.', 'danger')
        return redirect(url_for('auth.login'))

    anio_actual = datetime.date.today().year
    anio_seleccionado = request.args.get('anio', default=str(anio_actual))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            t_id = obtener_trabajador_id_actual(cursor)
            if not t_id:
                flash('Cuenta no vinculada a una ficha de trabajador.', 'danger')
                return redirect(url_for('portal.inicio'))

            # Procesar nueva solicitud de certificación
            if request.method == 'POST':
                anio_sol = request.form.get('anio_solicitud', anio_actual)
                motivo = request.form.get('motivo', '').strip()

                cursor.execute("""
                    INSERT INTO solicitud_faov (trabajador_id, anio, motivo, estado, fecha_solicitud)
                    VALUES (%s, %s, %s, 'solicitada', NOW());
                """, (t_id, anio_sol, motivo or 'Trámite Habitacional / Crédito Hipotecario BANAVIH'))
                conexion.commit()
                flash('Solicitud de Certificación FAOV remitida a la Dirección de Recursos Humanos.', 'success')
                return redirect(url_for('portal.faov_estado_cuenta', anio=anio_sol))

            # Datos del trabajador
            cursor.execute("""
                SELECT t.*, c.nombre AS cargo_nombre, d.nombre AS departamento_nombre
                FROM trabajador t
                INNER JOIN cargo c ON t.cargo_id = c.cargo_id
                LEFT JOIN departamento d ON c.departamento_id = d.departamento_id
                WHERE t.trabajador_id = %s;
            """, (t_id,))
            trabajador = cursor.fetchone()

            # Desglose de nóminas aprobadas para el año
            sql_faov = """
                SELECT nd.monto AS retencion_trabajador,
                       pn.periodo_id, pn.descripcion, pn.fecha_inicio, pn.fecha_fin,
                       pn.tipo_nomina, YEAR(pn.fecha_fin) AS anio
                FROM nomina_detalle nd
                INNER JOIN nomina_trabajador nt ON nd.nomina_trabajador_id = nt.nomina_trabajador_id
                INNER JOIN periodo_nomina pn ON nt.periodo_id = pn.periodo_id
                WHERE nt.trabajador_id = %s 
                  AND nd.codigo_concepto = 'FAOV'
                  AND pn.estado IN ('aprobada', 'procesada_patria')
                  AND YEAR(pn.fecha_fin) = %s
                ORDER BY pn.fecha_fin DESC;
            """
            cursor.execute(sql_faov, (t_id, anio_seleccionado))
            registros_raw = cursor.fetchall()

            # Años disponibles
            cursor.execute("""
                SELECT DISTINCT YEAR(pn.fecha_fin) AS anio
                FROM nomina_detalle nd
                INNER JOIN nomina_trabajador nt ON nd.nomina_trabajador_id = nt.nomina_trabajador_id
                INNER JOIN periodo_nomina pn ON nt.periodo_id = pn.periodo_id
                WHERE nt.trabajador_id = %s AND nd.codigo_concepto = 'FAOV'
                  AND pn.estado IN ('aprobada', 'procesada_patria')
                ORDER BY anio DESC;
            """, (t_id,))
            anios_disponibles = [row['anio'] for row in cursor.fetchall()]
            if not anios_disponibles:
                anios_disponibles = [anio_actual]

            movimientos = []
            total_trabajador = Decimal('0.00')
            total_patronal = Decimal('0.00')
            gran_total_banavih = Decimal('0.00')

            for r in registros_raw:
                ret_trab = Decimal(str(r['retencion_trabajador']))
                aporte_pat = ret_trab * Decimal('2.00')
                aporte_tot = ret_trab * Decimal('3.00')

                total_trabajador += ret_trab
                total_patronal += aporte_pat
                gran_total_banavih += aporte_tot

                movimientos.append({
                    'periodo': r['descripcion'],
                    'fecha_inicio': r['fecha_inicio'],
                    'fecha_fin': r['fecha_fin'],
                    'tipo_nomina': r['tipo_nomina'],
                    'retencion_trabajador': ret_trab,
                    'aporte_patronal': aporte_pat,
                    'total_depositado': aporte_tot
                })

            # Historial de solicitudes de certificación de este trabajador
            cursor.execute("""
                SELECT * FROM solicitud_faov
                WHERE trabajador_id = %s
                ORDER BY solicitud_faov_id DESC;
            """, (t_id,))
            solicitudes = cursor.fetchall()

            return render_template(
                'portal/portal_faov.html',
                trabajador=trabajador,
                movimientos=movimientos,
                total_trabajador=total_trabajador,
                total_patronal=total_patronal,
                gran_total_banavih=gran_total_banavih,
                anios=anios_disponibles,
                anio_activo=str(anio_seleccionado),
                solicitudes=solicitudes
            )
    finally:
        conexion.close()

# -------------------------------------------------------------------------
# FAOV: Constancia Oficial de Retenciones para Bancos y BANAVIH
# -------------------------------------------------------------------------
@portal_bp.route('/faov/imprimir/<int:solicitud_id>')
def imprimir_constancia_faov(solicitud_id):
    if 'usuario_id' not in session:
        return redirect(url_for('auth.login'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            # Consultar solicitud
            cursor.execute("""
                SELECT sf.*, t.cedula, t.nombres, t.apellidos,
                       c.nombre AS cargo_nombre, d.nombre AS departamento_nombre,
                       u.nombre_usuario AS autorizador_nombre
                FROM solicitud_faov sf
                INNER JOIN trabajador t ON sf.trabajador_id = t.trabajador_id
                INNER JOIN cargo c ON t.cargo_id = c.cargo_id
                LEFT JOIN departamento d ON c.departamento_id = d.departamento_id
                LEFT JOIN usuario u ON sf.aprobada_por = u.usuario_id
                WHERE sf.solicitud_faov_id = %s;
            """, (solicitud_id,))
            solicitud = cursor.fetchone()

            if not solicitud or solicitud['estado'] != 'aprobada':
                flash('La certificación solicitada no ha sido aprobada por Recursos Humanos o no existe.', 'warning')
                return redirect(url_for('portal.faov_estado_cuenta'))

            # Validación de pertenencia para trabajadores
            t_id = obtener_trabajador_id_actual(cursor)
            if session.get('rol') == 'trabajador' and solicitud['trabajador_id'] != t_id:
                flash('No tiene autorización para visualizar este documento.', 'danger')
                return redirect(url_for('portal.faov_estado_cuenta'))

            # Consultar retenciones de ese año específico
            sql_faov = """
                SELECT nd.monto AS retencion_trabajador,
                       pn.periodo_id, pn.descripcion, pn.fecha_fin, pn.fecha_inicio
                FROM nomina_detalle nd
                INNER JOIN nomina_trabajador nt ON nd.nomina_trabajador_id = nt.nomina_trabajador_id
                INNER JOIN periodo_nomina pn ON nt.periodo_id = pn.periodo_id
                WHERE nt.trabajador_id = %s 
                  AND nd.codigo_concepto = 'FAOV'
                  AND pn.estado IN ('aprobada', 'procesada_patria')
                  AND YEAR(pn.fecha_fin) = %s
                ORDER BY pn.fecha_fin ASC;
            """
            cursor.execute(sql_faov, (solicitud['trabajador_id'], solicitud['anio']))
            detalles = cursor.fetchall()

            total_retenido = sum(Decimal(str(d['retencion_trabajador'])) for d in detalles)
            total_patrono = total_retenido * Decimal('2.00')
            total_general = total_retenido * Decimal('3.00')

            meses = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']
            fecha_ref = solicitud['fecha_aprobacion'] or datetime.date.today()
            fecha_texto = f"a los {fecha_ref.day} días del mes de {meses[fecha_ref.month - 1]} de {fecha_ref.year}"

            return render_template(
                'portal/portal_faov_imprimir.html',
                s=solicitud,
                t=solicitud,
                detalles=detalles,
                total_retenido=total_retenido,
                total_patrono=total_patrono,
                total_general=total_general,
                anio=solicitud['anio'],
                fecha_texto=fecha_texto
            )
    finally:
        conexion.close()
        
# -------------------------------------------------------------------------
# VACACIONES: Consulta de Saldo y Solicitud del Funcionario
# -------------------------------------------------------------------------
@portal_bp.route('/vacaciones', methods=['GET', 'POST'])
def vacaciones():
    if 'usuario_id' not in session or session.get('rol') != 'trabajador':
        return redirect(url_for('auth.login'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            t_id = obtener_trabajador_id_actual(cursor)
            cursor.execute("""
                SELECT t.*, c.nombre AS cargo_nombre, d.nombre AS departamento_nombre
                FROM trabajador t
                INNER JOIN cargo c ON t.cargo_id = c.cargo_id
                LEFT JOIN departamento d ON c.departamento_id = d.departamento_id
                WHERE t.trabajador_id = %s;
            """, (t_id,))
            trabajador = cursor.fetchone()

            # Cómputo legal de antigüedad (Art. 190 LOTTT)
            hoy = datetime.date.today()
            f_ingreso = trabajador['fecha_ingreso']
            if f_ingreso:
                anios_servicio = hoy.year - f_ingreso.year - ((hoy.month, hoy.day) < (f_ingreso.month, f_ingreso.day))
                anios_servicio = max(0, anios_servicio)
            else:
                anios_servicio = 0

            # 15 días base + 1 por año adicional (máximo 30 días hábiles)
            dias_derecho = min(15 + max(0, anios_servicio - 1), 30) if anios_servicio >= 1 else 0

            # Días disfrutados acumulados
            cursor.execute("""
                SELECT COALESCE(SUM(dias_habiles), 0) AS disfrutados
                FROM solicitud_vacaciones
                WHERE trabajador_id = %s AND estado IN ('aprobada', 'disfrutada');
            """, (t_id,))
            dias_disfrutados = int(cursor.fetchone()['disfrutados'])
            saldo_disponible = max(0, dias_derecho - dias_disfrutados)

            # Advertencia legal Art. 199 (Acumulación máxima de 2 períodos)
            alerta_acumulacion = anios_servicio >= 2 and saldo_disponible >= 30

            if request.method == 'POST':
                f_inicio = request.form.get('fecha_inicio')
                f_fin = request.form.get('fecha_fin')
                dias_solicitados = int(request.form.get('dias_habiles', 0))
                periodo_texto = f"{hoy.year - 1} - {hoy.year}"

                if dias_solicitados <= 0 or dias_solicitados > saldo_disponible:
                    flash(f'La cantidad de días solicitados ({dias_solicitados}) supera su saldo disponible ({saldo_disponible} días).', 'danger')
                    return redirect(url_for('portal.vacaciones'))

                cursor.execute("""
                    INSERT INTO solicitud_vacaciones (trabajador_id, periodo, fecha_inicio, fecha_fin, dias_habiles, estado, fecha_solicitud)
                    VALUES (%s, %s, %s, %s, %s, 'pendiente', NOW());
                """, (t_id, periodo_texto, f_inicio, f_fin, dias_solicitados))
                conexion.commit()
                flash('Solicitud de vacaciones registrada con éxito. Notifique a su supervisor para su visto bueno.', 'success')
                return redirect(url_for('portal.vacaciones'))

            cursor.execute("""
                SELECT * FROM solicitud_vacaciones
                WHERE trabajador_id = %s
                ORDER BY vacacion_id DESC;
            """, (t_id,))
            historial = cursor.fetchall()

            return render_template(
                'portal/portal_vacaciones.html',
                t=trabajador,
                anios_servicio=anios_servicio,
                dias_derecho=dias_derecho,
                dias_disfrutados=dias_disfrutados,
                saldo_disponible=saldo_disponible,
                alerta_acumulacion=alerta_acumulacion,
                historial=historial
            )
    finally:
        conexion.close()


# -------------------------------------------------------------------------
# VACACIONES: Boleta Oficial Imprimible
# -------------------------------------------------------------------------
@portal_bp.route('/vacaciones/<int:vacacion_id>/imprimir')
def imprimir_boleta_vacaciones(vacacion_id):
    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            sql = """
                SELECT sv.*, t.cedula, t.nombres, t.apellidos, t.fecha_ingreso,
                       c.nombre AS cargo_nombre, d.nombre AS departamento_nombre
                FROM solicitud_vacaciones sv
                INNER JOIN trabajador t ON sv.trabajador_id = t.trabajador_id
                INNER JOIN cargo c ON t.cargo_id = c.cargo_id
                LEFT JOIN departamento d ON c.departamento_id = d.departamento_id
                WHERE sv.vacacion_id = %s;
            """
            cursor.execute(sql, (vacacion_id,))
            v = cursor.fetchone()
            hoy = datetime.date.today()
            return render_template('portal/portal_vacaciones_boleta.html', v=v, hoy=hoy)
    finally:
        conexion.close()
        
# -------------------------------------------------------------------------
# IVSS: Estado de Cuenta Individual y Cotizaciones del Seguro Social
# -------------------------------------------------------------------------
@portal_bp.route('/ivss', methods=['GET', 'POST'])
def ivss_estado_cuenta():
    if 'usuario_id' not in session or session.get('rol') != 'trabajador':
        flash('Acceso restringido al portal del funcionario.', 'danger')
        return redirect(url_for('auth.login'))

    anio_actual = datetime.date.today().year
    anio_seleccionado = request.args.get('anio', default=str(anio_actual))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            t_id = obtener_trabajador_id_actual(cursor)
            if not t_id:
                flash('Cuenta no vinculada a una ficha de trabajador.', 'danger')
                return redirect(url_for('portal.inicio'))

            # Procesar solicitud de constancia de cotizaciones
            if request.method == 'POST':
                anio_sol = request.form.get('anio_solicitud', anio_actual)
                motivo = request.form.get('motivo', '').strip()

                cursor.execute("""
                    INSERT INTO solicitud_ivss (trabajador_id, anio, motivo, estado, fecha_solicitud)
                    VALUES (%s, %s, %s, 'solicitada', NOW());
                """, (t_id, anio_sol, motivo or 'Trámite de Cuenta Individual / Pensión IVSS'))
                conexion.commit()
                flash('Solicitud de Certificación IVSS remitida a la Dirección de Recursos Humanos.', 'success')
                return redirect(url_for('portal.ivss_estado_cuenta', anio=anio_sol))

            # Datos del trabajador
            cursor.execute("""
                SELECT t.*, c.nombre AS cargo_nombre, d.nombre AS departamento_nombre
                FROM trabajador t
                INNER JOIN cargo c ON t.cargo_id = c.cargo_id
                LEFT JOIN departamento d ON c.departamento_id = d.departamento_id
                WHERE t.trabajador_id = %s;
            """, (t_id,))
            trabajador = cursor.fetchone()

            # Desglose de retenciones IVSS en nóminas aprobadas del año seleccionado
            sql_ivss = """
                SELECT nd.monto AS retencion_trabajador,
                       pn.periodo_id, pn.descripcion, pn.fecha_inicio, pn.fecha_fin,
                       pn.tipo_nomina, nt.dias_trabajados, YEAR(pn.fecha_fin) AS anio
                FROM nomina_detalle nd
                INNER JOIN nomina_trabajador nt ON nd.nomina_trabajador_id = nt.nomina_trabajador_id
                INNER JOIN periodo_nomina pn ON nt.periodo_id = pn.periodo_id
                WHERE nt.trabajador_id = %s 
                  AND nd.codigo_concepto = 'IVSS'
                  AND pn.estado IN ('aprobada', 'procesada_patria')
                  AND YEAR(pn.fecha_fin) = %s
                ORDER BY pn.fecha_fin DESC;
            """
            cursor.execute(sql_ivss, (t_id, anio_seleccionado))
            registros_raw = cursor.fetchall()

            # Años disponibles con retenciones registradas
            cursor.execute("""
                SELECT DISTINCT YEAR(pn.fecha_fin) AS anio
                FROM nomina_detalle nd
                INNER JOIN nomina_trabajador nt ON nd.nomina_trabajador_id = nt.nomina_trabajador_id
                INNER JOIN periodo_nomina pn ON nt.periodo_id = pn.periodo_id
                WHERE nt.trabajador_id = %s AND nd.codigo_concepto = 'IVSS'
                  AND pn.estado IN ('aprobada', 'procesada_patria')
                ORDER BY anio DESC;
            """, (t_id,))
            anios_disponibles = [row['anio'] for row in cursor.fetchall()]
            if not anios_disponibles:
                anios_disponibles = [anio_actual]

            movimientos = []
            total_trabajador = Decimal('0.00')
            total_patronal = Decimal('0.00')
            gran_total_ivss = Decimal('0.00')
            total_semanas_cotizadas = 0

            for r in registros_raw:
                ret_trab = Decimal(str(r['retencion_trabajador']))
                # Riesgo Mínimo (9% patrono / 4% trabajador = factor 2.25)
                aporte_pat = (ret_trab * Decimal('2.25')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                aporte_tot = (ret_trab * Decimal('3.25')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                
                # Cada quincena liquidada representa 2 semanas cotizadas
                semanas = 2 if int(r.get('dias_trabajados') or 15) <= 15 else 4
                total_semanas_cotizadas += semanas

                total_trabajador += ret_trab
                total_patronal += aporte_pat
                gran_total_ivss += aporte_tot

                movimientos.append({
                    'periodo': r['descripcion'],
                    'fecha_inicio': r['fecha_inicio'],
                    'fecha_fin': r['fecha_fin'],
                    'tipo_nomina': r['tipo_nomina'],
                    'semanas': semanas,
                    'retencion_trabajador': ret_trab,
                    'aporte_patronal': aporte_pat,
                    'total_depositado': aporte_tot
                })

            # Historial de solicitudes de certificación de este funcionario
            cursor.execute("""
                SELECT * FROM solicitud_ivss
                WHERE trabajador_id = %s
                ORDER BY solicitud_ivss_id DESC;
            """, (t_id,))
            solicitudes = cursor.fetchall()

            return render_template(
                'portal/portal_ivss.html',
                trabajador=trabajador,
                movimientos=movimientos,
                total_trabajador=total_trabajador,
                total_patronal=total_patronal,
                gran_total_ivss=gran_total_ivss,
                total_semanas=total_semanas_cotizadas,
                anios=anios_disponibles,
                anio_activo=str(anio_seleccionado),
                solicitudes=solicitudes
            )
    finally:
        conexion.close()


# -------------------------------------------------------------------------
# IVSS: Constancia Oficial de Retenciones y Cuenta Individual
# -------------------------------------------------------------------------
@portal_bp.route('/ivss/imprimir/<int:solicitud_id>')
def imprimir_constancia_ivss(solicitud_id):
    if 'usuario_id' not in session:
        return redirect(url_for('auth.login'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            cursor.execute("""
                SELECT si.*, t.cedula, t.nombres, t.apellidos, t.fecha_ingreso,
                       c.nombre AS cargo_nombre, d.nombre AS departamento_nombre,
                       u.nombre_usuario AS autorizador_nombre
                FROM solicitud_ivss si
                INNER JOIN trabajador t ON si.trabajador_id = t.trabajador_id
                INNER JOIN cargo c ON t.cargo_id = c.cargo_id
                LEFT JOIN departamento d ON c.departamento_id = d.departamento_id
                LEFT JOIN usuario u ON si.aprobada_por = u.usuario_id
                WHERE si.solicitud_ivss_id = %s;
            """, (solicitud_id,))
            solicitud = cursor.fetchone()

            if not solicitud or solicitud['estado'] != 'aprobada':
                flash('La certificación solicitada aún no ha sido aprobada por Recursos Humanos.', 'warning')
                return redirect(url_for('portal.ivss_estado_cuenta'))

            t_id = obtener_trabajador_id_actual(cursor)
            if session.get('rol') == 'trabajador' and solicitud['trabajador_id'] != t_id:
                flash('No tiene autorización para visualizar este documento.', 'danger')
                return redirect(url_for('portal.ivss_estado_cuenta'))

            sql_ivss = """
                SELECT nd.monto AS retencion_trabajador,
                       pn.periodo_id, pn.descripcion, pn.fecha_fin, pn.fecha_inicio,
                       nt.dias_trabajados
                FROM nomina_detalle nd
                INNER JOIN nomina_trabajador nt ON nd.nomina_trabajador_id = nt.nomina_trabajador_id
                INNER JOIN periodo_nomina pn ON nt.periodo_id = pn.periodo_id
                WHERE nt.trabajador_id = %s 
                  AND nd.codigo_concepto = 'IVSS'
                  AND pn.estado IN ('aprobada', 'procesada_patria')
                  AND YEAR(pn.fecha_fin) = %s
                ORDER BY pn.fecha_fin ASC;
            """
            cursor.execute(sql_ivss, (solicitud['trabajador_id'], solicitud['anio']))
            detalles_raw = cursor.fetchall()

            detalles = []
            total_retenido = Decimal('0.00')
            total_patrono = Decimal('0.00')
            total_general = Decimal('0.00')
            semanas_acumuladas = 0

            for d in detalles_raw:
                ret = Decimal(str(d['retencion_trabajador']))
                pat = (ret * Decimal('2.25')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                tot = (ret * Decimal('3.25')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                semanas = 2 if int(d.get('dias_trabajados') or 15) <= 15 else 4
                semanas_acumuladas += semanas

                total_retenido += ret
                total_patrono += pat
                total_general += tot

                detalles.append({
                    'descripcion': d['descripcion'],
                    'fecha_inicio': d['fecha_inicio'],
                    'fecha_fin': d['fecha_fin'],
                    'semanas': semanas,
                    'retencion_trabajador': ret,
                    'aporte_patronal': pat,
                    'total_depositado': tot
                })

            meses = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']
            fecha_ref = solicitud['fecha_aprobacion'] or datetime.date.today()
            fecha_texto = f"a los {fecha_ref.day} días del mes de {meses[fecha_ref.month - 1]} de {fecha_ref.year}"

            return render_template(
                'portal/portal_ivss_imprimir.html',
                s=solicitud,
                t=solicitud,
                detalles=detalles,
                total_retenido=total_retenido,
                total_patrono=total_patrono,
                total_general=total_general,
                total_semanas=semanas_acumuladas,
                anio=solicitud['anio'],
                fecha_texto=fecha_texto
            )
    finally:
        conexion.close()
        
# -------------------------------------------------------------------------
# JUBILACIONES: Solicitud y Consulta del Funcionario
# -------------------------------------------------------------------------
@portal_bp.route('/jubilacion', methods=['GET', 'POST'])
def jubilacion():
    if 'usuario_id' not in session or session.get('rol') != 'trabajador':
        return redirect(url_for('auth.login'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            t_id = obtener_trabajador_id_actual(cursor)
            cursor.execute("""
                SELECT t.*, c.nombre AS cargo_nombre, d.nombre AS departamento_nombre
                FROM trabajador t
                INNER JOIN cargo c ON t.cargo_id = c.cargo_id
                LEFT JOIN departamento d ON c.departamento_id = d.departamento_id
                WHERE t.trabajador_id = %s;
            """, (t_id,))
            trabajador = cursor.fetchone()

            hoy = datetime.date.today()
            f_ing = trabajador['fecha_ingreso']
            f_nac = trabajador['fecha_nacimiento']

            anos_servicio = hoy.year - f_ing.year - ((hoy.month, hoy.day) < (f_ing.month, f_ing.day)) if f_ing else 0
            edad = hoy.year - f_nac.year - ((hoy.month, hoy.day) < (f_nac.month, f_nac.day)) if f_nac else 0

            cumple_edad = (trabajador['sexo'] == 'M' and edad >= 60) or (trabajador['sexo'] == 'F' and edad >= 55)
            cumple_requisitos = anos_servicio >= 28 or (cumple_edad and anos_servicio >= 25)

            if request.method == 'POST':
                motivo = request.form.get('motivo', 'Solicitud formal de jubilación reglamentaria').strip()
                cursor.execute("""
                    INSERT INTO solicitud_jubilacion (
                        trabajador_id, tipo_tramite, motivo, anos_servicio, edad_trabajador,
                        fecha_solicitud, estado
                    ) VALUES (%s, 'solicitud_voluntaria', %s, %s, %s, NOW(), 'solicitada');
                """, (t_id, motivo, anos_servicio, edad))
                conexion.commit()
                flash('Solicitud de jubilación enviada a la Dirección de Recursos Humanos.', 'success')
                return redirect(url_for('portal.jubilacion'))

            cursor.execute("SELECT * FROM solicitud_jubilacion WHERE trabajador_id = %s ORDER BY jubilacion_id DESC;", (t_id,))
            solicitudes = cursor.fetchall()

            return render_template(
                'portal/portal_jubilacion.html',
                t=trabajador,
                anos_servicio=anos_servicio,
                edad=edad,
                cumple=cumple_requisitos,
                solicitudes=solicitudes
            )
    finally:
        conexion.close()


# -------------------------------------------------------------------------
# RESOLUCIÓN OFICIAL DE JUBILACIÓN (Documento Legal Imprimible)
# -------------------------------------------------------------------------
@portal_bp.route('/jubilacion/imprimir/<int:jubilacion_id>')
def imprimir_resolucion_jubilacion(jubilacion_id):
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
                WHERE sj.jubilacion_id = %s;
            """
            cursor.execute(sql, (jubilacion_id,))
            j = cursor.fetchone()

            if not j or j['estado'] != 'aprobada':
                flash('La resolución solicitada no existe o no ha sido aprobada.', 'warning')
                return redirect(url_for('auth.dashboard'))

            meses = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']
            fecha_ref = j['fecha_resolucion'] or datetime.date.today()
            fecha_texto = f"a los {fecha_ref.day} días del mes de {meses[fecha_ref.month - 1]} de {fecha_ref.year}"

            return render_template('portal/portal_jubilacion_imprimir.html', j=j, fecha_texto=fecha_texto)
    finally:
        conexion.close()