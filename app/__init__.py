from flask import Flask, redirect, url_for
from config import Config

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Registro de módulos (Blueprints)
    from app.modules.auth import auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')

    # Ruta raíz: Redirige automáticamente al login
    @app.route('/')
    def index():
        return redirect(url_for('auth.login'))

    return app