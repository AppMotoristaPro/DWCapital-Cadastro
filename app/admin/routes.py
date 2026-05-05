import os
from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app
from flask_login import login_required, current_user
from app.models import User, Fatura, FaturaDiaria
from app import db
from datetime import datetime, timedelta
import pytz

tz_br = pytz.timezone('America/Sao_Paulo')
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

@admin_bp.route('/')
@login_required
def dashboard():
    if current_user.role != 'admin': return redirect(url_for('client.dashboard'))
    
    filtro_dia = request.args.get('dia')
    filtro_semana = request.args.get('semana')
    filtro_mes = request.args.get('mes')
    
    faturas_base = Fatura.query.filter(Fatura.status.in_(['parcial', 'relatorio_enviado', 'pago', 'inadimplente']))
    faturas_diarias_base = FaturaDiaria.query.filter(FaturaDiaria.status == 'relatorio_enviado')
    
    label_periodo = "Todo o Período"
    
    if filtro_dia:
        dt = datetime.strptime(filtro_dia, '%Y-%m-%d').date()
        faturas_filtradas = faturas_diarias_base.filter(FaturaDiaria.data_pregao == dt).all()
        faturamento_total = sum(f.repasse for f in faturas_filtradas)
        qtd = len(faturas_filtradas)
        label_periodo = f"Dia {dt.strftime('%d/%m/%Y')}"
    elif filtro_semana:
        dt_inicio = datetime.strptime(filtro_semana + '-1', '%G-W%V-%u').date()
        dt_fim = dt_inicio + timedelta(days=6)
        faturas_filtradas = faturas_base.filter(Fatura.data_inicio >= dt_inicio, Fatura.data_inicio <= dt_fim).all()
        faturamento_total = sum(f.repasse for f in faturas_filtradas)
        qtd = len(faturas_filtradas)
        label_periodo = f"Semana de {dt_inicio.strftime('%d/%m')}"
    elif filtro_mes:
        dt_inicio = datetime.strptime(filtro_mes + '-01', '%Y-%m-%d').date()
        prox_mes = dt_inicio.replace(day=28) + timedelta(days=4)
        dt_fim = prox_mes - timedelta(days=prox_mes.day)
        faturas_filtradas = faturas_base.filter(Fatura.data_inicio >= dt_inicio, Fatura.data_inicio <= dt_fim).all()
        faturamento_total = sum(f.repasse for f in faturas_filtradas)
        qtd = len(faturas_filtradas)
        label_periodo = f"Mês {dt_inicio.strftime('%m/%Y')}"
    else:
        hoje = datetime.now(tz_br).date()
        dt_inicio = hoje.replace(day=1)
        faturas_filtradas = faturas_base.filter(Fatura.data_inicio >= dt_inicio).all()
        faturamento_total = sum(f.repasse for f in faturas_filtradas)
        qtd = len(faturas_filtradas)
        label_periodo = f"Mês Atual ({dt_inicio.strftime('%m/%Y')})"
        
    clientes_ativos = User.query.filter_by(role='cliente', status_acesso='ativo').count()
    total_clientes = User.query.filter_by(role='cliente').count()
    alocado_row = db.session.query(db.func.sum(User.capital_alocado)).filter_by(role='cliente', status_acesso='ativo').first()
    capital_total = alocado_row[0] or 0.0
    media_cliente = faturamento_total / qtd if qtd > 0 else 0.0
    
    return render_template('admin/dashboard.html', 
                           clientes_ativos=clientes_ativos,
                           total_clientes=total_clientes,
                           capital_total=capital_total,
                           faturamento_total=faturamento_total,
                           media_cliente=media_cliente,
                           label_periodo=label_periodo)

@admin_bp.route('/clientes')
@login_required
def clientes_list():
    if current_user.role != 'admin': return redirect(url_for('client.dashboard'))
    busca = request.args.get('q', '')
    query = User.query.filter_by(role='cliente')
    if busca:
        query = query.filter((User.nome.ilike(f'%{busca}%')) | (User.matricula.ilike(f'%{busca}%')))
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
    db.session.flush()
    
    for i in range(7):
        data_atual = inicio_ciclo + timedelta(days=i)
        if data_atual.weekday() < 5: 
            fd = FaturaDiaria(fatura_id=fatura.id, data_pregao=data_atual)
            db.session.add(fd)

    db.session.commit()
    flash('Acesso liberado e ciclos gerados!', 'success')
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
        
        nova_data_str = request.form.get('data_cadastro')
        if nova_data_str:
            try:
                dt = datetime.strptime(nova_data_str, '%Y-%m-%dT%H:%M')
                cliente.data_cadastro = tz_br.localize(dt)
            except ValueError:
                pass 

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
        query = query.filter((User.nome.ilike(f'%{busca}%')) | (User.matricula.ilike(f'%{busca}%')))
    ativos = query.all()
    
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

@admin_bp.route('/pagamentos/rejeitar/<int:dia_id>', methods=['POST'])
@login_required
def rejeitar_relatorio(dia_id):
    """Rota para o admin rejeitar o PDF e forçar o cliente a reenviar."""
    dia = FaturaDiaria.query.get_or_404(dia_id)
    
    if dia.arquivo_pdf:
        file_path = os.path.join(current_app.root_path, 'static', 'uploads', dia.arquivo_pdf)
        if os.path.exists(file_path):
            os.remove(file_path)
            
    # Limpa os dados do dia
    dia.arquivo_pdf = None
    dia.bruto = 0.0
    dia.liquido = 0.0
    dia.irrf_1 = 0.0
    dia.taxas_b3 = 0.0
    dia.repasse = 0.0
    dia.status = 'pendente'
    
    # Se a fatura semanal estava como 'relatorio_enviado', ela volta para parcial ou pendente
    if dia.fatura_semanal.status in ['relatorio_enviado', 'pago', 'inadimplente']:
        dia.fatura_semanal.status = 'parcial'
        
    db.session.commit()
    
    flash('O relatório foi rejeitado e o status devolvido ao cliente como Pendente.', 'success')
    return redirect(url_for('admin.pagamentos_cliente', id=dia.fatura_semanal.user_id))

