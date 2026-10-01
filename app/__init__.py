from flask import Flask, redirect, url_for, session
from config import Config
from app.database import get_db_connection

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    @app.before_request
    def revalidar_sesion():
        if 'usuario_id' in session:
            conexion = get_db_connection()
            try:
                with conexion.cursor() as cursor:
                    sql = """
                        SELECT u.activo, r.nombre AS rol_nombre
                        FROM usuario u
                        INNER JOIN rol r ON u.rol_id = r.rol_id
                        WHERE u.usuario_id = %s;
                    """
                    cursor.execute(sql, (session['usuario_id'],))
                    usuario = cursor.fetchone()

                    if not usuario or not usuario['activo'] or usuario['rol_nombre'] != session.get('rol'):
                        session.clear()
            except Exception:
                session.clear()
            finally:
                conexion.close()

    # 1. Autenticación
    from app.modules.auth import auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')

    # 2. Cálculo de Nómina
    from app.modules.nomina import nomina_bp
    app.register_blueprint(nomina_bp, url_prefix='/nomina')

    # 3. Gestión de Trabajadores
    from app.modules.trabajadores.trabajadores_routes import trabajadores_bp
    app.register_blueprint(trabajadores_bp, url_prefix='/trabajadores')

    # 4. Configuración de Conceptos
    from app.modules.config.config_routes import config_bp
    app.register_blueprint(config_bp, url_prefix='/config')

    # 5. Estructura Organizacional
    from app.modules.organizacion.organizacion_routes import organizacion_bp
    app.register_blueprint(organizacion_bp, url_prefix='/organizacion')

    # 6. Portal de Autoservicio del Trabajador
    from app.modules.portal.routes import portal_bp
    app.register_blueprint(portal_bp, url_prefix='/portal')
    
    # 7. Módulo de Registro de Asistencia
    from app.modules.asistencia.asistencia_routes import asistencia_bp
    app.register_blueprint(asistencia_bp, url_prefix='/asistencia')
    
    # 8. Módulo Técnico de Informática (Soporte y Seguridad)
    from app.modules.tecnico.tecnico_routes import tecnico_bp
    app.register_blueprint(tecnico_bp, url_prefix='/tecnico')

    @app.route('/')
    def index():
        return redirect(url_for('auth.login'))

    return app