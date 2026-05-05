import os
import random
import string
from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
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
    
    # ATUALIZAÇÃO: Captura de todos os filtros do formulário
    filtro_dia = request.args.get('dia')
    filtro_semana = request.args.get('semana')
    filtro_mes = request.args.get('mes')
    
    faturas_base = Fatura.query.filter(Fatura.status.in_(['parcial', 'completo', 'pago', 'inadimplente']))
    
    label_periodo = "Todo o Período"
    
    # Lógica Dinâmica de Filtros
    if filtro_dia:
        dt_dia = datetime.strptime(filtro_dia, '%Y-%m-%d').date()
        # Pega as faturas em que este dia está contido no ciclo
        faturas_filtradas = faturas_base.filter(Fatura.data_inicio <= dt_dia, Fatura.data_fim >= dt_dia).all()
        label_periodo = f"Dia {dt_dia.strftime('%d/%m/%Y')}"
        
    elif filtro_semana:
        # O HTML envia '2026-W18'. O '-1' no final indica a segunda-feira daquela semana
        dt_inicio_sem = datetime.strptime(filtro_semana + '-1', '%G-W%V-%u').date()
        dt_fim_sem = dt_inicio_sem + timedelta(days=6)
        faturas_filtradas = faturas_base.filter(Fatura.data_inicio >= dt_inicio_sem, Fatura.data_inicio <= dt_fim_sem).all()
        label_periodo = f"Semana {dt_inicio_sem.strftime('%d/%m')} a {dt_fim_sem.strftime('%d/%m')}"
        
    elif filtro_mes:
        dt_inicio_mes = datetime.strptime(filtro_mes + '-01', '%Y-%m-%d').date()
        # Descobre o último dia do mês
        if dt_inicio_mes.month == 12:
            dt_fim_mes = dt_inicio_mes.replace(year=dt_inicio_mes.year+1, month=1, day=1) - timedelta(days=1)
        else:
            dt_fim_mes = dt_inicio_mes.replace(month=dt_inicio_mes.month+1, day=1) - timedelta(days=1)
            
        faturas_filtradas = faturas_base.filter(Fatura.data_inicio >= dt_inicio_mes, Fatura.data_inicio <= dt_fim_mes).all()
        label_periodo = f"Mês {dt_inicio_mes.strftime('%m/%Y')}"
        
    else:
        faturas_filtradas = faturas_base.all()
        
    faturamento_total = sum(f.repasse for f in faturas_filtradas)
    
    clientes_ativos = User.query.filter_by(role='cliente', status_acesso='ativo').count()
    clientes_inativos = User.query.filter_by(role='cliente', status_acesso='inativo').count()
    
    alocado_row = db.session.query(db.func.sum(User.capital_alocado)).filter_by(role='cliente', status_acesso='ativo').first()
    capital_total = alocado_row[0] or 0.0
    
    qtd_faturas = len(faturas_filtradas)
    media_cliente = faturamento_total / qtd_faturas if qtd_faturas > 0 else 0.0
    
    return render_template('admin/dashboard.html', 
                           clientes_ativos=clientes_ativos,
                           clientes_inativos=clientes_inativos,
                           capital_total=capital_total,
                           faturamento_total=faturamento_total,
                           media_cliente=media_cliente,
                           label_periodo=label_periodo)

@admin_bp.route('/clientes')
@login_required
def clientes_list():
    if current_user.role != 'admin': return redirect(url_for('client.dashboard'))
    
    busca = request.args.get('q', '')
    status_filtro = request.args.get('status', '')
    
    query = User.query.filter_by(role='cliente')
    
    if busca:
        query = query.filter((User.nome.ilike(f'%{busca}%')) | (User.matricula.ilike(f'%{busca}%')))
    if status_filtro:
        query = query.filter_by(status_acesso=status_filtro)
        
    clientes = query.order_by(User.id.desc()).all()
    
    return render_template('admin/index.html', clientes=clientes, busca=busca, status_filtro=status_filtro)

@admin_bp.route('/liberar_cliente', methods=['POST'])
@login_required
def liberar_cliente():
    cpf = ''.join(filter(str.isdigit, request.form.get('cpf')))
    nome_temp = request.form.get('nome_temp')
    
    if User.query.filter_by(cpf=cpf).first():
        flash('CPF já cadastrado.', 'error')
        return redirect(url_for('admin.clientes_list'))

    novo = User(cpf=cpf, nome=nome_temp, role='cliente', status_acesso='pendente_cadastro')
    db.session.add(novo)
    db.session.flush()
    
    hoje = datetime.now(tz_br).date()
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
        cliente.capital_alocado = float(request.form.get('capital') or 0.0)
        db.session.commit()
        flash('Dados atualizados!', 'success')
        return redirect(url_for('admin.clientes_list'))
    return render_template('admin/editar.html', cliente=cliente)

@admin_bp.route('/inativar_cliente/<int:id>', methods=['POST'])
@login_required
def inativar_cliente(id):
    cliente = User.query.get_or_404(id)
    cliente.status_acesso = 'inativo'
    db.session.commit()
    flash(f'Cliente {cliente.nome} inativado com sucesso.', 'success')
    return redirect(url_for('admin.clientes_list'))

@admin_bp.route('/excluir_cliente/<int:id>', methods=['POST'])
@login_required
def excluir_cliente(id):
    cliente = User.query.get_or_404(id)
    db.session.delete(cliente)
    db.session.commit()
    flash('Cliente e todas as suas faturas foram excluídos permanentemente.', 'success')
    return redirect(url_for('admin.clientes_list'))

