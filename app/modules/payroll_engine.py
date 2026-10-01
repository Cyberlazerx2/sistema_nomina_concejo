from decimal import Decimal, ROUND_HALF_UP


def redondear(valor):
    """Garantiza que todo calculo financiero tenga exactamente 2 decimales bancarios."""
    if not isinstance(valor, Decimal):
        valor = Decimal(str(valor))
    return valor.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


# El nivel de instruccion decide CUAL fila de concepto aplica, pero el PORCENTAJE
# sigue viviendo en esa fila (concepto.valor), nunca aqui. Si se necesita un nivel
# nuevo, se agrega una linea aqui + una fila en `concepto`; nunca un porcentaje suelto.
MAPA_PRIMA_PROFESIONAL = {
    'TSU': 'PRIMA_PROF_TSU',
    'Licenciado': 'PRIMA_PROF_LIC',
    'Ingeniero': 'PRIMA_PROF_LIC',
    'Especialista': 'PRIMA_PROF_ESP',
    'Magister': 'PRIMA_PROF_ESP',
    'Doctor': 'PRIMA_PROF_ESP',
}


def calcular_quincena_trabajador(trabajador, conceptos_catalogo, conceptos_individuales=None,
                                  solo_cestaticket=False):
    """
    Motor de calculo generico: ningun porcentaje ni monto esta escrito en este archivo.
    Todo se lee de la tabla `concepto` y, para primas que solo aplican a un trabajador
    especifico (jerarquia, responsabilidad, antiguedad...), de `concepto_trabajador`.

    trabajador: dict con los datos del trabajador (sueldo_base, hijos, nivel_instruccion...)
    conceptos_catalogo: lista de filas activas de la tabla `concepto`
    conceptos_individuales: lista de filas de `concepto_trabajador` para ESTE trabajador,
        cada una con su `concepto` ya resuelto (ver nota de integracion mas abajo).
        Puede venir vacia o None si el trabajador no tiene primas individuales asignadas.
    solo_cestaticket: el Cestaticket se paga en una corrida MENSUAL aparte, nunca junto
        a la quincena (confirmado en la entrevista). Cuando esto es True, la funcion
        calcula UNICAMENTE el Cestaticket y devuelve un resultado simplificado --
        no toca sueldo, primas ni deducciones, para que nunca se pague dos veces al mes.
    """
    conceptos_individuales = conceptos_individuales or []
    mapa_conceptos = {c['codigo']: c for c in conceptos_catalogo}

    detalles = []
    total_asignaciones = Decimal('0.00')
    total_deducciones = Decimal('0.00')

    def agregar(concepto, monto, descripcion=None):
        nonlocal total_asignaciones, total_deducciones
        monto = redondear(monto)
        if monto == 0:
            return
        detalles.append({
            'concepto_id': concepto['concepto_id'],
            'codigo_concepto': concepto['codigo'],
            'descripcion': descripcion or concepto['nombre'],
            'tipo': concepto['tipo'],
            'monto': monto,
        })
        if concepto['tipo'] == 'asignacion':
            total_asignaciones += monto
        else:
            total_deducciones += monto

    # RAMA APARTE: corrida mensual de Cestaticket, sin nada mas.
    if solo_cestaticket:
        c_ces = mapa_conceptos.get('CESTATICKET')
        if c_ces:
            agregar(c_ces, Decimal(str(c_ces['valor'] or 0)), 'Cestaticket Mensual')
        return {
            'trabajador_id': trabajador['trabajador_id'],
            'cedula': trabajador['cedula'],
            'nombre_completo': f"{trabajador['nombres']} {trabajador['apellidos']}",
            'dias_trabajados': 30,
            'total_asignaciones': total_asignaciones,
            'total_deducciones': Decimal('0.00'),
            'neto_pagar': redondear(total_asignaciones),
            'detalles': detalles,
        }

    sueldo_mensual = Decimal(str(trabajador['sueldo_base']))
    sueldo_quincenal = redondear(sueldo_mensual / Decimal('2'))

    # 1. SUELDO BASE -- el unico concepto que no sale de un porcentaje/monto de la tabla,
    #    porque ES la base sobre la que se calculan los demas.
    c_sueldo = mapa_conceptos.get('SUELDO')
    if c_sueldo:
        agregar(c_sueldo, sueldo_quincenal, 'Sueldo Base Quincenal (15 días)')

    # 2. CONCEPTOS OBLIGATORIOS DE APLICACION GENERAL EN LA QUINCENA
    #    Las 4 deducciones de ley. CESTATICKET se excluye siempre aqui: se paga
    #    mensual, aparte (ver rama solo_cestaticket arriba), nunca dentro de la quincena.
    #      porcentaje -> concepto.valor se aplica sobre el sueldo quincenal
    #      fijo       -> concepto.valor es el monto directo
    #    Cambiar una tasa = editar la fila en `concepto`. Este archivo no se vuelve a tocar.
    for codigo, concepto in mapa_conceptos.items():
        if codigo in ('SUELDO', 'CESTATICKET') or not concepto.get('obligatorio'):
            continue
        valor = Decimal(str(concepto['valor'] or 0))
        if concepto['metodo'] == 'porcentaje':
            monto = sueldo_quincenal * valor
        elif concepto['metodo'] == 'fijo':
            monto = valor
        else:
            continue  # metodo 'formula': reservado para reglas mas complejas a futuro
        agregar(concepto, monto)

    # 3. PRIMA POR PROFESIONALIZACION
    nivel = trabajador.get('nivel_instruccion') or ''
    codigo_prof = MAPA_PRIMA_PROFESIONAL.get(nivel)
    if codigo_prof:
        c_prof = mapa_conceptos.get(codigo_prof)
        if c_prof:
            monto_prof = sueldo_quincenal * Decimal(str(c_prof['valor'] or 0))
            agregar(c_prof, monto_prof, f'Prima Profesionalización ({nivel})')

    # 4. PRIMA POR HIJO -- el "monto por hijo" vive en concepto.valor (metodo fijo);
    #    aqui solo se multiplica por la cantidad de hijos del trabajador.
    hijos = trabajador.get('hijos') or 0
    c_hijo = mapa_conceptos.get('PRIMA_HIJO')
    if c_hijo and hijos > 0:
        monto_hijos = Decimal(str(c_hijo['valor'] or 0)) * Decimal(str(hijos))
        agregar(c_hijo, monto_hijos, f'Prima por Carga Familiar ({hijos} hijos)')

    # 5. PRIMAS INDIVIDUALES (jerarquia, responsabilidad, antiguedad...)
    #    No aplican a todos: cada fila viene de `concepto_trabajador`, la tabla pensada
    #    exactamente para esto. El monto ya viene resuelto para este trabajador.
    for ci in conceptos_individuales:
        concepto = ci.get('concepto') or mapa_conceptos.get(ci.get('codigo'))
        if not concepto:
            continue
        agregar(concepto, Decimal(str(ci['valor'])), concepto['nombre'])

    neto_pagar = redondear(total_asignaciones - total_deducciones)

    return {
        'trabajador_id': trabajador['trabajador_id'],
        'cedula': trabajador['cedula'],
        'nombre_completo': f"{trabajador['nombres']} {trabajador['apellidos']}",
        'dias_trabajados': 15,
        'total_asignaciones': total_asignaciones,
        'total_deducciones': total_deducciones,
        'neto_pagar': neto_pagar,
        'detalles': detalles,
    }