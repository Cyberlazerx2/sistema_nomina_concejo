import datetime
from werkzeug.security import generate_password_hash
from app.database import get_db_connection

def sembrar_datos():
    conexion = get_db_connection()
    try:
        with conexion.cursor() as cursor:
            print("Iniciando carga de datos iniciales...")

            # 1. ROLES INSTITUCIONALES
            roles = [
                ('analista_rrhh', 'Elaboracion y precalculo de nominas'),
                ('directora_rrhh', 'Revision, rechazo o validacion de nominas y gestion de personal'),
                ('presidente', 'Aprobacion institucional y bloqueo definitivo del periodo'),
                ('trabajador', 'Consulta individual de recibos de pago y autoservicio'),
                ('tecnico_informatica', 'Mantenimiento de infraestructura y soporte del sistema')
            ]
            sql_rol = "INSERT IGNORE INTO rol (nombre, descripcion) VALUES (%s, %s);"
            cursor.executemany(sql_rol, roles)
            print("-> Roles institucionales verificados.")

            # 2. CONCEPTOS DE LEY Y HABERES BASE
            conceptos = [
                ('SUELDO', 'Sueldo Base Quincenal', 'asignacion', 'fijo', 0.0000, 'sueldo_base', True, 'Tabulador ONAPRE / LOTTT Art. 106'),
                ('CESTATICKET', 'Bono de Alimentacion Cestaticket', 'asignacion', 'fijo', 0.0000, 'salario_normal', True, 'Decreto Cestaticket Socialista 2015'),
                ('PRIMA_PROF', 'Prima por Profesionalizacion', 'asignacion', 'porcentaje', 0.0000, 'sueldo_base', False, 'Tabulador de Primas ONAPRE'),
                ('PRIMA_ANTIG', 'Prima por Antiguedad y Años de Servicio', 'asignacion', 'formula', 0.0000, 'sueldo_base', False, 'Tabulador de Primas ONAPRE'),
                ('PRIMA_HIJO', 'Prima por Carga Familiar (Hijos)', 'asignacion', 'formula', 0.0000, 'sueldo_base', False, 'Tabulador de Primas ONAPRE'),
                ('PRIMA_JERARQ', 'Prima de Jerarquia', 'asignacion', 'fijo', 0.0000, 'sueldo_base', False, 'Escala de Sueldos y RAC Municipal'),
                ('PRIMA_RESP', 'Prima de Responsabilidad', 'asignacion', 'fijo', 0.0000, 'sueldo_base', False, 'Escala de Sueldos y RAC Municipal'),
                ('IVSS', 'Seguro Social Obligatorio (4%)', 'deduccion', 'porcentaje', 0.0400, 'sueldo_base', True, 'Ley del Seguro Social Art. 59'),
                ('RPE', 'Regimen Prestacional de Empleo (0.5%)', 'deduccion', 'porcentaje', 0.0050, 'sueldo_base', True, 'Ley del Regimen Prestacional de Empleo'),
                ('FAOV', 'Fondo de Ahorro Obligatorio para la Vivienda (1%)', 'deduccion', 'porcentaje', 0.0100, 'sueldo_base', True, 'Ley Reg. Prestacional Vivienda Art. 138'),
                ('FONDO_JUB', 'Fondo de Jubilaciones y Pensiones (3%)', 'deduccion', 'porcentaje', 0.0300, 'sueldo_base', True, 'Estatuto de Prevision Social del Funcionario')
            ]
            sql_concepto = """
                INSERT IGNORE INTO concepto 
                (codigo, nombre, tipo, metodo, valor, base_calculo, obligatorio, fundamento, activo) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, true);
            """
            cursor.executemany(sql_concepto, conceptos)
            print("-> Catalogo de conceptos y retenciones de ley cargado.")

            # 3. DEPARTAMENTOS BASE
            departamentos = [
                ('Presidencia del Concejo',),
                ('Direccion de Recursos Humanos',),
                ('Administracion y Servicios',),
                ('Coordinacion de Informatica',)
            ]
            cursor.executemany("INSERT IGNORE INTO departamento (nombre) VALUES (%s);", departamentos)
            print("-> Departamentos cargados.")

            # Obtener IDs de departamentos para vincular cargos
            cursor.execute("SELECT departamento_id, nombre FROM departamento;")
            dept_map = {d['nombre']: d['departamento_id'] for d in cursor.fetchall()}

            # 4. CARGOS BASE (RAC)
            cargos = [
                (dept_map['Presidencia del Concejo'], 'Presidente del Concejo', 1500.00),
                (dept_map['Direccion de Recursos Humanos'], 'Directora de Recursos Humanos', 1200.00),
                (dept_map['Direccion de Recursos Humanos'], 'Analista de Recursos Humanos', 800.00),
                (dept_map['Coordinacion de Informatica'], 'Tecnico de Informatica', 800.00),
                (dept_map['Administracion y Servicios'], 'Asistente Administrativo', 600.00)
            ]
            sql_cargo = "INSERT IGNORE INTO cargo (departamento_id, nombre, sueldo_base) VALUES (%s, %s, %s);"
            cursor.executemany(sql_cargo, cargos)
            print("-> Cargos institucionales cargados.")

            # Obtener IDs de roles para vincular usuarios
            cursor.execute("SELECT rol_id, nombre FROM rol;")
            rol_map = {r['nombre']: r['rol_id'] for r in cursor.fetchall()}

            # 5. USUARIOS ADMINISTRATIVOS DE PRUEBA
            # Contraseña por defecto para pruebas: Admin123*
            clave_cifrada = generate_password_hash("Admin123*")
            ahora = datetime.datetime.now()

            usuarios_prueba = [
                (rol_map['analista_rrhh'], 'analista.rrhh', clave_cifrada, ahora),
                (rol_map['directora_rrhh'], 'directora.rrhh', clave_cifrada, ahora),
                (rol_map['presidente'], 'presidente.concejo', clave_cifrada, ahora),
                (rol_map['tecnico_informatica'], 'admin.tecnico', clave_cifrada, ahora)
            ]
            sql_usuario = """
                INSERT IGNORE INTO usuario 
                (rol_id, nombre_usuario, clave_hash, creado_en, activo) 
                VALUES (%s, %s, %s, %s, true);
            """
            cursor.executemany(sql_usuario, usuarios_prueba)
            print("-> Usuarios administrativos de prueba creados.")

        conexion.commit()
        print("=" * 50)
        print("POBLADO INICIAL COMPLETADO CON EXITO")
        print("Contraseña temporal para los 4 usuarios: Admin123*")
        print("=" * 50)
    except Exception as e:
        conexion.rollback()
        print(f"Error durante el sembrado: {e}")
    finally:
        conexion.close()

if __name__ == '__main__':
    sembrar_datos()