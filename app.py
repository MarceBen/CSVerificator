from flask import Flask, render_template, request, jsonify
import csv
import re
import os
import io

app = Flask(__name__)

# Analisis lexico para identificacion de tokens
def reconocer_token(valor):
 
    valor = valor.strip()  # Quitamos espacios al inicio y al final

    if valor == "":
        return "EMPTY"

    # Número entero: solo dígitos
    elif re.fullmatch(r'\d+', valor): 
        return "INTEGER"

    # Número decimal: dígitos, punto, más dígitos
    elif re.fullmatch(r'\d+\.\d+', valor):
        return "FLOAT"

    # Fecha ISO: AAAA-MM-DD
    elif re.fullmatch(r'\d{4}-\d{2}-\d{2}', valor):
        return "DATE"

    # Correo electrónico básico
    elif re.fullmatch(r'[\w.\-+]+@[\w.\-]+\.[a-zA-Z]{2,}', valor):
        return "EMAIL"

    # Texto con letras, tildes, espacios y algunos símbolos comunes
    elif re.fullmatch(r'[a-zA-ZáéíóúÁÉÍÓÚñÑüÜ0-9 _\-\.]+', valor):
        return "STRING"

    else:
        return "INVALID"


#  Recorre todas las filas del CSV y clasifica cada celda con su token.
#  Retorna una lista de resultados por fila con errores léxicos marcados.
def analizar_lexico(filas):
    
    resultados = []

    for numero_fila, fila in enumerate(filas, start=1):
        celdas = []
        errores_lexicos = []

        for col_idx, valor in enumerate(fila):
            token = reconocer_token(valor)
            celdas.append({
                "valor": valor,
                "token": token,
                "es_error": token == "INVALID"  # Marcamos si es inválido
            })
            if token == "INVALID":
                errores_lexicos.append(
                    f"Columna {col_idx + 1}: valor '{valor}' no reconocido"
                )

        resultados.append({
            "numero_fila": numero_fila,
            "celdas": celdas,
            "errores_lexicos": errores_lexicos
        })

    return resultados



#  ANÁLISIS SINTÁCTICO
#  Verificamos que todas las filas tengan la misma cantidad
#  de columnas que la cabecera (primera fila = encabezado).

#  Esto es como una "gramática": cada fila debe seguir la
#  estructura  →  campo, campo, campo, ... (N campos fijos)


def analizar_sintactico(encabezado, filas_datos):
    """
    Compara el número de columnas de cada fila con el encabezado.
    Si una fila tiene más o menos columnas → ERROR SINTÁCTICO.
    Retorna lista de errores sintácticos encontrados.
    """
    n_esperado = len(encabezado)  # Cuántas columnas debería tener cada fila
    errores = []

    for numero_fila, fila in enumerate(filas_datos, start=2):  # empieza en 2 porque la fila 1 es el header
        n_actual = len(fila)
        if n_actual != n_esperado:
            errores.append({
                "fila": numero_fila,
                "esperado": n_esperado,
                "encontrado": n_actual,
                "mensaje": (
                    f"Fila {numero_fila}: se esperaban {n_esperado} columnas "
                    f"pero se encontraron {n_actual}"
                )
            })

    return errores



#  GENERACIÓN DE SQL
#  Tomamos las filas válidas (sin errores léxicos ni sintácticos)
#  y las convertimos en sentencias SQL tipo INSERT INTO ...


def generar_sql(tabla, encabezado, filas_datos, filas_invalidas_idx):
    """
    Genera sentencias SQL INSERT para cada fila válida del CSV.

    Parámetros:
      tabla           → nombre de la tabla SQL destino
      encabezado      → lista de nombres de columnas
      filas_datos     → lista de filas (listas de strings)
      filas_invalidas_idx → índices de filas que tienen errores (se omiten)
    """
    sentencias = []

    # Construimos la parte fija: INSERT INTO tabla (col1, col2, ...)
    columnas = ", ".join(encabezado)

    for idx, fila in enumerate(filas_datos):
        # Si esta fila tiene errores, la saltamos
        if idx in filas_invalidas_idx:
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
            if token in ("INTEGER", "FLOAT"):
                valores.append(valor)
            elif token == "EMPTY":
                valores.append("NULL")  # Celda vacía → NULL en SQL
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
    """Página principal: muestra el formulario para subir el CSV."""
    return render_template("index.html")


@app.route("/analizar", methods=["POST"])
def analizar():
    """
    Recibe el archivo CSV subido por el usuario, lo analiza
    y devuelve los resultados en formato JSON para mostrarlos en la web.
    """

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
    filas_invalidas_idx = set()
    for i, resultado in enumerate(resultados_lexicos):
        if resultado["errores_lexicos"]:
            filas_invalidas_idx.add(i)

    # --- ANÁLISIS SINTÁCTICO (revisamos la estructura de cada fila) ---
    errores_sintacticos = analizar_sintactico(encabezado, filas_datos)

    # Las filas con errores sintácticos también se marcan como inválidas
    for err in errores_sintacticos:
        filas_invalidas_idx.add(err["fila"] - 2)  # -2 porque el índice empieza en 0 y fila en 2

    # --- GENERACIÓN DE SQL (solo si el usuario lo pidió) ---
    sentencias_sql = []
    if generar_sql_flag:
        sentencias_sql = generar_sql(nombre_tabla, encabezado, filas_datos, filas_invalidas_idx)

    # Contamos cuántas filas son válidas e inválidas
    total_filas = len(filas_datos)
    filas_validas = total_filas - len(filas_invalidas_idx)
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
            "filas_invalidas": len(filas_invalidas_idx),
            "total_errores_lexicos": total_errores_lexicos,
            "total_errores_sintacticos": len(errores_sintacticos),
        }
    })



#  PUNTO DE ENTRADA
#  Esto ejecuta el servidor cuando corremos: python app.py


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )