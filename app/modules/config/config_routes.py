from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from decimal import Decimal
import datetime
import json
from app.database import get_db_connection

config_bp = Blueprint('config', __name__)

# -------------------------------------------------------------------------
# 1. TABLA GENERAL DE CONCEPTOS (Activos e Inactivos)
# Rol exclusivo: tecnico_informatica
# -------------------------------------------------------------------------
@config_bp.route('/conceptos')
def conceptos():
    if 'usuario_id' not in session or session.get('rol') != 'tecnico_informatica':
        flash('Acceso denegado: Solo el Técnico de Informática tiene autorización para parametrizar conceptos.', 'danger')
        return redirect(url_for('auth.dashboard'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            # Se consultan todos los conceptos sin filtro de activo
            sql = """
                SELECT concepto_id, codigo, nombre, tipo, metodo, valor, 
                       base_calculo, obligatorio, fundamento, activo
                FROM concepto
                ORDER BY tipo ASC, codigo ASC;
            """
            cursor.execute(sql)
            conceptos_lista = cursor.fetchall()
            return render_template('config_conceptos.html', conceptos=conceptos_lista)
    finally:
        conexion.close()

# -------------------------------------------------------------------------
# 2. ACTUALIZAR EXCLUSIVAMENTE 'VALOR' Y 'ACTIVO'
# Rol exclusivo: tecnico_informatica (Registra auditoría en bitácora)
# -------------------------------------------------------------------------
@config_bp.route('/conceptos/<int:id>/actualizar', methods=['POST'])
def actualizar_concepto(id):
    if 'usuario_id' not in session or session.get('rol') != 'tecnico_informatica':
        flash('Acceso denegado: Acción reservada exclusivamente para Informática.', 'danger')
        return redirect(url_for('auth.dashboard'))

    # Se extraen y validan únicamente 'valor' y 'activo'
    valor_raw = request.form.get('valor', '').strip()
    activo_raw = request.form.get('activo')
    activo = True if activo_raw in ['1', 'true', 'on', True] else False

    try:
        valor_decimal = Decimal(valor_raw)
    except Exception:
        flash('El valor suministrado no es un formato decimal numérico válido.', 'danger')
        return redirect(url_for('config.conceptos'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            # 1. Obtener estado previo inalterable para la bitácora
            cursor.execute("SELECT * FROM concepto WHERE concepto_id = %s;", (id,))
            valor_previo = cursor.fetchone()

            if not valor_previo:
                flash('El concepto a modificar no existe en la base de datos.', 'warning')
                return redirect(url_for('config.conceptos'))

            # 2. Actualización restringida: no modifica codigo, tipo ni metodo
            sql_update = """
                UPDATE concepto 
                SET valor = %s, activo = %s 
                WHERE concepto_id = %s;
            """
            cursor.execute(sql_update, (valor_decimal, activo, id))

            # 3. Obtener estado posterior a la modificación
            cursor.execute("SELECT * FROM concepto WHERE concepto_id = %s;", (id,))
            valor_nuevo = cursor.fetchone()

            # 4. Inserción obligatoria de auditoría en la tabla bitácora
            sql_bitacora = """
                INSERT INTO bitacora (usuario_id, tabla, registro_id, accion, valor_previo, valor_nuevo, fecha_hora, ip)
                VALUES (%s, 'concepto', %s, 'modificar', %s, %s, %s, %s);
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
            flash(f"Concepto '{valor_previo['codigo']}' actualizado y registrado en bitácora.", 'success')

    except Exception as e:
        conexion.rollback()
        flash(f'Error al procesar la actualización: {e}', 'danger')
    finally:
        conexion.close()

    return redirect(url_for('config.conceptos'))