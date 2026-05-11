import os
import random
import string
from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from sqlalchemy.exc import IntegrityError
from app.models import User, Fatura, FaturaDiaria, AlocacaoCorretora, LogAuditoria, DocumentoTemplate, DocumentoCliente
from app import db
from datetime import datetime, timedelta
from app.utils.autentique import enviar_documento_local_com_link, verificar_status_autentique
import pytz

tz_br = pytz.timezone('America/Sao_Paulo')
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

def registrar_log(acao, categoria):
    if current_user.is_authenticated:
        novo_log = LogAuditoria(
            admin_id=current_user.id,
            admin_nome=current_user.nome,
            acao_detalhada=acao,
            categoria=categoria
        )
        db.session.add(novo_log)

def atualizar_totais_semana_admin(fatura):
    fatura.bruto = sum((d.bruto if d.bruto > 0 else 0.0) for d in fatura.dias if d.status == 'relatorio_enviado')
    fatura.taxas_b3 = sum((d.taxas_b3 if d.taxas_b3 > 0 else 0.0) for d in fatura.dias if d.status == 'relatorio_enviado')
    fatura.irrf_1 = sum((d.irrf_1 if d.irrf_1 > 0 else 0.0) for d in fatura.dias if d.status == 'relatorio_enviado')
    fatura.liquido_pregao = sum((d.liquido_pregao if d.liquido_pregao > 0 else 0.0) for d in fatura.dias if d.status == 'relatorio_enviado')
    fatura.irrf_19 = sum((d.irrf_19 if d.irrf_19 > 0 else 0.0) for d in fatura.dias if d.status == 'relatorio_enviado')
    fatura.liquido = sum((d.liquido if d.liquido > 0 else 0.0) for d in fatura.dias if d.status == 'relatorio_enviado')
    fatura.repasse = sum((d.repasse if d.repasse > 0 else 0.0) for d in fatura.dias if d.status == 'relatorio_enviado')
    
    dias_enviados = sum(1 for d in fatura.dias if d.status == 'relatorio_enviado')
    dias_isentos = sum(1 for d in fatura.dias if d.status == 'isento')
    total_exigido = len(fatura.dias) - dias_isentos
    
    if dias_enviados == 0:
        if total_exigido == 0 and len(fatura.dias) > 0:
            fatura.status = 'completo'
        else:
            fatura.status = 'pendente'
    elif dias_enviados >= total_exigido and total_exigido > 0:
        fatura.status = 'completo'
    else:
        fatura.status = 'parcial'
        
    db.session.commit()

def auto_gerar_ciclo_admin(user, data_base=None):
    if not user.alocacoes:
        return

    hoje = data_base if data_base else datetime.now(tz_br).date()
    dias_para_sexta = (hoje.weekday() - 4) % 7
    inicio_ciclo = hoje - timedelta(days=dias_para_sexta)
    fim_ciclo = inicio_ciclo + timedelta(days=6)

    fatura_existente = Fatura.query.filter_by(user_id=user.id, data_inicio=inicio_ciclo).first()

    if not fatura_existente:
        nova_fatura = Fatura(
            user_id=user.id,
            data_inicio=inicio_ciclo,
            data_fim=fim_ciclo,
            status='pendente'
        )
        db.session.add(nova_fatura)
        
        try:
            db.session.commit()
            fatura_existente = nova_fatura
        except IntegrityError:
            db.session.rollback()
            fatura_existente = Fatura.query.filter_by(user_id=user.id, data_inicio=inicio_ciclo).first()
            if not fatura_existente:
                return

    if fatura_existente:
        dias_uteis = []
        data_atual = inicio_ciclo
        while len(dias_uteis) < 5 and data_atual <= fim_ciclo:
            if data_atual.weekday() < 5:
                dias_uteis.append(data_atual)
            data_atual += timedelta(days=1)

        for data in dias_uteis:
            for alocacao in user.alocacoes:
                existe = FaturaDiaria.query.filter_by(fatura_id=fatura_existente.id, data_pregao=data, nome_corretora=alocacao.nome_corretora).first()
                if not existe:
                    novo_dia = FaturaDiaria(
                        fatura_id=fatura_existente.id,
                        data_pregao=data,
                        nome_corretora=alocacao.nome_corretora,
                        status='pendente'
                    )
                    db.session.add(novo_dia)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()

