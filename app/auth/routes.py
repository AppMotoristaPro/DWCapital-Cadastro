from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import text  # <--- Nova importação para comandos SQL brutos
from app.models import User
from app import db

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            return redirect(url_for('admin.dashboard'))
        return redirect(url_for('client.dashboard'))

    if request.method == 'POST':
        cpf = request.form.get('cpf')
        senha = request.form.get('senha')

        user = User.query.filter_by(cpf=cpf).first()

        if user and user.password_hash and check_password_hash(user.password_hash, senha):
            login_user(user)
            if user.role == 'admin':
                return redirect(url_for('admin.dashboard'))
            return redirect(url_for('client.dashboard'))
        else:
            flash('CPF ou senha inválidos, ou cadastro pendente.')
            
    return render_template('auth/login.html')

@auth_bp.route('/primeiro_acesso', methods=['GET', 'POST'])
def primeiro_acesso():
    if request.method == 'POST':
        cpf = request.form.get('cpf')
        user = User.query.filter_by(cpf=cpf).first()

        if user and user.status_acesso == 'pendente_cadastro':
            senha = request.form.get('senha')
            nome = request.form.get('nome')
            corretora = request.form.get('corretora')
            capital = request.form.get('capital')
            perfil = request.form.get('perfil')

            user.nome = nome
            user.password_hash = generate_password_hash(senha)
            user.corretora = corretora
            user.capital_alocado = float(capital) if capital else 0.0
            user.perfil_risco = perfil
            user.status_acesso = 'ativo'

            db.session.commit()
            flash('Cadastro concluído com sucesso! Faça seu login.')
            return redirect(url_for('auth.login'))
        else:
            flash('CPF não liberado, não encontrado ou já cadastrado.')

    return render_template('auth/primeiro_acesso.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))

# ==========================================
# ROTA SECRETA DE EMERGÊNCIA (DEVOPS)
# ==========================================
@auth_bp.route('/setup_secreto_dw')
def setup_secreto():
    try:
        # 1. Limpeza Profunda: Apaga o schema inteiro com CASCADE (trazendo junto tabelas antigas) e recria
        db.session.execute(text('DROP SCHEMA public CASCADE; CREATE SCHEMA public;'))
        db.session.commit()
        
        # 2. Cria apenas as tabelas da DW Capital
        db.create_all()
        
        # 3. Cria o usuário Admin
        admin = User(
            cpf='00000000000',
            password_hash=generate_password_hash('admin123'),
            nome='Admin DW Capital',
            role='admin',
            status_acesso='ativo'
        )
        db.session.add(admin)
        db.session.commit()
        
        return "<h1>✅ Mágica Feita! Banco limpo com CASCADE e Admin injetado com sucesso. Volte para a tela inicial e faça seu login.</h1>"
    except Exception as e:
        db.session.rollback() # Previne travamento do banco em caso de erro
        return f"<h1>❌ Erro ao resetar o banco: {str(e)}</h1>"

