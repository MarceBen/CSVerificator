from flask import Flask, render_template, request, jsonify
import csv
import re
import os
import io

app = Flask(__name__) #inicializamos el flask.

#funcion para reconocer tokens, ademas de fecha en formato americano y correo electronico.
def reconocer_token(valor):

    valor = valor.strip()  # limpiamos espacios para evitar falsos errores

    if valor == "":
        return "NULL_VALUE"  # celda vacía es NULL en SQL

    elif re.fullmatch(r'\d{4}-\d{2}-\d{2}', valor):
        return "VALUE_DATE"  # va primero que numérico para que 2026-01-15 no se confunda

    elif re.fullmatch(r'\d+(\.\d+)?', valor):  # entero Y decimal en una sola regex para que se considere parte de un solo token
        return "NUMERIC_VALUE"  # va sin comillas para exportar en sql

    elif re.fullmatch(r'[a-zA-ZáéíóúÁÉÍÓÚñÑüÜ][a-zA-ZáéíóúÁÉÍÓÚñÑüÜ0-9 _\-\.@]*', valor):
         return "TEXT_VALUE" # va con comillas simples en SQL

    else:
        return "INVALID_VALUE"  # dispara el error léxico, la fila no se exporta


# recorremos las filas del csv para verificar sus tokens
def analizar_lexico(filas): #filas del csv
    
    resultados = [] #aqui almacenamos los resultados.

    for numeroFila, fila in enumerate(filas, start=1): #iteramos desde el 1 para facilitar lectura y no empezar de 0 xD
        celdas = [] #por cada fila creamos una lista de celdas
        errores_lexicos = [] #por cada fila creamos una lista de errores

        for indexColumn, valor in enumerate(fila): #recorremos las columnas de la fila actual

            token = reconocer_token(valor) #reconocemos el token de la celda
            celdas.append({"valor": valor,"token": token,"es_error": token == "INVALID_VALUE" }) #agregamos a la lista de celdas el token que reconocio

            if token == "INVALID_VALUE":

                errores_lexicos.append(f"Columna {indexColumn + 1}: valor '{valor}' no reconocido") # si el token es invalido lo metemos a la lista de errores

        resultados.append({"numero_fila": numeroFila,"celdas": celdas,"errores_lexicos": errores_lexicos}) #agregamos la lista de celdas y errores a la lista de resultados

    return resultados

#verificamos la estructura principal del csv, si tiene el mismo numero de columnas que el encabezado
def analizar_sintactico(encabezado, filas_datos):

    n_esperado = len(encabezado)  # Cuántas columnas debería tener cada fila
    errores = [] # creamos una lista de errores

    for numero_fila, fila in enumerate(filas_datos, start=2):  # comenzamos desde el 2 para mejorar mensaje de errores.
        n_actual = len(fila) # cuantas columnas tiene la fila
        if n_actual != n_esperado: # si no tiene el mismo numero de columnas que el encabezado
            errores.append({"fila": numero_fila,"esperado": n_esperado,"encontrado": n_actual,"mensaje": (f"Fila {numero_fila}: se esperaban {n_esperado} columnas "f"pero se encontraron {n_actual}")})

    return errores



#  GENERACIÓN DE SQL



def generar_sql(tabla, encabezado, filas_datos, filas_invalidas_idx):
 
    sentencias = []

    # Construimos la parte fija: INSERT INTO tabla (col1, col2, ...)
    columnas = ", ".join(encabezado)

    for i, fila in enumerate(filas_datos):
        # Si esta fila tiene errores, la saltamos
        if i in filas_invalidas_idx:
            continue

        # Si la fila no tiene el número correcto de columnas, también se salta
        if len(fila) != len(encabezado):
            continue

        # Construimos los valores: los strings van entre comillas simples
        valores = []
        for valor in fila:
            valor = valor.strip()
            token = reconocer_token(valor)

            # Los números no llevan comillas, el texto sí
            if token == "NUMERIC_VALUE":
                valores.append(valor)

            elif token == "NULL_VALUE":
                valores.append("NULL")  # Celda vacía  NULL en SQL
            else:
                # Escapamos comillas simples dentro del texto para evitar errores SQL
                valor_seguro = valor.replace("'", "''")
                valores.append(f"'{valor_seguro}'")

        valores_str = ", ".join(valores)
        sentencia = f"INSERT INTO {tabla} ({columnas}) VALUES ({valores_str});"
        sentencias.append(sentencia)

    return sentencias



