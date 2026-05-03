from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import text
from app.models import User
from app import db

# Definição do Blueprint de Autenticação
auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    # Se já estiver logado, redireciona direto para o painel correspondente
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            return redirect(url_for('admin.dashboard'))
        return redirect(url_for('client.dashboard'))

    if request.method == 'POST':
        cpf = request.form.get('cpf')
        senha = request.form.get('senha')

        # Busca o usuário pelo CPF (apenas números)
        user = User.query.filter_by(cpf=''.join(filter(str.isdigit, cpf))).first()

        # Validação de credenciais e status de acesso
        if user and user.password_hash and check_password_hash(user.password_hash, senha):
            if user.status_acesso == 'ativo':
                login_user(user)
                if user.role == 'admin':
                    return redirect(url_for('admin.dashboard'))
                return redirect(url_for('client.dashboard'))
            else:
                flash('Seu cadastro ainda não foi concluído. Vá em "Primeiro Acesso".')
        else:
            flash('CPF ou senha inválidos.')
            
    return render_template('auth/login.html')

@auth_bp.route('/primeiro_acesso', methods=['GET', 'POST'])
def primeiro_acesso():
    if request.method == 'POST':
        cpf = ''.join(filter(str.isdigit, request.form.get('cpf')))
        user = User.query.filter_by(cpf=cpf).first()

        # Verifica se o CPF foi previamente liberado pelo Administrador
        if user and user.status_acesso == 'pendente_cadastro':
            user.nome = request.form.get('nome')
            user.password_hash = generate_password_hash(request.form.get('senha'))
            user.corretora = request.form.get('corretora')
            user.capital_alocado = float(request.form.get('capital') or 0.0)
            user.perfil_risco = request.form.get('perfil')
            user.status_acesso = 'ativo'

            db.session.commit()
            flash('Cadastro concluído com sucesso! Agora você pode entrar no sistema.')
            return redirect(url_for('auth.login'))
        else:
            flash('CPF não autorizado para cadastro ou já ativo. Entre em contato com a DW Capital.')

    return render_template('auth/primeiro_acesso.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))

# ============================================================
# ROTA DE EMERGÊNCIA (DEVOPS) - RESET TOTAL DO BANCO NEON
# ============================================================
@auth_bp.route('/setup_secreto_dw')
def setup_secreto():
    """
    ATENÇÃO: Esta rota apaga TODA a estrutura do banco (CASCADE) 
    e recria o Admin padrão para resolver conflitos de schema.
    """
    try:
        # Limpeza profunda removendo dependências de tabelas antigas (Motorista Pro, etc)
        db.session.execute(text('DROP SCHEMA public CASCADE; CREATE SCHEMA public;'))
        db.session.commit()
        
        # Cria as tabelas da DW Capital conforme models.py
        db.create_all()
        
        # Injeta o usuário Administrador padrão
        # Senha: admin123
        admin = User(
            cpf='00000000000',
            password_hash='scrypt:32768:8:1$ADMqbAu5qrZBumoc$a1177a4cc34052ddab8054d60b8aaa4c9f5b0382e5ade634d918d062294be728cb98d35ec88714725ac98512211f2739f14d0a22183cdb7a5bea1265f280c87e',
            nome='Admin DW Capital',
            role='admin',
            status_acesso='ativo'
        )
        db.session.add(admin)
        db.session.commit()
        
        return "<h1>✅ Mágica Feita! Banco limpo e Admin DW Capital criado.</h1>"
    except Exception as e:
        db.session.rollback()
        return f"<h1>❌ Erro no reset: {str(e)}</h1>"

