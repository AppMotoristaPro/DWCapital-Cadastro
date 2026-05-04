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
    nome_temp = request.form.get('nome_temp')
    
    if User.query.filter_by(cpf=cpf).first():
        flash('Este CPF já está cadastrado.', 'error')
        return redirect(url_for('admin.dashboard'))

    novo = User(cpf=cpf, nome=nome_temp, role='cliente', status_acesso='pendente_cadastro')
    db.session.add(novo)
    db.session.flush()
    
    # LÓGICA DO CICLO: Sexta a Quinta
    hoje = datetime.now().date()
    # Pega a última sexta-feira (ou hoje, se hoje for sexta)
    dias_para_sexta = (hoje.weekday() - 4) % 7
    inicio_ciclo = hoje - timedelta(days=dias_para_sexta)
    fim_ciclo = inicio_ciclo + timedelta(days=6) # Quinta-feira
    
    fatura = Fatura(user_id=novo.id, data_inicio=inicio_ciclo, data_fim=fim_ciclo)
    db.session.add(fatura)
    db.session.commit()
    flash('Acesso liberado e primeira semana de faturamento criada!', 'success')
    return redirect(url_for('admin.dashboard'))

@admin_bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_cliente(id):
    cliente = User.query.get_or_404(id)
    if request.method == 'POST':
        cliente.nome = request.form.get('nome')
        cliente.email = request.form.get('email')
        cliente.celular = request.form.get('celular')
        cliente.capital_alocado = float(request.form.get('capital') or 0.0)
        db.session.commit()
        flash('Dados atualizados.', 'success')
        return redirect(url_for('admin.dashboard'))
    return render_template('admin/editar.html', cliente=cliente)

@admin_bp.route('/status/<int:id>', methods=['POST'])
@login_required
def toggle_status(id):
    user = User.query.get_or_404(id)
    user.status_acesso = 'inativo' if user.status_acesso == 'ativo' else 'ativo'
    db.session.commit()
    flash(f'Status atualizado.', 'success')
    return redirect(url_for('admin.dashboard'))

@admin_bp.route('/excluir/<int:id>', methods=['POST'])
@login_required
def excluir_cliente(id):
    user = User.query.get_or_404(id)
    db.session.delete(user)
    db.session.commit()
    flash('Cliente removido.', 'success')
    return redirect(url_for('admin.dashboard'))

# ==========================================
# MÓDULO DE GESTÃO DE PAGAMENTOS
# ==========================================
@admin_bp.route('/pagamentos')
@login_required
def pagamentos():
    # Lista apenas clientes que finalizaram o cadastro e estão ativos
    ativos = User.query.filter_by(role='cliente', status_acesso='ativo').all()
    return render_template('admin/pagamentos.html', clientes=ativos)

@admin_bp.route('/pagamentos/<int:id>')
@login_required
def pagamentos_cliente(id):
    cliente = User.query.get_or_404(id)
    faturas = Fatura.query.filter_by(user_id=cliente.id).order_by(Fatura.data_inicio.desc()).all()
    return render_template('admin/pagamentos_cliente.html', cliente=cliente, faturas=faturas)

@admin_bp.route('/pagamentos/status/<int:fatura_id>', methods=['POST'])
@login_required
def status_pagamento(fatura_id):
    fatura = Fatura.query.get_or_404(fatura_id)
    fatura.status = request.form.get('status') # pago, inadimplente, etc
    db.session.commit()
    flash('Status da fatura atualizado.', 'success')
    return redirect(url_for('admin.pagamentos_cliente', id=fatura.user_id))

