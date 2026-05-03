from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import text
from app.models import Admin, Cliente, Fatura
from app import db

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    # Se já está logado, vai direto pro CRM
    if current_user.is_authenticated:
        return redirect(url_for('clientes.index'))

    if request.method == 'POST':
        username = request.form.get('username')
        senha = request.form.get('senha')
        
        # Busca o admin no banco
        admin = Admin.query.filter_by(username=username).first()

        if admin and check_password_hash(admin.password_hash, senha):
            login_user(admin)
            return redirect(url_for('clientes.index'))
        else:
            flash('Usuário ou senha inválidos.', 'error')
            
    return render_template('auth/login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))

# ============================================================
# ROTA DE RESET (CRIAÇÃO DO SEU USUÁRIO ADMIN)
# ============================================================
@auth_bp.route('/setup_secreto_dw')
def setup_secreto():
    try:
        # 1. Apaga tudo e recria as tabelas novas (Admin, Cliente, Fatura)
        db.session.execute(text('DROP SCHEMA public CASCADE; CREATE SCHEMA public;'))
        db.session.commit()
        db.create_all()
        
        # 2. Cria o seu acesso exclusivo
        admin = Admin(
            username='dwcapital',
            password_hash=generate_password_hash('dwadmin2026'),
            nome='Administrador DW'
        )
        db.session.add(admin)
        db.session.commit()
        
        return "<h1>✅ Mágica Feita! Banco reestruturado. Usuário: <b>dwcapital</b> | Senha: <b>dwadmin2026</b></h1>"
    except Exception as e:
        db.session.rollback()
        return f"<h1>❌ Erro no reset: {str(e)}</h1>"

