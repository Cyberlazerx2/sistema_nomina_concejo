from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
import datetime
import unicodedata
from app.database import get_db_connection

chatbot_bp = Blueprint('chatbot', __name__)

def normalizar_texto(texto):
    """Convierte el texto a minusculas y elimina acentos y caracteres diacriticos."""
    if not texto:
        return ""
    texto = unicodedata.normalize('NFKD', texto).encode('ASCII', 'ignore').decode('utf-8')
    return texto.lower().strip()

def clasificar_consulta(pregunta_original):
    """
    Motor de clasificacion por palabras clave en Python puro.
    No utiliza modelos externos ni machine learning.
    """
    t = normalizar_texto(pregunta_original)

    # 1. Recibos / Pago / Sueldo
    if any(k in t for k in ['recibo', 'pago', 'sueldo', 'cobro', 'quincena']):
        intencion = 'recibo_pago'
        respuesta = (
            "Puedes consultar y descargar tus recibos de pago oficiales (según el Art. 106 de la LOTTT) "
            "directamente en el portal: <a href='/portal/recibos' style='font-weight: bold; color: #0056b3;'>Ir a Mis Recibos de Pago</a>."
        )
    # 2. Vacaciones
    elif any(k in t for k in ['vacacion', 'vacaciones']):
        intencion = 'vacaciones'
        respuesta = (
            "De acuerdo con el Art. 190 de la LOTTT, al cumplir un (1) año ininterrumpido de servicio "
            "tienes derecho a 15 días hábiles de vacaciones remuneradas, más 1 día adicional remunerado por cada año de antigüedad sucesivo "
            "(hasta un máximo de 15 días adicionales). Para planificar tu período, debes coordinar con la Dirección de RRHH."
        )
    # 3. Reposo / Incapacidad médica
    elif any(k in t for k in ['reposo', 'incapacidad', 'medico', 'enfermedad']):
        intencion = 'reposo_medico'
        respuesta = (
            "Para justificar una inasistencia por reposo médico o incapacidad temporal, debes consignar ante la Dirección de Recursos Humanos "
            "la constancia validada por el IVSS o centro de salud público en un lapso no mayor a 48 horas hábiles para su debido registro administrativo."
        )
    # 4. Cambiar / Actualizar datos de contacto
    elif any(k in t for k in ['cambiar', 'actualizar', 'datos', 'perfil', 'telefono', 'correo', 'direccion']):
        intencion = 'actualizar_datos'
        respuesta = (
            "Para actualizar tu número telefónico, correo electrónico o dirección de habitación, puedes emitir una solicitud formal "
            "que será revisada por RRHH desde la sección: <a href='/portal/perfil' style='font-weight: bold; color: #0056b3;'>Mi Perfil y Contacto</a>."
        )
    # 5. Sin coincidencia -> Remitir a RRHH
    else:
        intencion = 'contacto_rrhh'
        respuesta = (
            "No reconozco esa consulta en mis respuestas automáticas. Para trámites específicos, cartas de trabajo "
            "o situaciones salariales particulares, por favor acude a la Dirección de Recursos Humanos del Concejo Municipal."
        )

    return intencion, respuesta

# -------------------------------------------------------------------------
# GET /chatbot: Interfaz de chat
# -------------------------------------------------------------------------
@chatbot_bp.route('/')
def index():
    if 'usuario_id' not in session or session.get('rol') != 'trabajador':
        flash('Acceso denegado: El asistente virtual es exclusivo para trabajadores.', 'danger')
        return redirect(url_for('auth.dashboard'))

    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            # Obtener datos laborales básicos del trabajador
            cursor.execute("""
                SELECT t.nombres, t.apellidos, c.nombre AS cargo_nombre
                FROM usuario u
                INNER JOIN trabajador t ON u.trabajador_id = t.trabajador_id
                INNER JOIN cargo c ON t.cargo_id = c.cargo_id
                WHERE u.usuario_id = %s;
            """, (session['usuario_id'],))
            trabajador = cursor.fetchone()

            # Obtener historial de conversacion del usuario
            cursor.execute("""
                SELECT pregunta, respuesta, intencion, fecha_hora
                FROM conversacion_chatbot
                WHERE usuario_id = %s
                ORDER BY fecha_hora ASC;
            """, (session['usuario_id'],))
            historial = cursor.fetchall()

            return render_template('chatbot.html', trabajador=trabajador, historial=historial)
    finally:
        conexion.close()

# -------------------------------------------------------------------------
# POST /chatbot/preguntar: Procesa la consulta y almacena el intercambio
# -------------------------------------------------------------------------
@chatbot_bp.route('/preguntar', methods=['POST'])
def preguntar():
    if 'usuario_id' not in session or session.get('rol') != 'trabajador':
        return jsonify({'error': 'Acceso no autorizado'}), 403

    # Obtener el mensaje enviado (compatible con JSON fetch o formulario)
    if request.is_json:
        datos = request.get_json()
        pregunta = datos.get('mensaje', '').strip()
    else:
        pregunta = request.form.get('mensaje', '').strip()

    if not pregunta:
        return jsonify({'error': 'Debe ingresar un mensaje válido'}), 400

    # Clasificacion de intencion y generacion de respuesta
    intencion, respuesta = clasificar_consulta(pregunta)
    ahora = datetime.datetime.now()

    # Guardar en la tabla conversacion_chatbot
    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            sql_insert = """
                INSERT INTO conversacion_chatbot (usuario_id, pregunta, respuesta, intencion, fecha_hora)
                VALUES (%s, %s, %s, %s, %s);
            """
            cursor.execute(sql_insert, (
                session['usuario_id'],
                pregunta,
                respuesta,
                intencion,
                ahora
            ))
            conexion.commit()
    except Exception as e:
        conexion.rollback()
        return jsonify({'error': f'Error al registrar consulta: {e}'}), 500
    finally:
        conexion.close()

    # Si es llamada AJAX devuelve JSON para la interfaz fluida
    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'pregunta': pregunta,
            'respuesta': respuesta,
            'intencion': intencion,
            'fecha_hora': ahora.strftime('%d/%m/%Y %H:%M')
        })

    return redirect(url_for('chatbot.index'))