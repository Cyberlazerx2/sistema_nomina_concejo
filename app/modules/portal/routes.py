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

            return render_template('portal_recibos.html', trabajador=trabajador, recibos=recibos_lista)
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

            return render_template('portal_recibo_detalle.html', 
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

            # Inspección dinámica de columnas para compatibilidad de esquema
            cursor.execute("DESCRIBE solicitud_cambio_perfil;")
            columnas_existentes = [col['Field'] for col in cursor.fetchall()]

            if request.method == 'POST':
                telefono_nuevo = request.form.get('telefono', '').strip()
                correo_nuevo = request.form.get('correo', '').strip()
                direccion_nueva = request.form.get('direccion', '').strip()
                motivo = request.form.get('motivo', '').strip()

                if not motivo:
                    flash('Debe indicar el motivo de la actualización de sus datos.', 'warning')
                else:
                    ahora = datetime.datetime.now()
                    # Soporte flexible según el DDL de la tabla
                    if 'telefono_nuevo' in columnas_existentes:
                        sql_sol = """
                            INSERT INTO solicitud_cambio_perfil 
                            (trabajador_id, telefono_nuevo, correo_nuevo, direccion_nueva, motivo, estado, fecha_solicitud)
                            VALUES (%s, %s, %s, %s, %s, 'pendiente', %s);
                        """
                        cursor.execute(sql_sol, (trabajador['trabajador_id'], telefono_nuevo, correo_nuevo, direccion_nueva, motivo, ahora))
                    else:
                        # Si la estructura usa pares campo / valor_nuevo
                        sql_sol = """
                            INSERT INTO solicitud_cambio_perfil 
                            (trabajador_id, campo_modificar, valor_nuevo, motivo, estado, fecha_solicitud)
                            VALUES (%s, %s, %s, %s, 'pendiente', %s);
                        """
                        cambios = [
                            ('telefono', telefono_nuevo),
                            ('correo', correo_nuevo),
                            ('direccion', direccion_nueva)
                        ]
                        for campo, val in cambios:
                            if val:
                                cursor.execute(sql_sol, (trabajador['trabajador_id'], campo, val, motivo, ahora))

                    conexion.commit()
                    flash('Solicitud de actualización enviada a la Dirección de Recursos Humanos.', 'success')
                    return redirect(url_for('portal.perfil'))

            # Consultar solicitudes previas del trabajador
            cursor.execute("""
                SELECT * FROM solicitud_cambio_perfil 
                WHERE trabajador_id = %s 
                ORDER BY solicitud_id DESC;
            """, (trabajador['trabajador_id'],))
            solicitudes = cursor.fetchall()

            return render_template('portal_perfil.html', trabajador=trabajador, solicitudes=solicitudes)
    finally:
        conexion.close()