@admin_bp.route('/')
@login_required
def dashboard():
    if current_user.role != 'admin': return redirect(url_for('client.dashboard'))
    
    filtro_dia = request.args.get('dia')
    filtro_semana_dia = request.args.get('semana_dia') 
    filtro_ano = request.args.get('ano') 
    
    faturas_base = Fatura.query.join(User).filter(
        Fatura.status.in_(['parcial', 'completo', 'pago', 'inadimplente']),
        db.or_(User.is_isento == False, User.is_isento.is_(None))
    )
    
    label_periodo = "Todo o Período"
    
    if filtro_dia:
        dt_dia = datetime.strptime(filtro_dia, '%Y-%m-%d').date()
        faturas_filtradas = faturas_base.filter(Fatura.data_inicio <= dt_dia, Fatura.data_fim >= dt_dia).all()
        label_periodo = f"Dia {dt_dia.strftime('%d/%m/%Y')}"
        
    elif filtro_semana_dia:
        dt_ref = datetime.strptime(filtro_semana_dia, '%Y-%m-%d').date()
        dias_para_sexta = (dt_ref.weekday() - 4) % 7
        dt_inicio_sem = dt_ref - timedelta(days=dias_para_sexta)
        dt_fim_sem = dt_inicio_sem + timedelta(days=6)
        
        faturas_filtradas = faturas_base.filter(Fatura.data_inicio >= dt_inicio_sem, Fatura.data_inicio <= dt_fim_sem).all()
        label_periodo = f"Ciclo {dt_inicio_sem.strftime('%d/%m/%Y')} a {dt_fim_sem.strftime('%d/%m/%Y')}"
        
    elif filtro_ano:
        ano = int(filtro_ano)
        dt_inicio_ano = datetime(ano, 1, 1).date()
        dt_fim_ano = datetime(ano, 12, 31).date()
        faturas_filtradas = faturas_base.filter(Fatura.data_inicio >= dt_inicio_ano, Fatura.data_inicio <= dt_fim_ano).all()
        label_periodo = f"Ano {ano}"
        
    else:
        faturas_filtradas = faturas_base.all()
        
    faturamento_total = sum(f.repasse for f in faturas_filtradas)
    faturamento_bruto_total = sum(f.bruto for f in faturas_filtradas)
    
    dados_grafico_raw = {}
    rois_clientes = {}

    for f in faturas_filtradas:
        capital_cliente = f.cliente.capital_alocado or 0.0
        
        if f.user_id not in rois_clientes:
            rois_clientes[f.user_id] = {'bruto_acumulado': 0.0, 'capital': capital_cliente}
            
        rois_clientes[f.user_id]['bruto_acumulado'] += f.bruto

        for d in f.dias:
            if d.status == 'relatorio_enviado' and d.bruto != 0:
                dados_grafico_raw[d.data_pregao] = dados_grafico_raw.get(d.data_pregao, 0.0) + d.bruto

    datas_ordenadas = sorted(dados_grafico_raw.keys())
    chart_labels = [dt.strftime('%d/%m') for dt in datas_ordenadas]
    chart_data = [round(dados_grafico_raw[dt], 2) for dt in datas_ordenadas]

    lista_rois = []
    for uid, dados in rois_clientes.items():
        if dados['capital'] > 0 and dados['bruto_acumulado'] != 0:
            roi_cliente = (dados['bruto_acumulado'] / dados['capital']) * 100
            lista_rois.append(roi_cliente)

    if lista_rois:
        roi_min = min(lista_rois)
        roi_max = max(lista_rois)
        roi_med = sum(lista_rois) / len(lista_rois)
    else:
        roi_min = roi_med = roi_max = 0.0

    clientes_ativos = User.query.filter(
        User.role == 'cliente', 
        User.status_acesso == 'ativo',
        db.or_(User.is_isento == False, User.is_isento.is_(None))
    ).count()
    
    clientes_inativos = User.query.filter_by(role='cliente', status_acesso='inativo').count()
    
    alocado_row = db.session.query(db.func.sum(User.capital_alocado)).filter(
        User.role == 'cliente', 
        User.status_acesso == 'ativo', 
        db.or_(User.is_isento == False, User.is_isento.is_(None))
    ).first()
    
    capital_total = alocado_row[0] or 0.0
    
    qtd_faturas = len(faturas_filtradas)
    media_cliente = faturamento_bruto_total / qtd_faturas if qtd_faturas > 0 else 0.0
    
    return render_template('admin/dashboard.html', 
                           clientes_ativos=clientes_ativos,
                           clientes_inativos=clientes_inativos,
                           capital_total=capital_total,
                           faturamento_total=faturamento_total,
                           faturamento_bruto_total=faturamento_bruto_total,
                           media_cliente=media_cliente,
                           label_periodo=label_periodo,
                           chart_labels=chart_labels,
                           chart_data=chart_data,
                           roi_min=roi_min,
                           roi_med=roi_med,
                           roi_max=roi_max)

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
        
    clientes = query.order_by(User.nome.asc()).all()
    
    return render_template('admin/index.html', clientes=clientes, busca=busca, status_filtro=status_filtro)

@admin_bp.route('/liberar_cliente', methods=['POST'])
@login_required
def liberar_cliente():
    cpf = ''.join(filter(str.isdigit, request.form.get('cpf')))
    nome_temp = request.form.get('nome_temp')
    is_isento = True if request.form.get('is_isento') else False
    
    if User.query.filter_by(cpf=cpf).first():
        flash('CPF já cadastrado.', 'error')
        return redirect(url_for('admin.clientes_list'))

    novo = User(cpf=cpf, nome=nome_temp, role='cliente', status_acesso='pendente_cadastro', is_isento=is_isento)
    db.session.add(novo)
    db.session.flush()
    
    hoje = datetime.now(tz_br).date()
    dias_para_sexta = (hoje.weekday() - 4) % 7
    inicio_ciclo = hoje - timedelta(days=dias_para_sexta)
    fim_ciclo = inicio_ciclo + timedelta(days=6)
    
    fatura = Fatura(user_id=novo.id, data_inicio=inicio_ciclo, data_fim=fim_ciclo)
    db.session.add(fatura)
    
    status_isento_str = "Sim" if is_isento else "Não"
    registrar_log(f"Liberou novo acesso pré-cadastro para o CPF {cpf} (Nome: {nome_temp}, Isento: {status_isento_str}).", "Clientes")
    
    db.session.commit()
    flash('Acesso liberado e ciclo inicial preparado!', 'success')
    return redirect(url_for('admin.clientes_list'))

@admin_bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_cliente(id):
    cliente = User.query.get_or_404(id)
    if request.method == 'POST':
        corretoras_selecionadas = request.form.getlist('corretora[]')
        capitais_alocados = request.form.getlist('capital[]')
        
        for cap in capitais_alocados:
            if cap and float(cap) < 10000:
                flash('Operação cancelada: O capital mínimo exigido por corretora é de R$ 10.000,00.', 'error')
                return redirect(url_for('admin.editar_cliente', id=cliente.id))

        nome_raw = request.form.get('nome', '')
        cliente.nome = nome_raw.strip().title()
        
        cliente.email = request.form.get('email')
        cliente.celular = request.form.get('celular')
        cliente.is_isento = True if request.form.get('is_isento') else False
        
        AlocacaoCorretora.query.filter_by(user_id=cliente.id).delete()
        
        capital_soma = 0.0
        for corretora, capital in zip(corretoras_selecionadas, capitais_alocados):
            if corretora and capital:
                nova_alocacao = AlocacaoCorretora(
                    user_id=cliente.id,
                    nome_corretora=corretora.upper(),
                    capital_alocado=float(capital)
                )
                db.session.add(nova_alocacao)
                capital_soma += float(capital)
                
        cliente.capital_alocado = capital_soma
        
        status_isento = "Sim" if cliente.is_isento else "Não"
        registrar_log(f"Editou o cadastro (Isento: {status_isento}) e alocações do cliente {cliente.nome} (Novo Capital: R$ {capital_soma:,.2f}).", "Clientes")
        
        db.session.commit()
        flash('Dados e alocações atualizados com sucesso!', 'success')
        return redirect(url_for('admin.clientes_list'))
        
    return render_template('admin/editar.html', cliente=cliente)

@admin_bp.route('/inativar_cliente/<int:id>', methods=['POST'])
@login_required
def inativar_cliente(id):
    cliente = User.query.get_or_404(id)
    cliente.status_acesso = 'inativo'
    registrar_log(f"Inativou o acesso do cliente {cliente.nome}.", "Clientes")
    db.session.commit()
    flash(f'Cliente {cliente.nome} inativado com sucesso.', 'success')
    return redirect(url_for('admin.clientes_list'))

@admin_bp.route('/excluir_cliente/<int:id>', methods=['POST'])
@login_required
def excluir_cliente(id):
    cliente = User.query.get_or_404(id)
    nome_cliente = cliente.nome 
    db.session.delete(cliente)
    registrar_log(f"Excluiu permanentemente o cliente {nome_cliente} e todos os seus históricos.", "Segurança")
    db.session.commit()
    flash('Cliente e todas as suas faturas foram excluídos permanentemente.', 'success')
    return redirect(url_for('admin.clientes_list'))

@admin_bp.route('/pagamentos')
@login_required
def pagamentos():
    if current_user.role != 'admin': return redirect(url_for('client.dashboard'))
    
    busca = request.args.get('q', '')
    ciclo = request.args.get('ciclo')
    
    if ciclo or busca:
        query = User.query.filter_by(role='cliente', status_acesso='ativo')
        
        if busca:
            query = query.filter((User.nome.ilike(f'%{busca}%')) | (User.matricula.ilike(f'%{busca}%')))
        
        ativos = query.order_by(User.nome.asc()).all()
        
        if ciclo:
            try:
                data_selecionada = datetime.strptime(ciclo, '%Y-%m-%d').date()
                dias_para_sexta = (data_selecionada.weekday() - 4) % 7
                inicio_ciclo = data_selecionada - timedelta(days=dias_para_sexta)
            except ValueError:
                hoje = datetime.now(tz_br).date()
                dias_para_sexta = (hoje.weekday() - 4) % 7
                inicio_ciclo = hoje - timedelta(days=dias_para_sexta)
        else:
            hoje = datetime.now(tz_br).date()
            dias_para_sexta = (hoje.weekday() - 4) % 7
            inicio_ciclo = hoje - timedelta(days=dias_para_sexta)
            
        dias_uteis = []
        data_atual = inicio_ciclo
        while len(dias_uteis) < 5 and data_atual <= (inicio_ciclo + timedelta(days=6)):
            if data_atual.weekday() < 5:
                dias_uteis.append(data_atual)
            data_atual += timedelta(days=1)
        
        clientes_dados = []
        for c in ativos:
            auto_gerar_ciclo_admin(c, data_base=inicio_ciclo)
            
            fatura_atual = Fatura.query.filter_by(user_id=c.id, data_inicio=inicio_ciclo).first()
            detalhes_corretoras = {}
            
            if fatura_atual:
                status_atual = fatura_atual.status
                for aloc in c.alocacoes:
                    dias_corretora = [d for d in fatura_atual.dias if d.nome_corretora == aloc.nome_corretora]
                    dias_enviados = sum(1 for d in dias_corretora if d.status == 'relatorio_enviado')
                    dias_isentos = sum(1 for d in dias_corretora if d.status == 'isento')
                    total_base = len(dias_corretora) if dias_corretora else 5
                    total_exigido = total_base - dias_isentos
                    
                    detalhes_corretoras[aloc.nome_corretora] = f"{dias_enviados}/{total_exigido}"
            else:
                status_atual = 'sem_fatura'
                
            clientes_dados.append({
                'info': c, 
                'status_semana': status_atual, 
                'inicio_ciclo': inicio_ciclo,
                'detalhes_corretoras': detalhes_corretoras
            })
            
        return render_template('admin/pagamentos.html', clientes_dados=clientes_dados, busca=busca, exibe_clientes=True, ciclo_data=inicio_ciclo, dias_uteis=dias_uteis)
    
    else:
        ciclos_db = db.session.query(
            Fatura.data_inicio, Fatura.data_fim
        ).distinct().order_by(Fatura.data_inicio.desc()).limit(15).all()
        
        gavetas = []
        for dt_ini, dt_fim in ciclos_db:
            todas_faturas = Fatura.query.join(User).filter(
                Fatura.data_inicio == dt_ini,
                User.status_acesso == 'ativo',
                db.or_(User.is_isento == False, User.is_isento.is_(None))
            ).all()
            
            total = len(todas_faturas)
            if total > 0:
                pendentes = sum(1 for f in todas_faturas if f.status in ['pendente', 'parcial'])
                gavetas.append({
                    'data_inicio': dt_ini,
                    'data_fim': dt_fim,
                    'total_clientes': total,
                    'pendentes': pendentes
                })
                
        return render_template('admin/pagamentos.html', gavetas=gavetas, exibe_clientes=False)

@admin_bp.route('/pagamentos/<int:id>')
@login_required
def pagamentos_cliente(id):
    cliente = User.query.get_or_404(id)
    ciclo = request.args.get('ciclo')
    
    if ciclo:
        try:
            dt_inicio = datetime.strptime(ciclo, '%Y-%m-%d').date()
            auto_gerar_ciclo_admin(cliente, data_base=dt_inicio)
            query = Fatura.query.filter_by(user_id=cliente.id, data_inicio=dt_inicio)
        except ValueError:
            query = Fatura.query.filter_by(user_id=cliente.id)
    else:
        auto_gerar_ciclo_admin(cliente)
        query = Fatura.query.filter_by(user_id=cliente.id)
            
    faturas = query.order_by(Fatura.data_inicio.desc()).all()
    
    return render_template('admin/pagamentos_cliente.html', cliente=cliente, faturas=faturas, ciclo_voltar=ciclo)

@admin_bp.route('/pagamentos/status/<int:fatura_id>', methods=['POST'])
@login_required
def status_pagamento(fatura_id):
    fatura = Fatura.query.get_or_404(fatura_id)
    status_novo = request.form.get('status')
    fatura.status = status_novo
    
    periodo_str = f"{fatura.data_inicio.strftime('%d/%m')} a {fatura.data_fim.strftime('%d/%m/%Y')}"
    registrar_log(f"Alterou o status da fatura de {fatura.cliente.nome} (Período: {periodo_str}) para {status_novo.upper()}.", "Pagamentos")
    
    db.session.commit()
    flash('Status da fatura atualizado.', 'success')
    return redirect(url_for('admin.pagamentos_cliente', id=fatura.user_id, ciclo=fatura.data_inicio.strftime('%Y-%m-%d')))

@admin_bp.route('/pagamentos/isentar_dia_global', methods=['POST'])
@login_required
def isentar_dia_global():
    data_str = request.form.get('data_isencao')
    ciclo_str = request.form.get('ciclo_atual')
    
    try:
        data_alvo = datetime.strptime(data_str, '%Y-%m-%d').date()
        dias_afetados = FaturaDiaria.query.filter_by(data_pregao=data_alvo).all()
        
        faturas_afetadas = set()
        for dia in dias_afetados:
            dia.is_isento = True
            dia.status = 'isento'
            dia.arquivo_pdf = None
            dia.bruto = 0.0
            dia.taxas_b3 = 0.0
            dia.irrf_1 = 0.0
            dia.liquido_pregao = 0.0
            dia.irrf_19 = 0.0
            dia.liquido = 0.0
            dia.repasse = 0.0
            faturas_afetadas.add(dia.fatura_semanal)
            
        for fatura in faturas_afetadas:
            atualizar_totais_semana_admin(fatura)
            
        registrar_log(f"Isentou globalmente o dia {data_alvo.strftime('%d/%m/%Y')} para toda a base.", "Pagamentos")
        flash(f'O dia {data_alvo.strftime("%d/%m/%Y")} foi isentado para todos os clientes!', 'success')
        
    except Exception as e:
        flash(f'Erro ao isentar dia: {str(e)}', 'error')
        
    return redirect(url_for('admin.pagamentos', ciclo=ciclo_str))

@admin_bp.route('/pagamentos/isentar_dia/<int:dia_id>', methods=['POST'])
@login_required
def isentar_dia(dia_id):
    dia = FaturaDiaria.query.get_or_404(dia_id)
    
    dia.is_isento = True
    dia.status = 'isento'
    dia.arquivo_pdf = None
    dia.bruto = 0.0
    dia.taxas_b3 = 0.0
    dia.irrf_1 = 0.0
    dia.liquido_pregao = 0.0
    dia.irrf_19 = 0.0
    dia.liquido = 0.0
    dia.repasse = 0.0
    
    registrar_log(f"Marcou como Isento o dia {dia.data_pregao.strftime('%d/%m/%Y')} (Corretora: {dia.nome_corretora}) do cliente {dia.fatura_semanal.cliente.nome}.", "Pagamentos")
    
    atualizar_totais_semana_admin(dia.fatura_semanal)
    flash('Dia marcado como isento! O cliente não precisará enviar nota para esta data.', 'success')
    return redirect(url_for('admin.pagamentos_cliente', id=dia.fatura_semanal.user_id, ciclo=dia.fatura_semanal.data_inicio.strftime('%Y-%m-%d')))

@admin_bp.route('/pagamentos/remover_isencao/<int:dia_id>', methods=['POST'])
@login_required
def remover_isencao_dia(dia_id):
    dia = FaturaDiaria.query.get_or_404(dia_id)
    
    dia.is_isento = False
    dia.status = 'pendente'
    
    registrar_log(f"Removeu a isenção do dia {dia.data_pregao.strftime('%d/%m/%Y')} (Corretora: {dia.nome_corretora}) do cliente {dia.fatura_semanal.cliente.nome}.", "Pagamentos")
    
    atualizar_totais_semana_admin(dia.fatura_semanal)
    flash('Isenção removida. O dia voltou a ficar pendente de nota.', 'success')
    return redirect(url_for('admin.pagamentos_cliente', id=dia.fatura_semanal.user_id, ciclo=dia.fatura_semanal.data_inicio.strftime('%Y-%m-%d')))

@admin_bp.route('/pagamentos/rejeitar/<int:dia_id>', methods=['POST'])
@login_required
def rejeitar_relatorio(dia_id):
    dia = FaturaDiaria.query.get_or_404(dia_id)
    
    registrar_log(f"Rejeitou e excluiu o relatório de {dia.fatura_semanal.cliente.nome} do pregão {dia.data_pregao.strftime('%d/%m/%Y')} (Corretora: {dia.nome_corretora}).", "Pagamentos")
    
    dia.arquivo_pdf = None
    dia.status = 'pendente'
    dia.bruto = 0.0
    dia.taxas_b3 = 0.0
    dia.irrf_1 = 0.0
    dia.liquido_pregao = 0.0
    dia.irrf_19 = 0.0
    dia.liquido = 0.0
    dia.repasse = 0.0
    
    atualizar_totais_semana_admin(dia.fatura_semanal)
    flash('Relatório rejeitado e valores recalculados.', 'success')
    return redirect(url_for('admin.pagamentos_cliente', id=dia.fatura_semanal.user_id, ciclo=dia.fatura_semanal.data_inicio.strftime('%Y-%m-%d')))

@admin_bp.route('/pagamentos/forcar_limpeza/<int:dia_id>', methods=['POST'])
@login_required
def forcar_limpeza_dia(dia_id):
    dia = FaturaDiaria.query.get_or_404(dia_id)
    
    registrar_log(f"Forçou a limpeza de valores fantasmas do pregão {dia.data_pregao.strftime('%d/%m/%Y')} (Corretora: {dia.nome_corretora}) do cliente {dia.fatura_semanal.cliente.nome}.", "Pagamentos")
    
    dia.arquivo_pdf = None
    dia.status = 'pendente'
    dia.bruto = 0.0
    dia.taxas_b3 = 0.0
    dia.irrf_1 = 0.0
    dia.liquido_pregao = 0.0
    dia.irrf_19 = 0.0
    dia.liquido = 0.0
    dia.repasse = 0.0
    
    atualizar_totais_semana_admin(dia.fatura_semanal)
    flash('Limpeza forçada! Todos os valores fantasmas deste dia foram zerados.', 'success')
    return redirect(url_for('admin.pagamentos_cliente', id=dia.fatura_semanal.user_id, ciclo=dia.fatura_semanal.data_inicio.strftime('%Y-%m-%d')))

@admin_bp.route('/gerar_senha_temporaria/<int:id>', methods=['POST'])
@login_required
def gerar_senha_temporaria(id):
    cliente = User.query.get_or_404(id)
    senha_temp = "DW@" + ''.join(random.choices(string.ascii_letters + string.digits, k=5))
    cliente.password_hash = generate_password_hash(senha_temp)
    cliente.precisa_trocar_senha = True
    
    registrar_log(f"Gerou e forçou uma troca de senha temporária para o cliente {cliente.nome}.", "Segurança")
    
    db.session.commit()
    flash(f'Senha gerada para {cliente.nome}: {senha_temp}', 'success')
    return redirect(url_for('admin.editar_cliente', id=cliente.id))

