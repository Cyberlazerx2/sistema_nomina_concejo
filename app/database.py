import pymysql
from pymysql.cursors import DictCursor
from config import Config

def get_db_connection():
    """Retorna una conexion activa a la base de datos MySQL usando diccionarios."""
    return pymysql.connect(
        host=Config.DB_HOST,
        user=Config.DB_USER,
        password=Config.DB_PASSWORD,
        database=Config.DB_NAME,
        port=Config.DB_PORT,
        cursorclass=DictCursor,
        autocommit=False
    )