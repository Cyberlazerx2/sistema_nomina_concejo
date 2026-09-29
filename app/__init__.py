from flask import Flask, redirect, url_for, session
from config import Config
from app.database import get_db_connection

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Revalidación de sesión por petición
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

                    # Si el usuario no existe, fue desactivado o se le modificó el rol
                    if not usuario or not usuario['activo'] or usuario['rol_nombre'] != session.get('rol'):
                        session.clear()
            except Exception:
                session.clear()
            finally:
                conexion.close()

    # 1. Módulo de Autenticación
    from app.modules.auth import auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')

    # 2. Módulo de Cálculo de Nómina
    from app.modules.nomina import nomina_bp
    app.register_blueprint(nomina_bp, url_prefix='/nomina')

    # 3. Módulo de Gestión de Trabajadores y Expedientes
    from app.modules.trabajadores.routes import trabajadores_bp
    app.register_blueprint(trabajadores_bp, url_prefix='/trabajadores')

    # 4. Módulo de Configuración de Conceptos
    from app.modules.config.routes import config_bp
    app.register_blueprint(config_bp, url_prefix='/config')

    # 5. Módulo de Estructura Organizacional
    from app.modules.organizacion.routes import organizacion_bp
    app.register_blueprint(organizacion_bp, url_prefix='/organizacion')

    # Redirección raíz
    @app.route('/')
    def index():
        return redirect(url_for('auth.login'))

    return app