from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from app.models import User
from app import db

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    # Se o usuário já estiver logado, redireciona para o dashboard
    if current_user.is_authenticated:
        return redirect(url_for('client.dashboard'))

    if request.method == 'POST':
        cpf = request.form.get('cpf')
        senha = request.form.get('senha')

        user = User.query.filter_by(cpf=cpf).first()

        # Verifica se o usuário existe, tem senha e se a senha está correta
        if user and user.password_hash and check_password_hash(user.password_hash, senha):
            login_user(user)
            return redirect(url_for('client.dashboard'))
        else:
            flash('CPF ou senha inválidos, ou cadastro pendente.')
            
    return render_template('auth/login.html')

@auth_bp.route('/primeiro_acesso', methods=['GET', 'POST'])
def primeiro_acesso():
    if request.method == 'POST':
        cpf = request.form.get('cpf')
        user = User.query.filter_by(cpf=cpf).first()

        # Verifica se o CPF foi liberado pelo admin e se ainda está pendente
        if user and user.status_acesso == 'pendente_cadastro':
            senha = request.form.get('senha')
            nome = request.form.get('nome')
            corretora = request.form.get('corretora')
            capital = request.form.get('capital')
            perfil = request.form.get('perfil')

            # Atualiza os dados do cliente
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

