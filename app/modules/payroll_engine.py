from decimal import Decimal, ROUND_HALF_UP

def redondear(valor):
    """Garantiza que todo cálculo financiero tenga exactamente 2 decimales bancarios."""
    if not isinstance(valor, Decimal):
        valor = Decimal(str(valor))
    return valor.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

MAPA_PRIMA_PROFESIONAL = {
    'TSU': 'PRIMA_PROF_TSU',
    'Licenciado': 'PRIMA_PROF_LIC',
    'Ingeniero': 'PRIMA_PROF_LIC',
    'Especialista': 'PRIMA_PROF_ESP',
    'Magister': 'PRIMA_PROF_ESP',
    'Doctor': 'PRIMA_PROF_ESP',
}

def calcular_quincena_trabajador(trabajador, conceptos_catalogo, conceptos_individuales=None,
                                  solo_cestaticket=False, aplica_leyes_sociales=True,
                                  es_monto_manual=False, monto_manual=None,
                                  concepto_asignacion_manual=None):
    conceptos_individuales = conceptos_individuales or []
    mapa_conceptos = {c['codigo']: c for c in conceptos_catalogo}

    detalles = []
    total_asignaciones = Decimal('0.00')
    total_deducciones = Decimal('0.00')

    def agregar(concepto, monto, descripcion=None):
        nonlocal total_asignaciones, total_deducciones
        monto = redondear(monto)
        if monto <= 0 or not concepto:
            return
        
        detalles.append({
            'concepto_id': concepto['concepto_id'],
            'codigo_concepto': concepto['codigo'],
            'descripcion': (descripcion or concepto['nombre'])[:80],
            'tipo': concepto.get('tipo', 'asignacion'),
            'monto': monto,
        })
        if concepto.get('tipo') == 'asignacion':
            total_asignaciones += monto
        else:
            total_deducciones += monto

    # =========================================================================
    # RAMA 1: NÓMINAS CON MONTO MANUAL (BONOS, CESTATICKET O DECRETOS)
    # =========================================================================
    if es_monto_manual:
        monto_base = Decimal(str(monto_manual or '0.00'))
        
        # Concepto resuelto: prioridad al objeto validado en BD
        c_asig = concepto_asignacion_manual or mapa_conceptos.get('BONO_EXTRA') or mapa_conceptos.get('CESTATICKET')
        if not c_asig:
            c_asig = next((c for c in conceptos_catalogo if c.get('tipo') == 'asignacion'), None)

        if c_asig:
            agregar(c_asig, monto_base, c_asig.get('nombre', 'Asignación Extraordinaria'))

        # Si el tipo de nómina posee carácter salarial (Art. 104 LOTTT):
        if aplica_leyes_sociales:
            for codigo, concepto in mapa_conceptos.items():
                if concepto.get('tipo') == 'deduccion' and concepto.get('obligatorio'):
                    valor = Decimal(str(concepto['valor'] or 0))
                    tasa = valor / Decimal('100') if valor > Decimal('1.0') else valor
                    monto_ded = redondear(monto_base * tasa)
                    if monto_ded > 0:
                        agregar(concepto, monto_ded, concepto['nombre'])

        neto = redondear(total_asignaciones - total_deducciones)
        return {
            'trabajador_id': trabajador['trabajador_id'],
            'cedula': trabajador['cedula'],
            'nombre_completo': f"{trabajador['nombres']} {trabajador['apellidos']}",
            'dias_trabajados': 30,
            'total_asignaciones': total_asignaciones,
            'total_deducciones': total_deducciones,
            'neto_pagar': neto,
            'detalles': detalles,
        }

    # =========================================================================
    # RAMA 2: CESTATICKET ORDINARIO (VALOR DESDE BD)
    # =========================================================================
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

    # =========================================================================
    # RAMA 3: NÓMINA ORDINARIA QUINCENAL (TABULADOR ONAPRE / RAC)
    # =========================================================================
    sueldo_mensual = Decimal(str(trabajador['sueldo_base']))
    sueldo_quincenal = redondear(sueldo_mensual / Decimal('2'))

    c_sueldo = mapa_conceptos.get('SUELDO')
    if c_sueldo:
        agregar(c_sueldo, sueldo_quincenal, 'Sueldo Base Quincenal (15 días)')

    for codigo, concepto in mapa_conceptos.items():
        if codigo in ('SUELDO', 'CESTATICKET') or not concepto.get('obligatorio'):
            continue
        if not aplica_leyes_sociales and concepto.get('tipo') == 'deduccion':
            continue

        valor = Decimal(str(concepto['valor'] or 0))
        if concepto['metodo'] == 'porcentaje':
            tasa = valor / Decimal('100') if valor > Decimal('1.0') else valor
            monto = redondear(sueldo_quincenal * tasa)
        elif concepto['metodo'] == 'fijo':
            monto = redondear(valor)
        else:
            continue
        agregar(concepto, monto)

    nivel = trabajador.get('nivel_instruccion') or ''
    codigo_prof = MAPA_PRIMA_PROFESIONAL.get(nivel)
    if codigo_prof:
        c_prof = mapa_conceptos.get(codigo_prof)
        if c_prof:
            v_prof = Decimal(str(c_prof['valor'] or 0))
            tasa_prof = v_prof / Decimal('100') if v_prof > Decimal('1.0') else v_prof
            agregar(c_prof, redondear(sueldo_quincenal * tasa_prof), f'Prima Profesionalización ({nivel})')

    hijos = int(trabajador.get('hijos') or 0)
    c_hijo = mapa_conceptos.get('PRIMA_HIJO')
    if c_hijo and hijos > 0:
        m_hijo = redondear(Decimal(str(c_hijo['valor'] or 0)) * Decimal(str(hijos)))
        agregar(c_hijo, m_hijo, f'Prima por Carga Familiar ({hijos} hijos)')

    for ci in conceptos_individuales:
        c_ind = ci.get('concepto') or mapa_conceptos.get(ci.get('codigo'))
        if c_ind:
            agregar(c_ind, Decimal(str(ci['valor'])), c_ind['nombre'])

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