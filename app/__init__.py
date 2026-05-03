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
    
    # Busca a URL do banco
    database_url = os.getenv('DATABASE_URL')
    
    # Trava de segurança
    if not database_url:
        raise ValueError("⚠️ ERRO CRÍTICO: A variável DATABASE_URL não foi configurada.")

    # Ajuste para o Neon
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'

    # Registro de Blueprints
    from app.client.routes import client_bp
    from app.auth.routes import auth_bp
    from app.admin.routes import admin_bp  # <--- Nova importação do Admin
    
    app.register_blueprint(client_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)       # <--- Novo registro do Admin

    return app

