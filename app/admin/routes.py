from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from app.models import User, Fatura
from app import db
from datetime import datetime, timedelta
import pytz

tz_br = pytz.timezone('America/Sao_Paulo')
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

@admin_bp.route('/')
@login_required
def dashboard():
    if current_user.role != 'admin': return redirect(url_for('client.dashboard'))
    
    periodo = request.args.get('periodo', 'mes')
    hoje = datetime.now(tz_br).date()
    
    if periodo == 'dia':
        data_inicio = hoje
    elif periodo == 'semana':
        data_inicio = hoje - timedelta(days=hoje.weekday()) # Segunda da semana atual
    else: # mes
        data_inicio = hoje.replace(day=1)
        
    clientes_ativos = User.query.filter_by(role='cliente', status_acesso='ativo').count()
    total_clientes = User.query.filter_by(role='cliente').count()
    
    # Soma de valor alocado
    alocado_row = db.session.query(db.func.sum(User.capital_alocado)).filter_by(role='cliente', status_acesso='ativo').first()
    capital_total = alocado_row[0] or 0.0
    
    # Faturamentos do período
    faturas = Fatura.query.filter(Fatura.data_inicio >= data_inicio).all()
    # Apenas faturas com repasse calculado (não pendentes vazias)
    faturas_validas = [f for f in faturas if f.status in ['relatorio_enviado', 'pago', 'inadimplente']]
    
    faturamento_total = sum(f.repasse for f in faturas_validas)
    qtd_faturas = len(faturas_validas)
    media_cliente = faturamento_total / qtd_faturas if qtd_faturas > 0 else 0.0
    
    return render_template('admin/dashboard.html', 
                           clientes_ativos=clientes_ativos,
                           total_clientes=total_clientes,
                           capital_total=capital_total,
                           faturamento_total=faturamento_total,
                           media_cliente=media_cliente,
                           periodo=periodo)

@admin_bp.route('/clientes')
@login_required
def clientes_list():
    if current_user.role != 'admin': return redirect(url_for('client.dashboard'))
    busca = request.args.get('q', '')
    query = User.query.filter_by(role='cliente')
    if busca:
        query = query.filter(User.nome.ilike(f'%{busca}%'))
    clientes = query.order_by(User.id.desc()).all()
    return render_template('admin/index.html', clientes=clientes, busca=busca)

@admin_bp.route('/liberar_cliente', methods=['POST'])
@login_required
def liberar_cliente():
    cpf = ''.join(filter(str.isdigit, request.form.get('cpf')))
    nome_temp = request.form.get('nome_temp')
    
    if User.query.filter_by(cpf=cpf).first():
        flash('Este CPF já está cadastrado.', 'error')
        return redirect(url_for('admin.clientes_list'))

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
    flash('Acesso liberado e primeira semana criada!', 'success')
    return redirect(url_for('admin.clientes_list'))

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
        return redirect(url_for('admin.clientes_list'))
    return render_template('admin/editar.html', cliente=cliente)

@admin_bp.route('/status/<int:id>', methods=['POST'])
@login_required
def toggle_status(id):
    user = User.query.get_or_404(id)
    user.status_acesso = 'inativo' if user.status_acesso == 'ativo' else 'ativo'
    db.session.commit()
    flash(f'Status atualizado.', 'success')
    return redirect(url_for('admin.clientes_list'))

@admin_bp.route('/excluir/<int:id>', methods=['POST'])
@login_required
def excluir_cliente(id):
    user = User.query.get_or_404(id)
    db.session.delete(user)
    db.session.commit()
    flash('Cliente removido.', 'success')
    return redirect(url_for('admin.clientes_list'))

@admin_bp.route('/pagamentos')
@login_required
def pagamentos():
    busca = request.args.get('q', '')
    query = User.query.filter_by(role='cliente', status_acesso='ativo')
    if busca:
        query = query.filter(User.nome.ilike(f'%{busca}%'))
    ativos = query.all()
    
    # Busca status da semana atual para exibir na lista diretamente
    hoje = datetime.now().date()
    dias_para_sexta = (hoje.weekday() - 4) % 7
    inicio_ciclo = hoje - timedelta(days=dias_para_sexta)
    
    clientes_dados = []
    for c in ativos:
        fatura_atual = Fatura.query.filter_by(user_id=c.id, data_inicio=inicio_ciclo).first()
        status_atual = fatura_atual.status if fatura_atual else 'sem_fatura'
        clientes_dados.append({'info': c, 'status_semana': status_atual, 'inicio_ciclo': inicio_ciclo})
        
    return render_template('admin/pagamentos.html', clientes=clientes_dados, busca=busca)

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

