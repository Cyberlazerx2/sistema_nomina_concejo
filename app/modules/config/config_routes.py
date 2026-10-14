from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from decimal import Decimal
import datetime
import json
from app.database import get_db_connection

config_bp = Blueprint('config', __name__)

# -------------------------------------------------------------------------
# 1. TABLA GENERAL DE CONCEPTOS (Activos e Inactivos)
# Rol exclusivo: directora_rrhh
# -------------------------------------------------------------------------
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from app.database import get_db_connection

config_bp = Blueprint('config', __name__)

def formatear_numero_limpio(val):
    """
    Elimina los ceros innecesarios a la derecha de un número decimal:
    4.0000 -> '4' | 0.5000 -> '0.5' | 47.0500 -> '47.05' | 0.0025 -> '0.0025'
    """
    if val is None:
        return "0"
    try:
        f = float(val)
        formateado = f"{f:.6f}".rstrip('0').rstrip('.')
        return formateado if formateado != "" else "0"
    except Exception:
        return str(val)


@config_bp.route('/conceptos', methods=['GET', 'POST'])
def conceptos():
    roles_permitidos = ['directora_rrhh', 'tecnico_informatica']
    if 'usuario_id' not in session or session.get('rol') not in roles_permitidos:
        flash('Acceso denegado a la configuración salarial.', 'danger')
        return redirect(url_for('auth.dashboard'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            cursor.execute("DESCRIBE concepto;")
            columnas_reales = [col['Field'] for col in cursor.fetchall()]

            col_nombre = 'nombre' if 'nombre' in columnas_reales else ('descripcion' if 'descripcion' in columnas_reales else None)
            col_calc = 'tipo_calculo' if 'tipo_calculo' in columnas_reales else ('formula' if 'formula' in columnas_reales else None)
            col_valor = 'valor' if 'valor' in columnas_reales else ('monto' if 'monto' in columnas_reales else None)
            col_activo = 'activo' if 'activo' in columnas_reales else None

            # -----------------------------------------------------------------
            # Guardado masivo
            # -----------------------------------------------------------------
            if request.method == 'POST':
                conceptos_ids = request.form.getlist('concepto_id[]')
                nombres = request.form.getlist('nombre[]')
                tipos_calculo = request.form.getlist('tipo_calculo[]')
                valores = request.form.getlist('valor[]')
                activos_enviados = set(request.form.getlist('activo[]'))

                set_clauses = []
                if col_nombre: set_clauses.append(f"{col_nombre} = %s")
                if col_calc: set_clauses.append(f"{col_calc} = %s")
                if col_valor: set_clauses.append(f"{col_valor} = %s")
                if col_activo: set_clauses.append(f"{col_activo} = %s")

                if set_clauses:
                    sql_update = f"UPDATE concepto SET {', '.join(set_clauses)} WHERE concepto_id = %s;"

                    for i, c_id in enumerate(conceptos_ids):
                        val_str = valores[i].replace(',', '.').strip() if i < len(valores) else '0'
                        try:
                            valor_num = float(val_str) if val_str else 0.0
                        except ValueError:
                            valor_num = 0.0

                        esta_activo = 1 if c_id in activos_enviados else 0

                        params = []
                        if col_nombre: params.append(nombres[i].strip() if i < len(nombres) else '')
                        if col_calc: params.append(tipos_calculo[i].strip() if i < len(tipos_calculo) else 'porcentaje')
                        if col_valor: params.append(valor_num)
                        if col_activo: params.append(esta_activo)
                        params.append(c_id)

                        cursor.execute(sql_update, tuple(params))

                    conexion.commit()
                    flash('Parametrización salarial actualizada exitosamente en bloque.', 'success')
                else:
                    flash('No se encontraron columnas modificables en la tabla.', 'warning')

                return redirect(url_for('config.conceptos'))

            # -----------------------------------------------------------------
            # Carga y formateo de datos para la vista
            # -----------------------------------------------------------------
            cursor.execute("SELECT * FROM concepto ORDER BY tipo ASC, concepto_id ASC;")
            todos = cursor.fetchall()

            for c in todos:
                c['nombre_display'] = c.get('nombre') or c.get('descripcion') or 'Concepto General'
                c['codigo_display'] = c.get('codigo') or c.get('codigo_concepto') or f"CON-{c.get('concepto_id')}"
                c['tipo_calculo_display'] = c.get('tipo_calculo') or c.get('formula') or 'porcentaje'

                val_raw = c.get('valor') if c.get('valor') is not None else (c.get('monto') or 0.0)
                c['valor_limpio'] = formatear_numero_limpio(val_raw)
                c['activo_display'] = bool(c.get('activo', 1))

                # Etiqueta para la columna "Vigente Actual"
                if c['tipo_calculo_display'] == 'porcentaje':
                    c['etiqueta_actual'] = f"{c['valor_limpio']}%"
                elif c['tipo_calculo_display'] == 'dias':
                    c['etiqueta_actual'] = f"{c['valor_limpio']} d"
                else:
                    c['etiqueta_actual'] = f"Bs. {c['valor_limpio']}"

            asignaciones = [c for c in todos if str(c.get('tipo', '')).strip().lower() in ['asignacion', 'asignación']]
            deducciones = [c for c in todos if str(c.get('tipo', '')).strip().lower() in ['deduccion', 'deducción']]

            return render_template(
                'config/config_conceptos.html',
                asignaciones=asignaciones,
                deducciones=deducciones
            )
    except Exception as e:
        conexion.rollback()
        flash(f'Error al procesar conceptos: {e}', 'danger')
        return redirect(url_for('auth.dashboard'))
    finally:
        conexion.close()

# -------------------------------------------------------------------------
# 2. ACTUALIZAR EXCLUSIVAMENTE 'VALOR' Y 'ACTIVO'
# Rol exclusivo: directora_rrhh (Registra auditoría en bitácora)
# -------------------------------------------------------------------------
@config_bp.route('/conceptos/<int:id>/actualizar', methods=['POST'])
def actualizar_concepto(id):
    if 'usuario_id' not in session or session.get('rol') != 'directora_rrhh':
        flash('Acceso denegado: Solo la Directora de Recursos Humanos tiene autorización para parametrizar conceptos.', 'danger')
        return redirect(url_for('auth.dashboard'))

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
            cursor.execute("SELECT * FROM concepto WHERE concepto_id = %s;", (id,))
            valor_previo = cursor.fetchone()

            if not valor_previo:
                flash('El concepto a modificar no existe en la base de datos.', 'warning')
                return redirect(url_for('config.conceptos'))

            sql_update = """
                UPDATE concepto 
                SET valor = %s, activo = %s 
                WHERE concepto_id = %s;
            """
            cursor.execute(sql_update, (valor_decimal, activo, id))

            cursor.execute("SELECT * FROM concepto WHERE concepto_id = %s;", (id,))
            valor_nuevo = cursor.fetchone()

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