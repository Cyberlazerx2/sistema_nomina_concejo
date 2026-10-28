import os
import sys
from dotenv import load_dotenv

# 1. Asegurar la ruta raíz del proyecto
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# 2. Cargar variables de entorno del archivo .env
load_dotenv(os.path.join(BASE_DIR, '.env'))

# 3. Importar la función creadora 'create_app' e instanciar 'app'
from app import create_app

app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.environ.get('FLASK_DEBUG', '1') == '1'
    
    print(f" * Servidor iniciado exitosamente en: http://127.0.0.1:{port}")
    app.run(host='127.0.0.1', port=port, debug=debug_mode)