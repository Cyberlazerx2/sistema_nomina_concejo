# Helper para convertir montos a letras mayúsculas oficiales venezolanas

UNIDADES = ["", "UN", "DOS", "TRES", "CUATRO", "CINCO", "SEIS", "SIETE", "OCHO", "NUEVE"]
DECENAS = ["", "DIEZ", "VEINTE", "TREINTA", "CUARENTA", "CINCUENTA", "SESENTA", "SETENTA", "OCHENTA", "NOVENTA"]
DIEZ_Y = ["DIEZ", "ONCE", "DOCE", "TRECE", "CATORCE", "QUINCE", "DIECISEIS", "DIECISIETE", "DIECIOCHO", "DIECINUEVE"]
VEINTE_Y = ["VEINTE", "VEINTIUNO", "VEINTIDOS", "VEINTITRES", "VEINTICUATRO", "VEINTICINCO", "VEINTISEIS", "VEINTISIETE", "VEINTIOCHO", "VEINTINUEVE"]
CENTENAS = ["", "CIENTO", "DOSCIENTOS", "TRESCIENTOS", "CUATROCIENTOS", "QUINIENTOS", "SEISCIENTOS", "SETECIENTOS", "OCHOCIENTOS", "NOVECIENTOS"]

def _centenas(n):
    if n == 100:
        return "CIEN"
    c = n // 100
    d = (n % 100) // 10
    u = n % 10
    cadena = CENTENAS[c]
    if d == 1 and u > 0:
        texto_dec = DIEZ_Y[u]
    elif d == 2 and u > 0:
        texto_dec = VEINTE_Y[u]
    else:
        texto_dec = DECENAS[d]
        if d > 2 and u > 0:
            texto_dec += " Y " + UNIDADES[u]
        elif d == 0 and u > 0:
            texto_dec = UNIDADES[u]
    if cadena and texto_dec:
        return f"{cadena} {texto_dec}"
    return cadena or texto_dec or ""

def numero_a_letras(monto):
    try:
        monto_float = float(monto)
    except (ValueError, TypeError):
        monto_float = 0.0

    parte_entera = int(monto_float)
    centimos = int(round((monto_float - parte_entera) * 100))

    if parte_entera == 0:
        texto_entero = "CERO"
    elif parte_entera < 1000:
        texto_entero = _centenas(parte_entera)
    elif parte_entera < 1000000:
        miles = parte_entera // 1000
        resto = parte_entera % 1000
        txt_miles = "MIL" if miles == 1 else f"{_centenas(miles)} MIL"
        txt_resto = _centenas(resto)
        texto_entero = f"{txt_miles} {txt_resto}".strip()
    else:
        texto_entero = str(parte_entera)

    return f"{texto_entero} BOLIVARES CON {centimos:02d}/100 CENTIMOS"