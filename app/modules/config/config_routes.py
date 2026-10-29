import datetime
from decimal import Decimal
import json
from app.database import get_db_connection
from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

config_bp = Blueprint('config', __name__)


def formatear_numero_limpio(val):
  if val is None:
    return '0'
  try:
    f = float(val)
    formateado = f'{f:.6f}'.rstrip('0').rstrip('.')
    return formateado if formateado != '' else '0'
  except Exception:
    return str(val)


# -------------------------------------------------------------------------
# 1. TABLA GENERAL DE CONCEPTOS (Cálculo y Guardado en Bloque)
# -------------------------------------------------------------------------
@config_bp.route('/conceptos', methods=['GET', 'POST'])
def conceptos():
  roles_permitidos = ['directora_rrhh', 'tecnico_informatica']
  if 'usuario_id' not in session or session.get('rol') not in roles_permitidos:
    flash('Acceso denegado a la configuración salarial.', 'danger')
    return redirect(url_for('auth.dashboard'))

  conexion = get_db_connection()
  try:
    with conexion.cursor() as cursor:
      cursor.execute('DESCRIBE concepto;')
      columnas_reales = [col['Field'] for col in cursor.fetchall()]

      col_nombre = 'nombre' if 'nombre' in columnas_reales else None
      col_calc = (
          'metodo'
          if 'metodo' in columnas_reales
          else ('tipo_calculo' if 'tipo_calculo' in columnas_reales else None)
      )
      col_valor = 'valor' if 'valor' in columnas_reales else None
      col_activo = 'activo' if 'activo' in columnas_reales else None

      if request.method == 'POST':
        conceptos_ids = request.form.getlist('concepto_id[]')
        nombres = request.form.getlist('nombre[]')
        tipos_calculo = request.form.getlist('tipo_calculo[]')
        valores = request.form.getlist('valor[]')
        activos_enviados = set(request.form.getlist('activo[]'))

        set_clauses = []
        if col_nombre:
          set_clauses.append(f'{col_nombre} = %s')
        if col_calc:
          set_clauses.append(f'{col_calc} = %s')
        if col_valor:
          set_clauses.append(f'{col_valor} = %s')
        if col_activo:
          set_clauses.append(f'{col_activo} = %s')

        if set_clauses:
          sql_update = f"UPDATE concepto SET {', '.join(set_clauses)} WHERE concepto_id = %s;"

          for i, c_id in enumerate(conceptos_ids):
            val_str = (
                valores[i].replace(',', '.').strip()
                if i < len(valores)
                else '0'
            )
            try:
              valor_num = float(val_str) if val_str else 0.0
            except ValueError:
              valor_num = 0.0

            esta_activo = 1 if c_id in activos_enviados else 0

            params = []
            if col_nombre:
              params.append(nombres[i].strip() if i < len(nombres) else '')
            if col_calc:
              params.append(
                  tipos_calculo[i].strip()
                  if i < len(tipos_calculo)
                  else 'porcentaje'
              )
            if col_valor:
              params.append(valor_num)
            if col_activo:
              params.append(esta_activo)
            params.append(c_id)

            cursor.execute(sql_update, tuple(params))

          conexion.commit()
          flash(
              'Parametrización salarial actualizada exitosamente en bloque.',
              'success',
          )

        return redirect(url_for('config.conceptos'))

      cursor.execute('SELECT * FROM concepto ORDER BY tipo ASC, concepto_id ASC;')
      todos = cursor.fetchall()

      for c in todos:
        c['nombre_display'] = c.get('nombre') or 'Concepto General'
        c['codigo_display'] = c.get('codigo') or f"CON-{c.get('concepto_id')}"
        c['tipo_calculo_display'] = (
            c.get('metodo') or c.get('tipo_calculo') or 'porcentaje'
        )

        val_raw = c.get('valor', 0.0)
        c['valor_limpio'] = formatear_numero_limpio(val_raw)
        c['activo_display'] = bool(c.get('activo', 1))

        if c['tipo_calculo_display'] == 'porcentaje':
          c['etiqueta_actual'] = f"{c['valor_limpio']}%"
        else:
          c['etiqueta_actual'] = f"Bs. {c['valor_limpio']}"

      asignaciones = [
          c
          for c in todos
          if str(c.get('tipo', '')).strip().lower() == 'asignacion'
      ]
      deducciones = [
          c
          for c in todos
          if str(c.get('tipo', '')).strip().lower() == 'deduccion'
      ]

      return render_template(
          'config/config_conceptos.html',
          asignaciones=asignaciones,
          deducciones=deducciones,
      )
  except Exception as e:
    conexion.rollback()
    flash(f'Error al procesar conceptos: {e}', 'danger')
    return redirect(url_for('auth.dashboard'))
  finally:
    conexion.close()


