import os
import pymysql
from pymysql.cursors import DictCursor

def get_db_connection():
    return pymysql.connect(
        host=os.environ.get('DB_HOST', 'localhost'),
        user=os.environ.get('DB_USER', 'root'),
        password=os.environ.get('DB_PASSWORD', 'root123'),  # Tu clave local si tienes
        database=os.environ.get('DB_NAME', 'concejo'),
        port=int(os.environ.get('DB_PORT', 3306)),
        cursorclass=DictCursor,
        autocommit=False
    )