from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
import os
from dotenv import load_dotenv

# Inicializa extensões
db = SQLAlchemy()
login_manager = LoginManager()

def create_app():
    app = Flask(__name__)
    load_dotenv()

    # Configurações via Variáveis de Ambiente
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'chave-secreta-padrao')
    # Ajuste para garantir que a URL do Neon seja lida corretamente pelo SQLAlchemy
    database_url = os.getenv('DATABASE_URL')
    if database_url and database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'

    # Registro de Blueprints
    from app.client.routes import client_bp
    from app.auth.routes import auth_bp
    app.register_blueprint(client_bp)
    app.register_blueprint(auth_bp)

    return app

