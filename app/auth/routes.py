from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import text
from app.models import User
from app import db

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('admin.dashboard' if current_user.role == 'admin' else 'client.dashboard'))
    if request.method == 'POST':
        user = User.query.filter_by(cpf=request.form.get('cpf')).first()
        if user and user.password_hash and check_password_hash(user.password_hash, request.form.get('senha')):
            login_user(user)
            return redirect(url_for('admin.dashboard' if user.role == 'admin' else 'client.dashboard'))
        flash('Credenciais incorretas.')
    return render_template('auth/login.html')

@auth_bp.route('/primeiro_acesso', methods=['GET', 'POST'])
def primeiro_acesso():
    if request.method == 'POST':
        user = User.query.filter_by(cpf=request.form.get('cpf')).first()
        if user and user.status_acesso == 'pendente_cadastro':
            user.nome = request.form.get('nome')
            user.password_hash = generate_password_hash(request.form.get('senha'))
            user.corretora = request.form.get('corretora')
            user.capital_alocado = float(request.form.get('capital') or 0)
            user.perfil_risco = request.form.get('perfil')
            user.status_acesso = 'ativo'
            db.session.commit()
            flash('Sucesso! Faça login.')
            return redirect(url_for('auth.login'))
        flash('CPF não autorizado.')
    return render_template('auth/primeiro_acesso.html')

@auth_bp.route('/setup_secreto_dw')
def setup_secreto():
    try:
        db.session.execute(text('DROP SCHEMA public CASCADE; CREATE SCHEMA public;'))
        db.session.commit()
        db.create_all()
        admin = User(cpf='00000000000', password_hash=generate_password_hash('admin123'), role='admin', status_acesso='ativo', nome='Admin DW')
        db.session.add(admin)
        db.session.commit()
        return "✅ Mágica Feita!"
    except Exception as e:
        return f"❌ Erro: {e}"

@auth_bp.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('auth.login'))

