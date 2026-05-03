from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
import os
from dotenv import load_dotenv

db = SQLAlchemy()
login_manager = LoginManager()

def create_app():
    app = Flask(__name__)
    load_dotenv()

    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dw-secret-2026')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL').replace("postgres://", "postgresql://", 1)
    
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'

    # IMPORTANTE: Registrando com os nomes corretos para o url_for funcionar
    from app.client.routes import client_bp
    from app.auth.routes import auth_bp
    from app.admin.routes import admin_bp
    
    app.register_blueprint(client_bp, name='client') # Força o nome 'client'
    app.register_blueprint(auth_bp, name='auth')
    app.register_blueprint(admin_bp, name='admin')

    return app

