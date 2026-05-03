from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from app.models import User
from app import db
from functools import wraps

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

# Trava de segurança: Verifica se o usuário logado é realmente um administrador
def admin_required(f):
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if current_user.role != 'admin':
            flash('Acesso negado. Área restrita para administradores da DW Capital.')
            return redirect(url_for('client.dashboard'))
        return f(*args, **kwargs)
    return decorated_function

@admin_bp.route('/')
@admin_required
def dashboard():
    # Busca todos os clientes (ignorando outros admins)
    clientes = User.query.filter_by(role='cliente').order_by(User.id.desc()).all()
    return render_template('admin/index.html', user=current_user, clientes=clientes)

@admin_bp.route('/liberar_cpf', methods=['POST'])
@admin_required
def liberar_cpf():
    cpf = request.form.get('cpf')
    
    # Remove qualquer ponto ou traço caso você digite formatado
    cpf = ''.join(filter(str.isdigit, cpf))
    
    if len(cpf) != 11:
        flash('CPF inválido. Digite 11 números.')
        return redirect(url_for('admin.dashboard'))

    # Verifica se já existe
    usuario_existente = User.query.filter_by(cpf=cpf).first()
    
    if usuario_existente:
        flash('Este CPF já está cadastrado ou já foi liberado anteriormente.')
    else:
        # Cria a liberação oca no banco
        novo_cliente = User(cpf=cpf, role='cliente', status_acesso='pendente_cadastro')
        db.session.add(novo_cliente)
        db.session.commit()
        flash('CPF liberado com sucesso! O cliente já pode realizar o Primeiro Acesso.')
        
    return redirect(url_for('admin.dashboard'))

