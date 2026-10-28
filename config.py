import os
import sys
from dotenv import load_dotenv

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, '.env'))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'concejo_independencia_secret_2026')
    CUENTA_PAGADORA_CONCEJO = os.environ.get('CUENTA_PAGADORA_CONCEJO', '01750071650000001149')
    
    # Parámetros de la Base de Datos (Por defecto apunta a 'concejo' según tu concejoMuncipal.sql)
    DB_USER = os.environ.get('DB_USER', 'root')
    DB_PASSWORD = os.environ.get('DB_PASSWORD', '')
    DB_HOST = os.environ.get('DB_HOST', '127.0.0.1')
    DB_PORT = int(os.environ.get('DB_PORT', 3306))
    DB_NAME = os.environ.get('DB_NAME', 'concejo')

    # Detección inteligente de Aiven / Remoto vs Local
    database_url = os.environ.get('DATABASE_URL')
    
    if database_url:
        if database_url.startswith("mysql://"):
            database_url = database_url.replace("mysql://", "mysql+pymysql://", 1)
        SQLALCHEMY_DATABASE_URI = database_url
    else:
        SQLALCHEMY_DATABASE_URI = (
            f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
        )

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Si es Aiven (externo), requiere SSL obligatorio. Si es tu PC (127.0.0.1/localhost), NO usa SSL.
    es_remoto = DB_HOST not in ['127.0.0.1', 'localhost'] or (database_url and 'aivencloud' in database_url)

    if es_remoto:
        SQLALCHEMY_ENGINE_OPTIONS = {
            "connect_args": {"ssl": {"ssl_mode": "REQUIRED"}},
            "pool_recycle": 280,
            "pool_pre_ping": True
        }
    else:
        SQLALCHEMY_ENGINE_OPTIONS = {
            "pool_recycle": 280,
            "pool_pre_ping": True
        }