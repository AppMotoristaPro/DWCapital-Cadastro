from flask import Flask

def create_app():
    app = Flask(__name__)
    
    # Chave secreta temporária para a Fase 1
    app.config['SECRET_KEY'] = 'dwcapital-secret-key-temp'

    # Registrando as rotas do cliente para o nosso Hello World
    from app.client.routes import client_bp
    app.register_blueprint(client_bp)

    return app

