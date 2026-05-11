from flask import Flask, redirect, url_for, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import os
from dotenv import load_dotenv
import cloudinary
import cloudinary.uploader
from app.utils.filters import format_brl, to_tz_br
from app.cli import register_cli_commands

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address)

def create_app():
    app = Flask(__name__)
    load_dotenv()
    
    secret_key = os.getenv('SECRET_KEY')
    if not secret_key:
        raise ValueError("VAZAMENTO EVITADO: A SECRET_KEY não está configurada no ambiente. O sistema foi bloqueado por segurança.")
    app.config['SECRET_KEY'] = secret_key
    
    database_url = os.getenv('DATABASE_URL')
    if database_url and database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
        
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'pool_pre_ping': True}

    cloudinary.config(
        cloud_name = os.getenv('CLOUDINARY_CLOUD_NAME'),
        api_key = os.getenv('CLOUDINARY_API_KEY'),
        api_secret = os.getenv('CLOUDINARY_API_SECRET'),
        secure = True
    )

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)
    
    login_manager.login_view = 'auth.login'
    
    # REGISTRO DOS FILTROS NO JINJA (Puxados do novo ficheiro)
    app.jinja_env.filters['format_brl'] = format_brl
    app.jinja_env.filters['to_tz_br'] = to_tz_br

    # REGISTRO DOS COMANDOS DE TERMINAL
    register_cli_commands(app)

    from app.auth.routes import auth_bp
    from app.client.routes import client_bp
    from app.admin.routes import admin_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(client_bp, name='client')
    app.register_blueprint(admin_bp)

    @app.route('/')
    def root(): return redirect(url_for('auth.login'))

    # ==========================================
    # CAPTURA DE ERROS (ERROR HANDLERS)
    # ==========================================
    @app.errorhandler(404)
    def page_not_found(e):
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def internal_server_error(e):
        return render_template('errors/500.html'), 500

    @app.errorhandler(403)
    def forbidden_error(e):
        return render_template('errors/403.html'), 403

    @app.errorhandler(413)
    def request_entity_too_large(e):
        return render_template('errors/413.html'), 413

    @app.errorhandler(405)
    def method_not_allowed(e):
        return render_template('errors/405.html'), 405

    @app.errorhandler(429)
    def ratelimit_handler(e):
        return "Calma aí! Você excedeu o limite de acessos. Tente novamente em alguns instantes.", 429

    return app

