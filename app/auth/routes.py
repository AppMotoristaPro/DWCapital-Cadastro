from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import text
from app.models import User
from app import db

# Criação do Blueprint
auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('admin.dashboard' if current_user.role == 'admin' else 'client.dashboard'))

    if request.method == 'POST':
        identificador = request.form.get('login') # Pode ser CPF ou Username
        senha = request.form.get('senha')
        
        # Busca por CPF (limpo) ou por Username
        user = User.query.filter((User.cpf == identificador) | (User.username == identificador)).first()

        if user and check_password_hash(user.password_hash, senha):
            if user.status_acesso == 'ativo':
                login_user(user)
                return redirect(url_for('admin.dashboard' if user.role == 'admin' else 'client.dashboard'))
            flash('Cadastro pendente. Vá em Primeiro Acesso.')
        else:
            flash('Credenciais inválidas.')
            
    return render_template('auth/login.html')

# ==========================================
# ROTA API: Validação Silenciosa do CPF
# ==========================================
@auth_bp.route('/api/verificar_cpf', methods=['POST'])
def verificar_cpf():
    data = request.get_json()
    if not data or 'cpf' not in data:
        return jsonify({'valido': False, 'mensagem': 'CPF não informado.'}), 400

    cpf_limpo = ''.join(filter(str.isdigit, data['cpf']))
    user = User.query.filter_by(cpf=cpf_limpo).first()

    if not user:
        return jsonify({'valido': False, 'mensagem': 'CPF não liberado. Entre em contato com a DW Capital.'})
    
    if user.status_acesso != 'pendente_cadastro':
        return jsonify({'valido': False, 'mensagem': 'Este CPF já possui uma senha ativa.'})

    return jsonify({'valido': True, 'mensagem': 'CPF liberado!'})


@auth_bp.route('/primeiro_acesso', methods=['GET', 'POST'])
def primeiro_acesso():
    if request.method == 'POST':
        cpf = ''.join(filter(str.isdigit, request.form.get('cpf')))
        user = User.query.filter_by(cpf=cpf, status_acesso='pendente_cadastro').first()

        if user:
            # Recebe todas as informações do fluxo multi-passo (App de Banco)
            user.nome = request.form.get('nome')
            user.email = request.form.get('email')
            user.celular = request.form.get('celular')
            user.endereco = request.form.get('endereco')
            user.corretora = request.form.get('corretora')
            user.capital_alocado = float(request.form.get('capital') or 0.0)
            user.password_hash = generate_password_hash(request.form.get('senha'))
            user.status_acesso = 'ativo'
            
            db.session.commit()
            flash('Cadastro concluído com sucesso! Bem-vindo à DW Capital.', 'success')
            return redirect(url_for('auth.login'))
        
        flash('CPF não liberado ou cadastro já ativo.', 'error')

    return render_template('auth/primeiro_acesso.html')

@auth_bp.route('/setup_secreto_dw')
def setup_secreto():
    try:
        db.session.execute(text('DROP SCHEMA public CASCADE; CREATE SCHEMA public;'))
        db.session.commit()
        db.create_all()
        admin = User(username='dwcapital', password_hash=generate_password_hash('dwadmin2026'), role='admin', status_acesso='ativo', nome='Admin DW')
        db.session.add(admin)
        db.session.commit()
        return "✅ Sistema Resetado para Modelo Híbrido (Admin + Cliente)!"
    except Exception as e:
        return f"❌ Erro: {e}"

@auth_bp.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('auth.login'))

