import datetime
from app.database import get_db_connection

def sembrar_trabajadores():
    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            print("Cargando trabajadores piloto...")

            # 1. Obtener IDs de cargos existentes
            cursor.execute("SELECT cargo_id, nombre FROM cargo;")
            cargos = {c['nombre']: c['cargo_id'] for c in cursor.fetchall()}

            # 2. Lista de trabajadores con datos realistas
            # Campos: cedula, nombres, apellidos, fecha_nacimiento, sexo, telefono, correo, 
            #         direccion, cargo_id, tipo_personal, fecha_ingreso, sueldo_base, hijos, 
            #         nivel_instruccion, banco, numero_cuenta
            trabajadores = [
                (
                    'V-12345678', 'Carlos', 'Mendoza', '1980-05-12', 'M', '0414-1234567',
                    'carlos.mendoza@concejo.gob.ve', 'San Felipe, Centro', cargos['Presidente del Concejo'],
                    'alto_nivel', '2021-11-21', 1500.00, 2, 'Licenciado',
                    'Banco de Venezuela', '01020123456789012345'
                ),
                (
                    'V-14567890', 'Elena', 'Perez', '1985-08-20', 'F', '0424-7654321',
                    'elena.perez@concejo.gob.ve', 'Independencia, Calle 28', cargos['Directora de Recursos Humanos'],
                    'libre_remocion', '2022-01-15', 1200.00, 1, 'Especialista',
                    'Banco Bicentenario', '01750987654321098765'
                ),
                (
                    'V-18901234', 'Roberto', 'Gomez', '1992-03-10', 'M', '0416-5554433',
                    'roberto.gomez@concejo.gob.ve', 'Independencia, Urb. Vista Hermosa', cargos['Analista de Recursos Humanos'],
                    'empleado_fijo', '2019-06-01', 800.00, 0, 'TSU',
                    'Banco de Venezuela', '01021111222233334444'
                ),
                (
                    'V-20123456', 'Mariana', 'Silva', '1995-11-05', 'F', '0412-9988776',
                    'mariana.silva@concejo.gob.ve', 'San Felipe, El Panteón', cargos['Asistente Administrativo'],
                    'empleado_contratado', '2024-02-01', 600.00, 1, 'Bachiller',
                    'Banco Bicentenario', '01752222333344445555'
                ),
                (
                    'V-15678123', 'Jose', 'Torres', '1982-07-14', 'M', '0414-3322110',
                    'jose.torres@concejo.gob.ve', 'Independencia, Calle 30', cargos['Asistente Administrativo'],
                    'obrero_fijo', '2015-04-10', 500.00, 3, 'Bachiller',
                    'Banco de Venezuela', '01023333444455556666'
                ),
                (
                    'V-23456789', 'Miguel', 'Rojas', '1998-09-25', 'M', '0426-8877665',
                    'miguel.rojas@concejo.gob.ve', 'San Felipe, La Ascensión', cargos['Asistente Administrativo'],
                    'obrero_contratado', '2024-05-15', 500.00, 0, 'Bachiller',
                    'Banco Bicentenario', '01754444555566667777'
                )
            ]

            sql_insert = """
                INSERT INTO trabajador (
                    cedula, nombres, apellidos, fecha_nacimiento, sexo, telefono, correo, 
                    direccion, cargo_id, tipo_personal, fecha_ingreso, sueldo_base, hijos, 
                    nivel_instruccion, banco, numero_cuenta, activo
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, true)
                ON DUPLICATE KEY UPDATE nombres = VALUES(nombres);
            """
            cursor.executemany(sql_insert, trabajadores)

        conexion.commit()
        print("=" * 50)
        print("6 TRABAJADORES PILOTO REGISTRADOS CORRECTAMENTE")
        print("=" * 50)
    except Exception as e:
        conexion.rollback()
        print(f"Error al sembrar trabajadores: {e}")
    finally:
        conexion.close()

if __name__ == '__main__':
    sembrar_trabajadores()