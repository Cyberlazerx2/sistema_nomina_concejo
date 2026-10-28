import os
import pymysql
from pymysql.cursors import DictCursor
from dotenv import load_dotenv

load_dotenv()

def get_db_connection():
    db_host = os.environ.get('DB_HOST', '127.0.0.1')
    db_user = os.environ.get('DB_USER', 'root')
    db_password = os.environ.get('DB_PASSWORD', '')
    db_name = os.environ.get('DB_NAME', 'concejo')
    db_port = int(os.environ.get('DB_PORT', 3306))

    config_conn = {
        'host': db_host,
        'user': db_user,
        'password': db_password,
        'port': db_port,
        'cursorclass': DictCursor,
        'charset': 'utf8mb4',
        'autocommit': False
    }

    # Si es Aiven / remoto, se exige SSL
    es_remoto = db_host not in ['127.0.0.1', 'localhost']
    if es_remoto:
        config_conn['ssl'] = {'ssl_mode': 'REQUIRED'}

    # 1. Intentar conectar a la base de datos configurada
    try:
        return pymysql.connect(database=db_name, **config_conn)
    except pymysql.err.OperationalError as e:
        # Error 1049: Unknown database -> Autodescubrimiento inteligente
        if e.args[0] == 1049:
            conn = pymysql.connect(**config_conn)
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SHOW DATABASES;")
                    dbs = [row['Database'].lower() for row in cursor.fetchall()]
                    
                    # Prioridad de bases de datos compatibles
                    candidatas = ['concejo', 'concejo_nomina', 'defaultdb']
                    db_encontrada = next((c for c in candidatas if c in dbs), None)
                    
                    if db_encontrada:
                        conn.select_db(db_encontrada)
                        return conn
            except Exception:
                conn.close()
                raise e
            conn.close()
            raise e
        raise e