# -------------------------------------------------------------------------
# 2. REGISTRAR NUEVO CONCEPTO O RETENCIÓN
# -------------------------------------------------------------------------
@config_bp.route('/conceptos/nuevo', methods=['POST'])
def crear_concepto():
  roles_permitidos = ['directora_rrhh', 'tecnico_informatica']
  if 'usuario_id' not in session or session.get('rol') not in roles_permitidos:
    flash('Acceso denegado.', 'danger')
    return redirect(url_for('config.conceptos'))

  codigo = request.form.get('codigo', '').strip().upper().replace(' ', '_')
  nombre = request.form.get('nombre', '').strip()
  tipo = request.form.get('tipo', 'asignacion')
  metodo = request.form.get('metodo', 'fijo')
  valor_raw = request.form.get('valor', '0').replace(',', '.')
  obligatorio = 1 if request.form.get('obligatorio') == '1' else 0

  try:
    valor = Decimal(valor_raw)
  except Exception:
    valor = Decimal('0.00')

  conexion = get_db_connection()
  try:
    with conexion.cursor() as cursor:
      cursor.execute(
          'SELECT concepto_id FROM concepto WHERE codigo = %s;', (codigo,)
      )
      if cursor.fetchone():
        flash(
            f"El código de concepto '{codigo}' ya se encuentra registrado.",
            'warning',
        )
        return redirect(url_for('config.conceptos'))

      sql_insert = """
                INSERT INTO concepto (codigo, nombre, tipo, metodo, valor, base_calculo, obligatorio, activo)
                VALUES (%s, %s, %s, %s, %s, 'sueldo_base', %s, true);
            """
      cursor.execute(
          sql_insert, (codigo, nombre, tipo, metodo, valor, obligatorio)
      )
      conexion.commit()
      flash(f"Concepto '{nombre}' creado e incorporado con éxito.", 'success')
  except Exception as e:
    conexion.rollback()
    flash(f'Error al registrar concepto: {e}', 'danger')
  finally:
    conexion.close()

  return redirect(url_for('config.conceptos'))


# -------------------------------------------------------------------------
# 3. MODIFICAR PARÁMETROS COMPLETOS DEL CONCEPTO
# -------------------------------------------------------------------------
@config_bp.route('/conceptos/<int:id>/editar', methods=['POST'])
def editar_concepto(id):
  roles_permitidos = ['directora_rrhh', 'tecnico_informatica']
  if 'usuario_id' not in session or session.get('rol') not in roles_permitidos:
    flash('Acceso denegado.', 'danger')
    return redirect(url_for('config.conceptos'))

  nombre = request.form.get('nombre', '').strip()
  metodo = request.form.get('metodo', 'porcentaje')
  valor_raw = request.form.get('valor', '0').replace(',', '.').strip()
  base_calculo = request.form.get('base_calculo', 'sueldo_base')
  fundamento = request.form.get('fundamento', '').strip()
  obligatorio = 1 if request.form.get('obligatorio') == '1' else 0
  activo = 1 if request.form.get('activo') == '1' else 0

  try:
    valor = Decimal(valor_raw)
  except Exception:
    valor = Decimal('0.0000')

  conexion = get_db_connection()
  try:
    with conexion.cursor() as cursor:
      cursor.execute('SELECT * FROM concepto WHERE concepto_id = %s;', (id,))
      previo = cursor.fetchone()

      if not previo:
        flash('El concepto a editar no existe.', 'warning')
        return redirect(url_for('config.conceptos'))

      cursor.execute(
          """
                UPDATE concepto 
                SET nombre = %s, metodo = %s, valor = %s,
                    base_calculo = %s, fundamento = %s, obligatorio = %s, activo = %s
                WHERE concepto_id = %s;
            """,
          (
              nombre,
              metodo,
              valor,
              base_calculo,
              fundamento,
              obligatorio,
              activo,
              id,
          ),
      )

      conexion.commit()
      flash(f"Concepto '{previo['codigo']}' actualizado con éxito.", 'success')
  except Exception as e:
    conexion.rollback()
    flash(f'Error al modificar concepto: {e}', 'danger')
  finally:
    conexion.close()

  return redirect(url_for('config.conceptos'))


# -------------------------------------------------------------------------
# 4. ELIMINAR O DESACTIVAR CONCEPTO SALARIAL
# -------------------------------------------------------------------------
@config_bp.route('/conceptos/<int:id>/eliminar', methods=['POST'])
def eliminar_concepto(id):
  roles_permitidos = ['directora_rrhh', 'tecnico_informatica']
  if 'usuario_id' not in session or session.get('rol') not in roles_permitidos:
    flash('Acceso no autorizado.', 'danger')
    return redirect(url_for('config.conceptos'))

  conexion = get_db_connection()
  try:
    with conexion.cursor() as cursor:
      cursor.execute('SELECT * FROM concepto WHERE concepto_id = %s;', (id,))
      c = cursor.fetchone()

      if not c:
        flash('El concepto no existe.', 'warning')
        return redirect(url_for('config.conceptos'))

      # Proteger conceptos estructurales de la LOTTT
      if c['codigo'] in [
          'SUELDO',
          'CESTATICKET',
          'IVSS',
          'FAOV',
          'RPE',
          'FONDO_JUB',
          'BONO_EXTRA',
      ]:
        flash(
            f"El concepto '{c['codigo']}' es estructural por ley y no puede"
            ' eliminarse.',
            'danger',
        )
        return redirect(url_for('config.conceptos'))

      cursor.execute(
          'SELECT COUNT(*) AS total FROM nomina_detalle WHERE concepto_id = %s;',
          (id,),
      )
      total_usado = cursor.fetchone()['total']

      if total_usado > 0:
        cursor.execute(
            'UPDATE concepto SET activo = false WHERE concepto_id = %s;', (id,)
        )
        conexion.commit()
        flash(
            f"El concepto '{c['nombre']}' ya fue utilizado en {total_usado}"
            ' recibo(s) histórico(s). Por auditoría legal se ha DESACTIVADO.',
            'warning',
        )
      else:
        cursor.execute(
            'DELETE FROM concepto_trabajador WHERE concepto_id = %s;', (id,)
        )
        cursor.execute('DELETE FROM concepto WHERE concepto_id = %s;', (id,))
        conexion.commit()
        flash(
            f"Concepto '{c['nombre']}' ({c['codigo']}) eliminado"
            ' definitivamente de la base de datos.',
            'success',
        )
  except Exception as e:
    conexion.rollback()
    flash(f'Error al eliminar concepto: {e}', 'danger')
  finally:
    conexion.close()

  return redirect(url_for('config.conceptos'))