from app import create_app, db

app = create_app()

# Esta linha garante que o banco não tente recriar tabelas que já existem,
# resolvendo o problema de "DuplicateTable" de uma vez por todas.
with app.app_context():
    try:
        db.create_all()
    except Exception as e:
        print(f"Aviso de banco de dados ignorado: {e}")

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=10000)