#  Flask xd


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/analizar", methods=["POST"])
def analizar():

    # Verificamos que el usuario haya enviado un archivo
    if "archivo" not in request.files:
        return jsonify({"error": "No se recibió ningún archivo."}), 400

    archivo = request.files["archivo"]

    # Verificamos que tenga nombre y que sea .csv o .xlsx simplificado
    if archivo.filename == "":
        return jsonify({"error": "El archivo no tiene nombre."}), 400

    # Leemos el contenido del archivo en memoria (sin guardarlo en disco)
    contenido = archivo.read().decode("utf-8", errors="replace")

    # Nombre de tabla SQL: tomado del formulario o del nombre del archivo
    nombre_tabla = request.form.get("tabla", "").strip()
    if not nombre_tabla:
        # Si no ingresó tabla, usamos el nombre del archivo sin extensión
        nombre_tabla = os.path.splitext(archivo.filename)[0]
        nombre_tabla = re.sub(r'[^a-zA-Z0-9_]', '_', nombre_tabla)  # Limpiamos caracteres raros

    generar_sql_flag = request.form.get("generar_sql") == "true"

    # Parseamos el CSV usando csv.reader
    lector = csv.reader(io.StringIO(contenido))
    filas = list(lector)

    # Si el archivo está vacío
    if len(filas) == 0:
        return jsonify({"error": "El archivo CSV está vacío."}), 400

    # La primera fila es el encabezado (nombres de columnas)
    encabezado = filas[0]
    filas_datos = filas[1:]  # El resto son los datos

    # --- ANÁLISIS LÉXICO (revisamos cada celda) ---
    resultados_lexicos = analizar_lexico(filas_datos)

    # Recolectamos qué índices de filas tienen errores léxicos
    filasInvalidas = set()
    for i, resultado in enumerate(resultados_lexicos):
        if resultado["errores_lexicos"]:
            filasInvalidas.add(i)

    # --- ANÁLISIS SINTÁCTICO (revisamos la estructura de cada fila) ---
    errores_sintacticos = analizar_sintactico(encabezado, filas_datos)

    # Las filas con errores sintácticos también se marcan como inválidas
    for err in errores_sintacticos:
        filasInvalidas.add(err["fila"] - 2)  # -2 porque el índice empieza en 0 y fila en 2

    # --- GENERACIÓN DE SQL (solo si el usuario lo pidió) ---
    sentencias_sql = []
    if generar_sql_flag:
        sentencias_sql = generar_sql(nombre_tabla, encabezado, filas_datos, filasInvalidas)

    # Contamos cuántas filas son válidas e inválidas
    total_filas = len(filas_datos)
    filas_validas = total_filas - len(filasInvalidas)
    total_errores_lexicos = sum(len(r["errores_lexicos"]) for r in resultados_lexicos)

    # Devolvemos todo en formato JSON al frontend
    return jsonify({
        "encabezado": encabezado,
        "resultados_lexicos": resultados_lexicos,
        "errores_sintacticos": [e["mensaje"] for e in errores_sintacticos],
        "sentencias_sql": sentencias_sql,
        "resumen": {
            "total_filas": total_filas,
            "filas_validas": filas_validas,
            "filas_invalidas": len(filasInvalidas),
            "total_errores_lexicos": total_errores_lexicos,
            "total_errores_sintacticos": len(errores_sintacticos),
        }
    })



#  PUNTO DE ENTRADA
#  Esto ejecuta el servidor cuando corremos: python app.py
# ruta para render basicamente, sino no entra

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )