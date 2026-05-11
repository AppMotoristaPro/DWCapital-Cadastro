import os
import random
import string
from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app
from flask_login import current_user
from werkzeug.security import generate_password_hash
from app.models import User, Fatura, FaturaDiaria, AlocacaoCorretora, LogAuditoria, DocumentoTemplate, DocumentoCliente
from app import db
from datetime import datetime, timedelta
from app.utils.decorators import admin_required
from app.services.fatura_service import atualizar_totais_semana, auto_gerar_ciclo
from app.services.documento_service import disparar_lote
from app.services.dashboard_service import obter_dados_dashboard
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

@admin_bp.route('/')
@admin_required
def dashboard():
    filtro_dia = request.args.get('dia')
    filtro_semana_dia = request.args.get('semana_dia') 
    filtro_ano = request.args.get('ano') 
    
    # O Cérebro do Dashboard foi isolado na Camada de Serviços
    dados = obter_dados_dashboard(filtro_dia, filtro_semana_dia, filtro_ano)
    
    return render_template('admin/dashboard.html', **dados)

@admin_bp.route('/clientes')
@admin_required
def clientes_list():
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
@admin_required
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
@admin_required
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
@admin_required
def inativar_cliente(id):
    cliente = User.query.get_or_404(id)
    cliente.status_acesso = 'inativo'
    registrar_log(f"Inativou o acesso do cliente {cliente.nome}.", "Clientes")
    db.session.commit()
    flash(f'Cliente {cliente.nome} inativado com sucesso.', 'success')
    return redirect(url_for('admin.clientes_list'))

@admin_bp.route('/excluir_cliente/<int:id>', methods=['POST'])
@admin_required
def excluir_cliente(id):
    cliente = User.query.get_or_404(id)
    nome_cliente = cliente.nome 
    db.session.delete(cliente)
    registrar_log(f"Excluiu permanentemente o cliente {nome_cliente} e todos os seus históricos.", "Segurança")
    db.session.commit()
    flash('Cliente e todas as suas faturas foram excluídos permanentemente.', 'success')
    return redirect(url_for('admin.clientes_list'))

@admin_bp.route('/pagamentos')
@admin_required
def pagamentos():
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
            auto_gerar_ciclo(c, data_base=inicio_ciclo)
            
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
@admin_required
def pagamentos_cliente(id):
    cliente = User.query.get_or_404(id)
    ciclo = request.args.get('ciclo')
    
    if ciclo:
        try:
            dt_inicio = datetime.strptime(ciclo, '%Y-%m-%d').date()
            auto_gerar_ciclo(cliente, data_base=dt_inicio)
            query = Fatura.query.filter_by(user_id=cliente.id, data_inicio=dt_inicio)
        except ValueError:
            query = Fatura.query.filter_by(user_id=cliente.id)
    else:
        auto_gerar_ciclo(cliente)
        query = Fatura.query.filter_by(user_id=cliente.id)
            
    faturas = query.order_by(Fatura.data_inicio.desc()).all()
    
    return render_template('admin/pagamentos_cliente.html', cliente=cliente, faturas=faturas, ciclo_voltar=ciclo)

@admin_bp.route('/pagamentos/status/<int:fatura_id>', methods=['POST'])
@admin_required
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
@admin_required
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
            atualizar_totais_semana(fatura)
            
        registrar_log(f"Isentou globalmente o dia {data_alvo.strftime('%d/%m/%Y')} para toda a base.", "Pagamentos")
        flash(f'O dia {data_alvo.strftime("%d/%m/%Y")} foi isentado para todos os clientes!', 'success')
        
    except Exception as e:
        flash(f'Erro ao isentar dia: {str(e)}', 'error')
        
    return redirect(url_for('admin.pagamentos', ciclo=ciclo_str))

@admin_bp.route('/pagamentos/isentar_dia/<int:dia_id>', methods=['POST'])
@admin_required
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
    
    atualizar_totais_semana(dia.fatura_semanal)
    flash('Dia marcado como isento! O cliente não precisará enviar nota para esta data.', 'success')
    return redirect(url_for('admin.pagamentos_cliente', id=dia.fatura_semanal.user_id, ciclo=dia.fatura_semanal.data_inicio.strftime('%Y-%m-%d')))

@admin_bp.route('/pagamentos/remover_isencao/<int:dia_id>', methods=['POST'])
@admin_required
def remover_isencao_dia(dia_id):
    dia = FaturaDiaria.query.get_or_404(dia_id)
    
    dia.is_isento = False
    dia.status = 'pendente'
    
    registrar_log(f"Removeu a isenção do dia {dia.data_pregao.strftime('%d/%m/%Y')} (Corretora: {dia.nome_corretora}) do cliente {dia.fatura_semanal.cliente.nome}.", "Pagamentos")
    
    atualizar_totais_semana(dia.fatura_semanal)
    flash('Isenção removida. O dia voltou a ficar pendente de nota.', 'success')
    return redirect(url_for('admin.pagamentos_cliente', id=dia.fatura_semanal.user_id, ciclo=dia.fatura_semanal.data_inicio.strftime('%Y-%m-%d')))

@admin_bp.route('/pagamentos/rejeitar/<int:dia_id>', methods=['POST'])
@admin_required
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
    
    atualizar_totais_semana(dia.fatura_semanal)
    flash('Relatório rejeitado e valores recalculados.', 'success')
    return redirect(url_for('admin.pagamentos_cliente', id=dia.fatura_semanal.user_id, ciclo=dia.fatura_semanal.data_inicio.strftime('%Y-%m-%d')))

@admin_bp.route('/pagamentos/forcar_limpeza/<int:dia_id>', methods=['POST'])
@admin_required
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
    
    atualizar_totais_semana(dia.fatura_semanal)
    flash('Limpeza forçada! Todos os valores fantasmas deste dia foram zerados.', 'success')
    return redirect(url_for('admin.pagamentos_cliente', id=dia.fatura_semanal.user_id, ciclo=dia.fatura_semanal.data_inicio.strftime('%Y-%m-%d')))

@admin_bp.route('/gerar_senha_temporaria/<int:id>', methods=['POST'])
@admin_required
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
@admin_required
def atividades():
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

@admin_bp.route('/documentos')
@admin_required
def documentos():
    templates = DocumentoTemplate.query.all()
    clientes = User.query.filter_by(role='cliente', status_acesso='ativo').order_by(User.nome.asc()).all()
    historico = DocumentoCliente.query.order_by(DocumentoCliente.data_envio.desc()).limit(100).all()
    
    return render_template('admin/documentos.html', templates=templates, clientes=clientes, historico=historico)

@admin_bp.route('/documentos/cadastrar_template', methods=['POST'])
@admin_required
def cadastrar_template():
    nome = request.form.get('nome')
    arquivo_local = request.form.get('arquivo_local')
    
    novo_temp = DocumentoTemplate(nome=nome, arquivo_local=arquivo_local)
    db.session.add(novo_temp)
    registrar_log(f"Cadastrou novo Modelo de Contrato: {nome}.", "Assinaturas")
    db.session.commit()
    
    flash(f'Modelo "{nome}" registrado! Certifique-se de que o arquivo "{arquivo_local}" esteja na pasta static/documentos/.', 'success')
    return redirect(url_for('admin.documentos'))

@admin_bp.route('/documentos/disparar', methods=['POST'])
@admin_required
def disparar_documento():
    template_id = request.form.get('template_id')
    user_ids = request.form.getlist('clientes[]')
    
    try:
        enviados, erros, sem_email, nome_template = disparar_lote(template_id, user_ids)
        
        if enviados > 0:
            registrar_log(f"Disparou contrato '{nome_template}' via arquivo local para {enviados} investidores.", "Assinaturas")
            flash(f'{enviados} documentos enviados com sucesso!', 'success')
            
        if sem_email:
            flash(f'Clientes sem e-mail ignorados: {", ".join(sem_email)}', 'error')
            
        if erros > 0:
            flash(f'Houve erro técnico em {erros} envios.', 'error')
            
    except FileNotFoundError as e:
        flash(str(e), 'error')
    except Exception as e:
        flash(f'Ocorreu um erro inesperado: {str(e)}', 'error')
        
    return redirect(url_for('admin.documentos'))

