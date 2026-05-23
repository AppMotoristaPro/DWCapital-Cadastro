import os
import random
import string
import requests
from tempfile import NamedTemporaryFile
from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app, jsonify, send_file
from flask_login import current_user
from werkzeug.security import generate_password_hash
from sqlalchemy.orm import joinedload
from app.models import User, Fatura, FaturaDiaria, AlocacaoCorretora, LogAuditoria, DocumentoTemplate, DocumentoCliente, ParcelaCompra
from app import db
from datetime import datetime, timedelta
from app.utils.decorators import admin_required
from app.services.fatura_service import atualizar_totais_semana, auto_gerar_ciclo, auto_gerar_ciclos_em_lote
from app.services.documento_service import disparar_lote, disparar_unico
from app.services.dashboard_service import obter_dados_dashboard
from app.utils.parsers.gerenciador_pdf import processar_pdf
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
    
    dados = obter_dados_dashboard(filtro_dia, filtro_semana_dia, filtro_ano)
    return render_template('admin/dashboard.html', **dados)

@admin_bp.route('/clientes')
@admin_required
def clientes_list():
    busca = request.args.get('q', '')
    status_filtro = request.args.get('status', '')
    page = request.args.get('page', 1, type=int)
    
    query = User.query.filter_by(role='cliente').options(joinedload(User.alocacoes))
    
    if busca:
        busca_limpa = ''.join(filter(str.isdigit, busca))
        filtros = [User.nome.ilike(f'%{busca}%')]
        if busca_limpa:
            filtros.append(User.cpf.ilike(f'%{busca_limpa}%'))
        if busca.isdigit():
            filtros.append(User.id == int(busca))
        query = query.filter(db.or_(*filtros))
        
    if status_filtro:
        query = query.filter_by(status_acesso=status_filtro)
        
    pagination = query.order_by(User.nome.asc()).paginate(page=page, per_page=20, error_out=False)
    return render_template('admin/index.html', pagination=pagination, busca=busca, status_filtro=status_filtro)

@admin_bp.route('/liberar_cliente', methods=['POST'])
@admin_required
def liberar_cliente():
    cpf = ''.join(filter(str.isdigit, request.form.get('cpf')))
    nome_temp = request.form.get('nome_temp')
    is_isento = True if request.form.get('is_isento') else False
    modelo_negocio = request.form.get('modelo_negocio', 'comissao')
    
    if User.query.filter_by(cpf=cpf).first():
        flash('CPF já cadastrado.', 'error')
        return redirect(url_for('admin.clientes_list'))

    novo = User(cpf=cpf, nome=nome_temp, role='cliente', status_acesso='pendente_cadastro', is_isento=is_isento, modelo_negocio=modelo_negocio)
    db.session.add(novo)
    db.session.flush() 
    
    hoje = datetime.now(tz_br).date()
    
    if modelo_negocio == 'compra':
        p1 = ParcelaCompra(user_id=novo.id, ordem=1, valor=5000.0, data_vencimento=hoje)
        p2 = ParcelaCompra(user_id=novo.id, ordem=2, valor=2500.0, data_vencimento=hoje + timedelta(days=30))
        p3 = ParcelaCompra(user_id=novo.id, ordem=3, valor=2500.0, data_vencimento=hoje + timedelta(days=60))
        db.session.add_all([p1, p2, p3])
    else:
        dias_para_sexta = (hoje.weekday() - 4) % 7
        inicio_ciclo = hoje - timedelta(days=dias_para_sexta)
        fim_ciclo = inicio_ciclo + timedelta(days=6)
        fatura = Fatura(user_id=novo.id, data_inicio=inicio_ciclo, data_fim=fim_ciclo)
        db.session.add(fatura)
        
    templates_onboarding = DocumentoTemplate.query.filter_by(is_onboarding=True).all()
    if templates_onboarding:
        docs_onboarding = [
            DocumentoCliente(
                user_id=novo.id,
                template_id=t.id,
                status='na_fila'
            ) for t in templates_onboarding
        ]
        db.session.add_all(docs_onboarding)
    
    status_isento_str = "Sim" if is_isento else "Não"
    registrar_log(f"Liberou novo acesso pré-cadastro para o CPF {cpf} (Nome: {nome_temp}, Isento: {status_isento_str}, Modelo: {modelo_negocio.upper()}).", "Clientes")
    
    db.session.commit()
    flash('Acesso liberado e conta inicial preparada com contratos de onboarding na fila!', 'success')
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
        
        novo_modelo = request.form.get('modelo_negocio', 'comissao')
        
        if novo_modelo == 'compra':
            hoje = datetime.now(tz_br).date()
            has_parcelas = ParcelaCompra.query.filter_by(user_id=cliente.id).first()
            if not has_parcelas:
                p1 = ParcelaCompra(user_id=cliente.id, ordem=1, valor=5000.0, data_vencimento=hoje)
                p2 = ParcelaCompra(user_id=cliente.id, ordem=2, valor=2500.0, data_vencimento=hoje + timedelta(days=30))
                p3 = ParcelaCompra(user_id=cliente.id, ordem=3, valor=2500.0, data_vencimento=hoje + timedelta(days=60))
                db.session.add_all([p1, p2, p3])
        
        cliente.modelo_negocio = novo_modelo
        
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
        registrar_log(f"Editou o cadastro (Isento: {status_isento}, Modelo: {novo_modelo.upper()}) e alocações do cliente {cliente.nome} (Novo Capital: R$ {capital_soma:,.2f}).", "Clientes")
        
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

@admin_bp.route('/ativar_cliente/<int:id>', methods=['POST'])
@admin_required
def ativar_cliente(id):
    cliente = User.query.get_or_404(id)
    cliente.status_acesso = 'ativo'
    registrar_log(f"Reativou o acesso do cliente {cliente.nome}.", "Clientes")
    db.session.commit()
    flash(f'Cliente {cliente.nome} reativado com sucesso.', 'success')
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
    
    # 1) Faturamento (Repasse Global - Ignora 'compra' e 'isento')
    repasse_global = db.session.query(db.func.sum(Fatura.repasse)).join(User).filter(
        User.modelo_negocio == 'comissao',
        db.or_(User.is_isento == False, User.is_isento.is_(None))
    ).scalar() or 0.0
    
    if ciclo or busca:
        query = User.query.filter_by(role='cliente', status_acesso='ativo').options(joinedload(User.alocacoes))
        
        if busca:
            query = query.filter((User.nome.ilike(f'%{busca}%')) | (User.matricula.ilike(f'%{busca}%')))
        ativos_brutos = query.order_by(User.nome.asc()).all()
        
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
            
        ativos = []
        for c in ativos_brutos:
            data_cad = c.data_cadastro.date() if c.data_cadastro else datetime.min.date()
            if data_cad <= (inicio_ciclo + timedelta(days=6)):
                ativos.append(c)
        
        auto_gerar_ciclos_em_lote(ativos, data_base=inicio_ciclo)
            
        user_ids = [c.id for c in ativos]
        faturas_do_ciclo = []
        if user_ids:
            faturas_do_ciclo = Fatura.query.options(joinedload(Fatura.dias)).filter(
                Fatura.user_id.in_(user_ids),
                Fatura.data_inicio == inicio_ciclo
            ).all()
            
        mapa_faturas = {f.user_id: f for f in faturas_do_ciclo}
        
        # 2) Faturamento (Repasse do Ciclo Específico)
        repasse_ciclo = db.session.query(db.func.sum(Fatura.repasse)).join(User).filter(
            Fatura.data_inicio == inicio_ciclo,
            User.modelo_negocio == 'comissao',
            db.or_(User.is_isento == False, User.is_isento.is_(None))
        ).scalar() or 0.0
        
        clientes_dados = []
        for c in ativos:
            fatura_atual = mapa_faturas.get(c.id)
            detalhes_corretoras = {}
            
            total_dias_brutos_da_semana = len(dias_uteis)
            
            if fatura_atual:
                status_atual = fatura_atual.status
                for aloc in c.alocacoes:
                    dias_corretora = [d for d in fatura_atual.dias if d.nome_corretora == aloc.nome_corretora]
                    dias_enviados = sum(1 for d in dias_corretora if d.status == 'relatorio_enviado')
                    dias_isentos = sum(1 for d in dias_corretora if d.status == 'isento')
                    
                    total_exigido = total_dias_brutos_da_semana - dias_isentos
                    if total_exigido < 0: total_exigido = 0
                    
                    detalhes_corretoras[aloc.nome_corretora] = f"{dias_enviados}/{total_exigido}"
            else:
                status_atual = 'sem_fatura'
                for aloc in c.alocacoes:
                    detalhes_corretoras[aloc.nome_corretora] = f"0/{total_dias_brutos_da_semana}"
                
            clientes_dados.append({
                'info': c, 
                'status_semana': status_atual, 
                'inicio_ciclo': inicio_ciclo,
                'detalhes_corretoras': detalhes_corretoras
            })
            
        return render_template(
            'admin/pagamentos.html', 
            clientes_dados=clientes_dados, 
            busca=busca, 
            exibe_clientes=True, 
            ciclo_data=inicio_ciclo, 
            dias_uteis=dias_uteis,
            repasse_global=repasse_global,
            repasse_ciclo=repasse_ciclo
        )
    
    else:
        ciclos_db = db.session.query(
            Fatura.data_inicio, Fatura.data_fim
        ).distinct().order_by(Fatura.data_inicio.desc()).limit(15).all()
        
        gavetas = []
        for dt_ini, dt_fim in ciclos_db:
            todas_faturas = Fatura.query.join(User).filter(
                Fatura.data_inicio == dt_ini,
                User.status_acesso == 'ativo'
            ).all()
            
            # 3) Repasse Total exclusivo de cada Gaveta (Ignora 'compra' e 'isento')
            repasse_gaveta = sum(f.repasse for f in todas_faturas if getattr(f.cliente, 'modelo_negocio', 'comissao') == 'comissao' and not getattr(f.cliente, 'is_isento', False))
            
            total = len(todas_faturas)
            if total > 0:
                pendentes = sum(1 for f in todas_faturas if f.status in ['pendente', 'parcial'])
                gavetas.append({
                    'data_inicio': dt_ini,
                    'data_fim': dt_fim,
                    'total_clientes': total,
                    'pendentes': pendentes,
                    'repasse_total': repasse_gaveta
                })
                
        return render_template(
            'admin/pagamentos.html', 
            gavetas=gavetas, 
            exibe_clientes=False,
            repasse_global=repasse_global
        )

@admin_bp.route('/licencas')
@admin_required
def licencas():
    clientes_compra = User.query.filter_by(role='cliente', modelo_negocio='compra').options(joinedload(User.parcelas_licenca)).order_by(User.nome.asc()).all()
    return render_template('admin/licencas.html', clientes=clientes_compra)

@admin_bp.route('/pagamentos/exportar_pendencias')
@admin_required
def exportar_pendencias():
    ativos = User.query.filter(
        User.role == 'cliente', 
        User.status_acesso == 'ativo',
        db.or_(User.is_isento == False, User.is_isento.is_(None))
    ).options(joinedload(User.faturas).joinedload(Fatura.dias)).order_by(User.nome.asc()).all()
    
    from app.utils.processador_xlsx import gerar_relatorio_pendencias
    
    caminho_tmp = os.path.join(current_app.root_path, 'static', 'uploads')
    os.makedirs(caminho_tmp, exist_ok=True)
    arquivo_saida = os.path.join(caminho_tmp, f'Pendencias_Ate_Ontem.xlsx')
    
    tem_dados = gerar_relatorio_pendencias(ativos, arquivo_saida)
    
    if not tem_dados:
        flash('Excelente! Nenhuma pendência consolidada até o dia de ontem foi encontrada.', 'success')
        return redirect(url_for('admin.pagamentos'))
        
    registrar_log("Exportou relatório Excel GLOBAL de pendências (Calculado até ontem).", "Pagamentos")
    
    return send_file(arquivo_saida, as_attachment=True, download_name='Pendencias_Ate_Ontem.xlsx')

@admin_bp.route('/pagamentos/<int:id>')
@admin_required
def pagamentos_cliente(id):
    cliente = User.query.get_or_404(id)
    ciclo = request.args.get('ciclo')
    
    query = Fatura.query.filter_by(user_id=cliente.id).options(joinedload(Fatura.dias))
    
    if ciclo:
        try:
            dt_inicio = datetime.strptime(ciclo, '%Y-%m-%d').date()
            auto_gerar_ciclo(cliente, data_base=dt_inicio)
            query = query.filter_by(data_inicio=dt_inicio)
        except ValueError:
            pass
    else:
        auto_gerar_ciclo(cliente)
            
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
            dia.zerar_valores(isentar=True)
            faturas_afetadas.add(dia.fatura_semanal)
            
        for fatura in faturas_afetadas:
            fatura.recalcular_totais()
        
        db.session.commit()
            
        registrar_log(f"Isentou globalmente o dia {data_alvo.strftime('%d/%m/%Y')} para toda a base.", "Pagamentos")
        flash(f'O dia {data_alvo.strftime("%d/%m/%Y")} foi isentado para todos os clientes!', 'success')
        
    except Exception as e:
        flash(f'Erro ao isentar dia: {str(e)}', 'error')
        
    return redirect(url_for('admin.pagamentos', ciclo=ciclo_str))

@admin_bp.route('/pagamentos/isentar_dia/<int:dia_id>', methods=['POST'])
@admin_required
def isentar_dia(dia_id):
    dia = FaturaDiaria.query.get_or_404(dia_id)
    
    dia.zerar_valores(isentar=True)
    registrar_log(f"Marcou como Isento o dia {dia.data_pregao.strftime('%d/%m/%Y')} (Corretora: {dia.nome_corretora}) do cliente {dia.fatura_semanal.cliente.nome}.", "Pagamentos")
    
    atualizar_totais_semana(dia.fatura_semanal)
    flash('Dia marcado como isento! O cliente não precisará enviar nota para esta data.', 'success')
    return redirect(url_for('admin.pagamentos_cliente', id=dia.fatura_semanal.user_id, ciclo=dia.fatura_semanal.data_inicio.strftime('%Y-%m-%d')))

@admin_bp.route('/pagamentos/remover_isencao/<int:dia_id>', methods=['POST'])
@admin_required
def remover_isencao_dia(dia_id):
    dia = FaturaDiaria.query.get_or_404(dia_id)
    
    dia.zerar_valores(isentar=False)
    registrar_log(f"Removeu a isenção do dia {dia.data_pregao.strftime('%d/%m/%Y')} (Corretora: {dia.nome_corretora}) do cliente {dia.fatura_semanal.cliente.nome}.", "Pagamentos")
    
    atualizar_totais_semana(dia.fatura_semanal)
    flash('Isenção removida. O dia voltou a ficar pendente de nota.', 'success')
    return redirect(url_for('admin.pagamentos_cliente', id=dia.fatura_semanal.user_id, ciclo=dia.fatura_semanal.data_inicio.strftime('%Y-%m-%d')))

@admin_bp.route('/pagamentos/rejeitar/<int:dia_id>', methods=['POST'])
@admin_required
def rejeitar_relatorio(dia_id):
    dia = FaturaDiaria.query.get_or_404(dia_id)
    
    registrar_log(f"Rejeitou e excluiu o relatório de {dia.fatura_semanal.cliente.nome} do pregão {dia.data_pregao.strftime('%d/%m/%Y')} (Corretora: {dia.nome_corretora}).", "Pagamentos")
    
    dia.zerar_valores(isentar=False)
    atualizar_totais_semana(dia.fatura_semanal)
    
    flash('Relatório rejeitado e valores recalculados.', 'success')
    return redirect(url_for('admin.pagamentos_cliente', id=dia.fatura_semanal.user_id, ciclo=dia.fatura_semanal.data_inicio.strftime('%Y-%m-%d')))

@admin_bp.route('/pagamentos/forcar_limpeza/<int:dia_id>', methods=['POST'])
@admin_required
def forcar_limpeza_dia(dia_id):
    dia = FaturaDiaria.query.get_or_404(dia_id)
    
    registrar_log(f"Forçou a limpeza de valores fantasmas do pregão {dia.data_pregao.strftime('%d/%m/%Y')} (Corretora: {dia.nome_corretora}) do cliente {dia.fatura_semanal.cliente.nome}.", "Pagamentos")
    
    dia.zerar_valores(isentar=False)
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
    page = request.args.get('page', 1, type=int)
    
    query = LogAuditoria.query
    if busca:
        query = query.filter(
            (LogAuditoria.admin_nome.ilike(f'%{busca}%')) | (LogAuditoria.acao_detalhada.ilike(f'%{busca}%')) | 
            (LogAuditoria.categoria.ilike(f'%{busca}%'))
        )
    pagination = query.order_by(LogAuditoria.timestamp.desc()).paginate(page=page, per_page=30, error_out=False)
    return render_template('admin/atividades.html', pagination=pagination, busca=busca)

@admin_bp.route('/documentos')
@admin_required
def documentos():
    templates = DocumentoTemplate.query.all()
    clientes = User.query.filter_by(role='cliente', status_acesso='ativo').order_by(User.nome.asc()).all()
    
    page = request.args.get('page', 1, type=int)

    query = DocumentoCliente.query.join(User).join(DocumentoTemplate).options(
        joinedload(DocumentoCliente.cliente), 
        joinedload(DocumentoCliente.template)
    ).filter(
        db.or_(
            User.data_cadastro.is_(None),
            DocumentoCliente.data_envio.is_(None),
            DocumentoCliente.data_envio > User.data_cadastro + timedelta(seconds=60)
        )
    ).order_by(
        DocumentoCliente.status.desc(),
        DocumentoCliente.data_envio.desc()
    )
    
    pagination_docs = query.paginate(page=page, per_page=20, error_out=False)
    
    return render_template('admin/documentos.html', templates=templates, clientes=clientes, pagination_docs=pagination_docs)

@admin_bp.route('/documentos/cadastrar_template', methods=['POST'])
@admin_required
def cadastrar_template():
    nome = request.form.get('nome')
    arquivo_local = request.form.get('arquivo_local')
    is_onboarding = True if request.form.get('is_onboarding') else False
    
    novo_temp = DocumentoTemplate(nome=nome, arquivo_local=arquivo_local, is_onboarding=is_onboarding)
    db.session.add(novo_temp)
    
    status_msg = "obrigatório no primeiro acesso" if is_onboarding else "padrão"
    registrar_log(f"Cadastrou novo Modelo de Contrato {status_msg}: {nome}.", "Assinaturas")
    db.session.commit()
    
    flash(f'Modelo "{nome}" registrado! Certifique-se de que o arquivo "{arquivo_local}" esteja na pasta static/documentos/.', 'success')
    return redirect(url_for('admin.documentos'))

@admin_bp.route('/documentos/excluir_template/<int:id>', methods=['POST'])
@admin_required
def excluir_template(id):
    template = DocumentoTemplate.query.get_or_404(id)
    nome_temp = template.nome
    
    # Removemos todos os DocumentoCliente atrelados para não quebrar a integridade no DB
    DocumentoCliente.query.filter_by(template_id=template.id).delete()
    
    db.session.delete(template)
    registrar_log(f"Excluiu o Modelo de Documento e todas as suas pendências: {nome_temp}.", "Assinaturas")
    db.session.commit()
    
    flash(f'Modelo de contrato "{nome_temp}" excluído com sucesso!', 'success')
    return redirect(url_for('admin.documentos'))

@admin_bp.route('/documentos/disparar', methods=['POST'])
@admin_required
def disparar_documento():
    template_ids = request.form.getlist('template_ids[]')
    user_ids = request.form.getlist('clientes[]')
    
    if not template_ids or not user_ids:
        flash('Selecione ao menos um modelo e um cliente.', 'error')
        return redirect(url_for('admin.documentos'))
        
    try:
        enviados, erros, sem_email, nome_template = disparar_lote(template_ids, user_ids)
        
        if enviados > 0:
            registrar_log(f"Enfileirou contrato(s) '{nome_template}' para disparo futuro a {enviados} investidores.", "Assinaturas")
            flash(f'{enviados} documentos entraram na fila de assinatura dos clientes!', 'success')
            
        if sem_email:
            flash(f'Clientes sem e-mail ignorados: {", ".join(sem_email)}', 'error')
            
        if erros > 0:
            flash(f'Houve erro técnico ao enfileirar {erros} envios.', 'error')
            
    except FileNotFoundError as e:
        flash(str(e), 'error')
    except Exception as e:
        flash(f'Ocorreu um erro inesperado: {str(e)}', 'error')
        
    return redirect(url_for('admin.documentos'))

@admin_bp.route('/documentos/disparar_unico', methods=['POST'])
@admin_required
def api_disparar_unico():
    data = request.get_json()
    template_id = data.get('template_id')
    user_id = data.get('user_id')
    
    if not template_id or not user_id:
        return jsonify({"success": False, "message": "Dados incompletos enviados pela tela."}), 400
        
    resultado = disparar_unico(template_id, user_id)
    
    if resultado.get("success"):
        registrar_log(f"Enfileirou contrato '{resultado.get('nome_template')}' para o ID de cliente {user_id}.", "Assinaturas")
        
    return jsonify(resultado)

@admin_bp.route('/documentos/excluir/<int:doc_id>', methods=['POST'])
@admin_required
def excluir_documento_cliente(doc_id):
    doc = DocumentoCliente.query.get_or_404(doc_id)
    
    if doc.status == 'assinado':
        flash('Não é possível excluir ou cancelar um documento que já foi assinado pelo parceiro.', 'error')
        return redirect(url_for('admin.documentos'))
    
    if doc.template.is_onboarding:
        cliente = doc.cliente
        cliente.termo_assinado = False
    
    nome_doc = doc.template.nome
    nome_cliente = doc.cliente.nome
    
    db.session.delete(doc)
    registrar_log(f"Cancelou e excluiu o documento '{nome_doc}' da fila do parceiro {nome_cliente}.", "Assinaturas")
    db.session.commit()
    
    flash(f'Documento "{nome_doc}" removido com sucesso e obrigatoriedade resetada!', 'success')
    return redirect(url_for('admin.documentos'))

@admin_bp.route('/documentos/excluir_pendentes', methods=['POST'])
@admin_required
def excluir_todos_pendentes():
    try:
        DocumentoCliente.query.filter(DocumentoCliente.status.in_(['na_fila', 'pendente'])).delete(synchronize_session=False)
        db.session.commit()
        
        registrar_log("Cancelou e excluiu TODOS os documentos pendentes/na fila globalmente.", "Assinaturas")
        flash('Todos os documentos pendentes foram removidos com sucesso da fila de disparo!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao excluir em massa: {str(e)}', 'error')
        
    return redirect(url_for('admin.documentos'))

@admin_bp.route('/reprocessar_notas_antigas', methods=['GET'])
@admin_required
def reprocessar_notas_antigas():
    dias_enviados = FaturaDiaria.query.options(
        joinedload(FaturaDiaria.fatura_semanal).joinedload(Fatura.cliente)
    ).filter(
        FaturaDiaria.status == 'relatorio_enviado',
        FaturaDiaria.arquivo_pdf.isnot(None)
    ).all()
    
    sucesso = 0
    erros = 0
    faturas_afetadas = set()
    
    for dia in dias_enviados:
        try:
            response = requests.get(dia.arquivo_pdf, timeout=15)
            if response.status_code == 200:
                with NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
                    temp_pdf.write(response.content)
                    temp_path = temp_pdf.name
                
                cpf_cliente = dia.fatura_semanal.cliente.cpf
                dados = processar_pdf(temp_path, dia.nome_corretora, cpf_cliente, None)
                
                if dados:
                    dia.bruto = dados.get('bruto')
                    dia.taxas_b3 = dados.get('taxas_b3') 
                    dia.irrf_1 = 0.0              
                    dia.liquido_pregao = dados.get('liquido_pregao')
                    dia.irrf_19 = dados.get('irrf_19')
                    dia.liquido = dados.get('liquido_dia')
                    
                    if getattr(dia.fatura_semanal.cliente, 'is_isento', False):
                        dia.repasse = 0.0
                    else:
                        dia.repasse = dados.get('repasse_dw')
            
                    faturas_afetadas.add(dia.fatura_semanal)
                    sucesso += 1
                else:
                    erros += 1
            
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            else:
                erros += 1
        except Exception as e:
            print(f"Erro ao reprocessar dia {dia.id}: {str(e)}")
            erros += 1
            
    for fatura in faturas_afetadas:
        fatura.recalcular_totais()
        
    db.session.commit()
    
    registrar_log(f"Executou Batch Job: Reprocessou e corrigiu {sucesso} notas antigas (Falhas: {erros}).", "Sistema")
    flash(f'Reprocessamento concluído com sucesso! {sucesso} notas financeiras foram corrigidas com o novo motor unificado ({erros} não puderam ser lidas).', 'success')
    
    return redirect(url_for('admin.dashboard'))

