from app import create_app

app = create_app()

if __name__ == '__main__':
    # debug=True permite que el servidor se reinicie solo ante cualquier cambio en el codigo
    app.run(debug=True, host='127.0.0.1', port=5000)