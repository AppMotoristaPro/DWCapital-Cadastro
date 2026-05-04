from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from app.models import User, Fatura
from app import db
from datetime import datetime, timedelta

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

@admin_bp.route('/')
@login_required
def dashboard():
    if current_user.role != 'admin': return redirect(url_for('client.dashboard'))
    clientes = User.query.filter_by(role='cliente').order_by(User.id.desc()).all()
    return render_template('admin/index.html', clientes=clientes)

@admin_bp.route('/liberar_cliente', methods=['POST'])
@login_required
def liberar_cliente():
    cpf = ''.join(filter(str.isdigit, request.form.get('cpf')))
    nome_temp = request.form.get('nome_temp') # Nome para controle interno
    
    if User.query.filter_by(cpf=cpf).first():
        flash('Este CPF já está cadastrado ou liberado.', 'error')
        return redirect(url_for('admin.dashboard'))

    novo = User(
        cpf=cpf, 
        nome=nome_temp,
        role='cliente',
        status_acesso='pendente_cadastro'
    )
    db.session.add(novo)
    db.session.commit()
    flash(f'CPF {cpf} ({nome_temp}) liberado com sucesso!', 'success')
    return redirect(url_for('admin.dashboard'))

@admin_bp.route('/status/<int:id>', methods=['POST'])
@login_required
def toggle_status(id):
    user = User.query.get_or_404(id)
    user.status_acesso = 'inativo' if user.status_acesso == 'ativo' else 'ativo'
    db.session.commit()
    flash(f'Status de {user.nome} alterado para {user.status_acesso.upper()}.', 'success')
    return redirect(url_for('admin.dashboard'))

@admin_bp.route('/excluir/<int:id>', methods=['POST'])
@login_required
def excluir_cliente(id):
    user = User.query.get_or_404(id)
    db.session.delete(user)
    db.session.commit()
    flash('Cliente removido permanentemente.', 'success')
    return redirect(url_for('admin.dashboard'))