@admin_bp.route('/pagamentos')
@login_required
def pagamentos():
    if current_user.role != 'admin': return redirect(url_for('client.dashboard'))
    
    busca = request.args.get('q', '')
    query = User.query.filter_by(role='cliente', status_acesso='ativo')
    if busca:
        query = query.filter((User.nome.ilike(f'%{busca}%')) | (User.matricula.ilike(f'%{busca}%')))
    ativos = query.all()
    
    hoje = datetime.now(tz_br).date()
    dias_para_sexta = (hoje.weekday() - 4) % 7
    inicio_ciclo = hoje - timedelta(days=dias_para_sexta)
    
    clientes_dados = []
    for c in ativos:
        fatura_atual = Fatura.query.filter_by(user_id=c.id, data_inicio=inicio_ciclo).first()
        status_atual = fatura_atual.status if fatura_atual else 'sem_fatura'
        clientes_dados.append({
            'info': c, 
            'status_semana': status_atual, 
            'inicio_ciclo': inicio_ciclo
        })
        
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
    dia = FaturaDiaria.query.get_or_404(dia_id)
    
    dia.arquivo_pdf = None
    dia.status = 'pendente'
    dia.bruto = 0.0
    dia.taxas_b3 = 0.0
    dia.irrf_1 = 0.0
    dia.liquido_pregao = 0.0
    dia.irrf_19 = 0.0
    dia.liquido = 0.0
    dia.repasse = 0.0
    
    fatura = dia.fatura_semanal
    fatura.bruto = sum(d.bruto for d in fatura.dias if d.status == 'relatorio_enviado')
    fatura.taxas_b3 = sum(d.taxas_b3 for d in fatura.dias if d.status == 'relatorio_enviado')
    fatura.irrf_1 = sum(d.irrf_1 for d in fatura.dias if d.status == 'relatorio_enviado')
    fatura.liquido_pregao = sum(d.liquido_pregao for d in fatura.dias if d.status == 'relatorio_enviado')
    fatura.irrf_19 = sum(d.irrf_19 for d in fatura.dias if d.status == 'relatorio_enviado')
    fatura.liquido = sum(d.liquido for d in fatura.dias if d.status == 'relatorio_enviado')
    fatura.repasse = sum(d.repasse for d in fatura.dias if d.status == 'relatorio_enviado')
    
    dias_enviados = sum(1 for d in fatura.dias if d.status == 'relatorio_enviado')
    if dias_enviados == 0:
        fatura.status = 'pendente'
    elif dias_enviados == 5:
        fatura.status = 'completo'
    else:
        fatura.status = 'parcial'
        
    db.session.commit()
    flash('Relatório rejeitado e valores recalculados.', 'success')
    return redirect(url_for('admin.pagamentos_cliente', id=fatura.user_id))

@admin_bp.route('/pagamentos/forcar_limpeza/<int:dia_id>', methods=['POST'])
@login_required
def forcar_limpeza_dia(dia_id):
    dia = FaturaDiaria.query.get_or_404(dia_id)
    
    dia.arquivo_pdf = None
    dia.status = 'pendente'
    dia.bruto = 0.0
    dia.taxas_b3 = 0.0
    dia.irrf_1 = 0.0
    dia.liquido_pregao = 0.0
    dia.irrf_19 = 0.0
    dia.liquido = 0.0
    dia.repasse = 0.0
    
    fatura = dia.fatura_semanal
    fatura.bruto = sum(d.bruto for d in fatura.dias if d.status == 'relatorio_enviado')
    fatura.taxas_b3 = sum(d.taxas_b3 for d in fatura.dias if d.status == 'relatorio_enviado')
    fatura.irrf_1 = sum(d.irrf_1 for d in fatura.dias if d.status == 'relatorio_enviado')
    fatura.liquido_pregao = sum(d.liquido_pregao for d in fatura.dias if d.status == 'relatorio_enviado')
    fatura.irrf_19 = sum(d.irrf_19 for d in fatura.dias if d.status == 'relatorio_enviado')
    fatura.liquido = sum(d.liquido for d in fatura.dias if d.status == 'relatorio_enviado')
    fatura.repasse = sum(d.repasse for d in fatura.dias if d.status == 'relatorio_enviado')
    
    dias_enviados = sum(1 for d in fatura.dias if d.status == 'relatorio_enviado')
    if dias_enviados == 0:
        fatura.status = 'pendente'
    elif dias_enviados == 5:
        fatura.status = 'completo'
    else:
        fatura.status = 'parcial'
        
    db.session.commit()
    flash('Limpeza forçada! Todos os valores fantasmas deste dia foram zerados.', 'success')
    return redirect(url_for('admin.pagamentos_cliente', id=fatura.user_id))

@admin_bp.route('/gerar_senha_temporaria/<int:id>', methods=['POST'])
@login_required
def gerar_senha_temporaria(id):
    cliente = User.query.get_or_404(id)
    senha_temp = "DW@" + ''.join(random.choices(string.ascii_letters + string.digits, k=5))
    cliente.password_hash = generate_password_hash(senha_temp)
    cliente.precisa_trocar_senha = True
    db.session.commit()
    flash(f'Senha gerada para {cliente.nome}: {senha_temp}', 'success')
    return redirect(url_for('admin.editar_cliente', id=cliente.id))

