import os
from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app, send_from_directory
from flask_login import login_required, current_user
from app.models import User, Fatura
from app import db
from datetime import datetime, timedelta

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

@admin_bp.route('/')
@login_required
def dashboard():
    if current_user.role != 'admin': return redirect(url_for('client.dashboard'))
    
    # Cálculos do Dashboard
    total_clientes = User.query.filter_by(role='cliente').count()
    ativos = User.query.filter_by(role='cliente', status_acesso='ativo').count()
    capital_total = db.session.query(db.func.sum(User.capital_alocado)).filter_by(role='cliente', status_acesso='ativo').scalar() or 0.0
    
    hoje = datetime.now().date()
    mes_passado = hoje - timedelta(days=30)
    semana_passada = hoje - timedelta(days=7)
    
    fat_total = db.session.query(db.func.sum(Fatura.repasse)).filter(Fatura.status != 'pendente').scalar() or 0.0
    fat_mes = db.session.query(db.func.sum(Fatura.repasse)).filter(Fatura.status != 'pendente', Fatura.data_inicio >= mes_passado).scalar() or 0.0
    fat_semana = db.session.query(db.func.sum(Fatura.repasse)).filter(Fatura.status != 'pendente', Fatura.data_inicio >= semana_passada).scalar() or 0.0
    
    media_cliente = (fat_total / ativos) if ativos > 0 else 0.0
    
    return render_template('admin/dashboard.html', 
                           total_clientes=total_clientes, ativos=ativos, 
                           capital_total=capital_total, fat_total=fat_total, 
                           fat_mes=fat_mes, fat_semana=fat_semana, media_cliente=media_cliente)

@admin_bp.route('/clientes')
@login_required
def clientes():
    if current_user.role != 'admin': return redirect(url_for('client.dashboard'))
    
    q = request.args.get('q', '')
    query = User.query.filter_by(role='cliente').order_by(User.id.desc())
    if q:
        query = query.filter(User.nome.ilike(f'%{q}%'))
        
    return render_template('admin/index.html', clientes=query.all(), q=q)

@admin_bp.route('/liberar_cliente', methods=['POST'])
@login_required
def liberar_cliente():
    cpf = ''.join(filter(str.isdigit, request.form.get('cpf')))
    nome_temp = request.form.get('nome_temp')
    
    if User.query.filter_by(cpf=cpf).first():
        flash('Este CPF já está cadastrado.', 'error')
        return redirect(url_for('admin.clientes'))

    novo = User(cpf=cpf, nome=nome_temp, role='cliente', status_acesso='pendente_cadastro')
    db.session.add(novo)
    db.session.flush()
    
    hoje = datetime.now().date()
    dias_para_sexta = (hoje.weekday() - 4) % 7
    inicio_ciclo = hoje - timedelta(days=dias_para_sexta)
    fim_ciclo = inicio_ciclo + timedelta(days=6)
    
    fatura = Fatura(user_id=novo.id, data_inicio=inicio_ciclo, data_fim=fim_ciclo)
    db.session.add(fatura)
    db.session.commit()
    flash('Acesso liberado e primeira semana de faturamento criada!', 'success')
    return redirect(url_for('admin.clientes'))

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
        return redirect(url_for('admin.clientes'))
    return render_template('admin/editar.html', cliente=cliente)

@admin_bp.route('/status/<int:id>', methods=['POST'])
@login_required
def toggle_status(id):
    user = User.query.get_or_404(id)
    user.status_acesso = 'inativo' if user.status_acesso == 'ativo' else 'ativo'
    db.session.commit()
    flash(f'Status atualizado.', 'success')
    return redirect(url_for('admin.clientes'))

@admin_bp.route('/excluir/<int:id>', methods=['POST'])
@login_required
def excluir_cliente(id):
    user = User.query.get_or_404(id)
    db.session.delete(user)
    db.session.commit()
    flash('Cliente removido.', 'success')
    return redirect(url_for('admin.clientes'))

@admin_bp.route('/pagamentos')
@login_required
def pagamentos():
    q = request.args.get('q', '')
    query = User.query.filter_by(role='cliente', status_acesso='ativo').order_by(User.nome)
    if q:
        query = query.filter(User.nome.ilike(f'%{q}%'))
    
    ativos = query.all()
    hoje = datetime.now().date()
    
    for cliente in ativos:
        # Busca a semana atual ou a última gerada
        fatura = Fatura.query.filter(Fatura.user_id == cliente.id, Fatura.data_inicio <= hoje, Fatura.data_fim >= hoje).first()
        if not fatura:
            fatura = Fatura.query.filter_by(user_id=cliente.id).order_by(Fatura.id.desc()).first()
        cliente.fatura_atual = fatura

    return render_template('admin/pagamentos.html', clientes=ativos, q=q)

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
    fatura.status = request.form.get('status')
    db.session.commit()
    flash('Status da fatura atualizado.', 'success')
    return redirect(url_for('admin.pagamentos_cliente', id=fatura.user_id))

@admin_bp.route('/ver_pdf/<int:fatura_id>')
@login_required
def ver_pdf(fatura_id):
    fatura = Fatura.query.get_or_404(fatura_id)
    if not fatura.arquivo_pdf:
        flash('Nenhum PDF anexado.', 'error')
        return redirect(url_for('admin.pagamentos_cliente', id=fatura.user_id))
    
    upload_dir = os.path.join(current_app.root_path, 'uploads')
    return send_from_directory(upload_dir, fatura.arquivo_pdf)

