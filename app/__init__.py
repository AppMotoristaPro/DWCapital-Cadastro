from flask import Flask, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
import os
from dotenv import load_dotenv

db = SQLAlchemy()
login_manager = LoginManager()

# NOVO FILTRO JINJA: Formatação Moeda Brasileira
def format_brl(value):
    if value is None:
        value = 0.0
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def create_app():
    app = Flask(__name__)
    load_dotenv()

    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dw-secret-prod-2026')
    
    database_url = os.getenv('DATABASE_URL')
    if database_url and database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
        
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # CORREÇÃO: Previne o erro "SSL connection has been closed unexpectedly" no Render
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'pool_pre_ping': True}

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    
    # Registra o filtro para usarmos no HTML
    app.jinja_env.filters['format_brl'] = format_brl

    from app.auth.routes import auth_bp
    from app.client.routes import client_bp
    from app.admin.routes import admin_bp
    
    app.register_blueprint(auth_bp)
    app.register_blueprint(client_bp, name='client')
    app.register_blueprint(admin_bp)

    @app.route('/')
    def root():
        return redirect(url_for('auth.login'))

    return app

