from app import create_app

app = create_app()

if __name__ == "__main__":
    # Quando rodar localmente no Termux
    app.run(host='0.0.0.0', port=5000, debug=True)