@admin_bp.route('/atividades')
@login_required
def atividades():
    if current_user.role != 'admin': return redirect(url_for('client.dashboard'))
    
    busca = request.args.get('q', '')
    query = LogAuditoria.query
    
    if busca:
        query = query.filter(
            (LogAuditoria.admin_nome.ilike(f'%{busca}%')) | 
            (LogAuditoria.acao_detalhada.ilike(f'%{busca}%')) | 
            (LogAuditoria.categoria.ilike(f'%{busca}%'))
        )
        
    logs = query.order_by(LogAuditoria.timestamp.desc()).limit(200).all()
    
    return render_template('admin/atividades.html', logs=logs, busca=busca)

# --- FASE 4: GESTÃO DE ASSINATURAS (ARQUIVO LOCAL) ---
@admin_bp.route('/documentos')
@login_required
def documentos():
    if current_user.role != 'admin': return redirect(url_for('client.dashboard'))
    
    templates = DocumentoTemplate.query.all()
    clientes = User.query.filter_by(role='cliente', status_acesso='ativo').order_by(User.nome.asc()).all()
    historico = DocumentoCliente.query.order_by(DocumentoCliente.data_envio.desc()).limit(100).all()
    
    return render_template('admin/documentos.html', templates=templates, clientes=clientes, historico=historico)

@admin_bp.route('/documentos/cadastrar_template', methods=['POST'])
@login_required
def cadastrar_template():
    if current_user.role != 'admin': return redirect(url_for('client.dashboard'))
    
    nome = request.form.get('nome')
    arquivo_local = request.form.get('arquivo_local')
    
    novo_temp = DocumentoTemplate(nome=nome, arquivo_local=arquivo_local)
    db.session.add(novo_temp)
    registrar_log(f"Cadastrou novo Modelo de Contrato: {nome}.", "Assinaturas")
    db.session.commit()
    
    flash(f'Modelo "{nome}" registrado! Certifique-se de que o arquivo "{arquivo_local}" esteja na pasta static/documentos/.', 'success')
    return redirect(url_for('admin.documentos'))

@admin_bp.route('/documentos/disparar', methods=['POST'])
@login_required
def disparar_documento():
    if current_user.role != 'admin': return redirect(url_for('client.dashboard'))
    
    template_id = request.form.get('template_id')
    user_ids = request.form.getlist('clientes[]')
    
    template = DocumentoTemplate.query.get_or_404(template_id)
    
    caminho_pdf = os.path.join(current_app.root_path, 'static', 'documentos', template.arquivo_local)
    
    if not os.path.exists(caminho_pdf):
        flash(f'Erro: O arquivo "{template.arquivo_local}" não foi encontrado na pasta static/documentos/.', 'error')
        return redirect(url_for('admin.documentos'))

    enviados = 0
    erros = 0
    sem_email = []
    
    for uid in user_ids:
        cliente = User.query.get(uid)
        if cliente:
            if not cliente.email:
                sem_email.append(cliente.nome)
                continue
                
            try:
                nome_doc = f"{template.nome} - {cliente.nome}"
                doc_id, link = enviar_documento_local_com_link(cliente.nome, cliente.email, caminho_pdf, nome_doc)
                
                novo_doc = DocumentoCliente(
                    user_id=cliente.id,
                    template_id=template.id,
                    autentique_document_id=doc_id,
                    link_assinatura=link,
                    status='pendente'
                )
                db.session.add(novo_doc)
                enviados += 1
            except Exception as e:
                print(f"Erro ao disparar para {cliente.nome}: {e}")
                erros += 1
                
    db.session.commit()
    
    if enviados > 0:
        registrar_log(f"Disparou contrato '{template.nome}' via arquivo local para {enviados} investidores.", "Assinaturas")
        flash(f'{enviados} documentos enviados com sucesso!', 'success')
        
    if sem_email:
        flash(f'Clientes sem e-mail ignorados: {", ".join(sem_email)}', 'error')
        
    if erros > 0:
        flash(f'Houve erro técnico em {erros} envios.', 'error')
        
    return redirect(url_for('admin.documentos'))

