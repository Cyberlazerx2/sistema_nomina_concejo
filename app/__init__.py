from flask import Flask, redirect, url_for
from config import Config

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # 1. Modulo de Autenticacion
    from app.modules.auth import auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')

    # 2. Modulo de Calculo de Nomina
    from app.modules.nomina import nomina_bp
    app.register_blueprint(nomina_bp, url_prefix='/nomina')

    # Redireccion a la raiz
    @app.route('/')
    def index():
        return redirect(url_for('auth.login'))

    return app