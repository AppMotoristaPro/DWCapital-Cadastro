import os
import random
import string
import requests
import logging
from tempfile import NamedTemporaryFile
from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app, jsonify, send_file
from flask_login import current_user
from werkzeug.security import generate_password_hash
from sqlalchemy.orm import joinedload
from app.models import User, Fatura, FaturaDiaria, AlocacaoCorretora, LogAuditoria, DocumentoTemplate, DocumentoCliente, ParcelaCompra, VersaoRobo, DownloadControle, LicencaCliente, PremioSolicitacao
from app import db, csrf, limiter
from datetime import datetime, timedelta
from app.utils.decorators import admin_required
from app.services.fatura_service import atualizar_totais_semana, auto_gerar_ciclo, auto_gerar_ciclos_em_lote
from app.services.documento_service import disparar_lote, disparar_unico
from app.services.dashboard_service import obter_dados_dashboard
from app.services.licenca_service import gerar_licenca_vitalicia, obter_licenca_ativa, expirar_licencas_semanais
from app.utils.parsers.gerenciador_pdf import processar_pdf
from app.utils.validators import validar_cpf
from app.services.parcela_service import gerar_parcelas_compra_unificado, contar_indicacoes_com_entrada_paga
import cloudinary.uploader
import pytz
import re

logger = logging.getLogger(__name__)
tz_br = pytz.timezone('America/Sao_Paulo')
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

def registrar_log(acao, categoria):
    if current_user.is_authenticated:
        ip = request.remote_addr
        novo_log = LogAuditoria(
            admin_id=current_user.id,
            admin_nome=current_user.nome,
            acao_detalhada=acao,
            categoria=categoria,
            ip_address=ip
        )
        db.session.add(novo_log)

# ==================== FUNÇÃO AUXILIAR PARA AGREGAR CLIENTES ====================

def _agregar_clientes_parcelas(query_parcelas):
    """
    Recebe uma query de ParcelaCompra (já com joins) e retorna uma lista de dicionários
    com dados agregados por cliente, incluindo a lista de parcelas.
    """
    parcelas = query_parcelas.all()
    clientes_dict = {}
    
    hoje = datetime.now(tz_br).date()
    
    for p in parcelas:
        cliente = p.cliente
        if cliente.id not in clientes_dict:
            # Dados agregados do cliente
            clientes_dict[cliente.id] = {
                'id': cliente.id,
                'nome': cliente.nome,
                'cpf': cliente.cpf,
                'is_indicado': cliente.is_indicado,
                'parcelas': [],
                'total_parcelas': 0,
                'parcelas_pagas': 0,
                'valor_total': 0.0,
                'valor_pago': 0.0,
                'valor_pendente': 0.0,
                'proximo_vencimento': None,
                'parcela_atual': None,  # ex: "3/10"
                'status_geral': 'pago'  # pago, parcial, inadimplente
            }
        
        # Adiciona a parcela à lista do cliente
        clientes_dict[cliente.id]['parcelas'].append(p)
        clientes_dict[cliente.id]['total_parcelas'] += 1
        if p.status == 'pago':
            clientes_dict[cliente.id]['parcelas_pagas'] += 1
            clientes_dict[cliente.id]['valor_pago'] += p.valor
        else:
            clientes_dict[cliente.id]['valor_pendente'] += p.valor
            
            # Verifica vencimento para status e próximo vencimento
            if p.data_vencimento < hoje:
                clientes_dict[cliente.id]['status_geral'] = 'inadimplente'
            elif clientes_dict[cliente.id]['status_geral'] != 'inadimplente':
                clientes_dict[cliente.id]['status_geral'] = 'parcial'
            
            # Próximo vencimento (menor data_vencimento pendente)
            if (clientes_dict[cliente.id]['proximo_vencimento'] is None or 
                p.data_vencimento < clientes_dict[cliente.id]['proximo_vencimento']):
                clientes_dict[cliente.id]['proximo_vencimento'] = p.data_vencimento
            
            # Parcela atual (menor ordem pendente)
            if (clientes_dict[cliente.id]['parcela_atual'] is None or 
                p.ordem < clientes_dict[cliente.id]['parcela_atual']):
                clientes_dict[cliente.id]['parcela_atual'] = p.ordem
        
        clientes_dict[cliente.id]['valor_total'] += p.valor
    
    # Se todas as parcelas estão pagas, status geral = pago
    for cliente_id, dados in clientes_dict.items():
        if dados['parcelas_pagas'] == dados['total_parcelas']:
            dados['status_geral'] = 'pago'
        
        # Formata parcela atual para exibição
        if dados['parcela_atual']:
            dados['parcela_atual_exibicao'] = f"{dados['parcela_atual']}/{dados['total_parcelas']}"
        else:
            dados['parcela_atual_exibicao'] = f"{dados['total_parcelas']}/{dados['total_parcelas']}"
    
    # Ordena clientes por nome
    clientes = sorted(clientes_dict.values(), key=lambda x: x['nome'])
    return clientes

# ==================== ROTAS EXISTENTES ====================

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
    page = request.args.get('page', 1, type=int)
    per_page = 20
    clientes = User.query.filter_by(role='cliente').options(joinedload(User.alocacoes)).order_by(User.nome.asc()).paginate(page=page, per_page=per_page, error_out=False)
    clientes_ativos = User.query.filter_by(role='cliente', status_acesso='ativo').order_by(User.nome.asc()).all()
    return render_template('admin/index.html', clientes=clientes, clientes_ativos=clientes_ativos)

@admin_bp.route('/liberar_cliente', methods=['POST'])
@admin_required
def liberar_cliente():
    cpf = ''.join(filter(str.isdigit, request.form.get('cpf')))
    
    if not validar_cpf(cpf):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({"success": False, "message": "CPF inválido. Verifique os dígitos."}), 400
        flash('CPF inválido. Não é possível liberar acesso.', 'error')
        return redirect(url_for('admin.clientes_list'))
    
    nome_temp = request.form.get('nome_temp')
    is_isento = True if request.form.get('is_isento') else False
    modelo_negocio = request.form.get('modelo_negocio', 'comissao')
    
    indicador_id = request.form.get('indicador_id')
    if indicador_id and indicador_id.isdigit():
        indicador_id = int(indicador_id)
    else:
        indicador_id = None
    
    if User.query.filter_by(cpf=cpf).first():
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({"success": False, "message": "CPF já cadastrado."}), 400
        flash('CPF já cadastrado.', 'error')
        return redirect(url_for('admin.clientes_list'))

    novo = User(
        cpf=cpf, 
        nome=nome_temp, 
        role='cliente', 
        status_acesso='pendente_cadastro', 
        is_isento=is_isento, 
        modelo_negocio=modelo_negocio
    )
    
    if modelo_negocio == 'compra' and indicador_id:
        indicador = User.query.get(indicador_id)
        if indicador and indicador.role == 'cliente' and indicador.status_acesso == 'ativo':
            novo.indicador_id = indicador_id
            novo.is_indicado = True
            novo.data_indicacao = datetime.now(tz_br)
    
    db.session.add(novo)
    db.session.flush() 
    
    hoje = datetime.now(tz_br).date()
    
    if modelo_negocio == 'compra':
        parcelas = gerar_parcelas_compra_unificado(novo.id, data_inicio=hoje)
        db.session.add_all(parcelas)
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
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({"success": True, "message": "Cliente liberado com sucesso!"}), 200
    flash('Acesso liberado e conta inicial preparada com contratos de onboarding na fila!', 'success')
    return redirect(url_for('admin.clientes_list'))

@admin_bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@admin_required
def editar_cliente(id):
    cliente = User.query.get_or_404(id)
    modelo_anterior = cliente.modelo_negocio
    
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
        
        cliente.conta_mt5 = request.form.get('conta_mt5', '').strip()
        
        cliente.licenca_bloqueada = True if request.form.get('licenca_bloqueada') else False
        
        novo_modelo = request.form.get('modelo_negocio', 'comissao')
        
        if novo_modelo == 'compra' and not cliente.parcelas_licenca:
            hoje = datetime.now(tz_br).date()
            parcelas = gerar_parcelas_compra_unificado(cliente.id, data_inicio=hoje)
            db.session.add_all(parcelas)
        
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
        
        if modelo_anterior != novo_modelo:
            if novo_modelo == 'compra':
                if cliente.termo_assinado:
                    parcela_inicial = ParcelaCompra.query.filter_by(user_id=cliente.id, ordem=1, status='pago').first()
                    if parcela_inicial:
                        if cliente.conta_mt5:
                            chave, msg, licenca = gerar_licenca_vitalicia(cliente, cliente.conta_mt5)
                            flash(f'Cliente alterado para compra. Licença vitalícia gerada: {chave}', 'success')
                            registrar_log(f"Alterou modelo para compra e gerou licença vitalícia para {cliente.nome}.", "Clientes")
                        else:
                            flash('Cliente alterado para compra, mas não possui conta MT5. Será solicitado no próximo acesso.', 'warning')
                    else:
                        flash('Cliente alterado para compra, mas a primeira parcela ainda não foi paga. Licença será gerada automaticamente após o pagamento.', 'warning')
                else:
                    flash('Cliente alterado para compra, mas ainda não assinou os termos. Licença será gerada após assinatura.', 'warning')
                    
            elif novo_modelo == 'comissao':
                licenca_vitalicia = obter_licenca_ativa(cliente, tipo='vitalicia')
                if licenca_vitalicia:
                    licenca_vitalicia.status = 'cancelada'
                    db.session.add(licenca_vitalicia)
                    flash('Licença vitalícia cancelada. Cliente agora opera no modelo comissão.', 'info')
                    registrar_log(f"Alterou modelo para comissão e cancelou licença vitalícia de {cliente.nome}.", "Clientes")
        
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
    
    PremioSolicitacao.query.filter_by(user_id=cliente.id).delete()
    
    db.session.delete(cliente)
    registrar_log(f"Excluiu permanentemente o cliente {nome_cliente} e todos os seus históricos.", "Segurança")
    db.session.commit()
    flash('Cliente e todas as suas faturas foram excluídos permanentemente.', 'success')
    return redirect(url_for('admin.clientes_list'))

@admin_bp.route('/pagamentos')
@admin_required
def pagamentos():
    ciclo = request.args.get('ciclo')
    
    repasse_global = db.session.query(db.func.sum(Fatura.repasse)).join(User).filter(
        User.modelo_negocio == 'comissao',
        db.or_(User.is_isento == False, User.is_isento.is_(None))
    ).scalar() or 0.0
    
    if ciclo:
        try:
            data_selecionada = datetime.strptime(ciclo, '%Y-%m-%d').date()
            dias_para_sexta = (data_selecionada.weekday() - 4) % 7
            inicio_ciclo = data_selecionada - timedelta(days=dias_para_sexta)
        except ValueError:
            hoje = datetime.now(tz_br).date()
            dias_para_sexta = (hoje.weekday() - 4) % 7
            inicio_ciclo = hoje - timedelta(days=dias_para_sexta)
            
        dias_uteis = []
        data_atual = inicio_ciclo
        while len(dias_uteis) < 5 and data_atual <= (inicio_ciclo + timedelta(days=6)):
            if data_atual.weekday() < 5:
                dias_uteis.append(data_atual)
            data_atual += timedelta(days=1)
            
        ativos_brutos = User.query.filter_by(role='cliente', status_acesso='ativo').options(joinedload(User.alocacoes)).order_by(User.nome.asc()).all()
        ativos = []
        for c in ativos_brutos:
            data_cad = c.data_cadastro.date() if c.data_cadastro else datetime.min.date()
            if data_cad <= (inicio_ciclo + timedelta(days=6)):
                ativos.append(c)
        
        user_ids = [c.id for c in ativos]
        faturas_do_ciclo = []
        if user_ids:
            faturas_do_ciclo = Fatura.query.options(joinedload(Fatura.dias)).filter(
                Fatura.user_id.in_(user_ids),
                Fatura.data_inicio == inicio_ciclo
            ).all()
            
        mapa_faturas = {f.user_id: f for f in faturas_do_ciclo}
        
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
                    if total_exigido < 0: 
                        total_exigido = 0
                    
                    if total_exigido == 0:
                        progresso_display = "Isento"
                    else:
                        progresso_display = f"{dias_enviados}/{total_exigido}"
                    
                    detalhes_corretoras[aloc.nome_corretora] = progresso_display
            else:
                status_atual = 'sem_fatura'
                for aloc in c.alocacoes:
                    detalhes_corretoras[aloc.nome_corretora] = f"0/{total_dias_brutos_da_semana}"
                
            clientes_dados.append({
                'info': c, 
                'status_semana': status_atual, 
                'inicio_ciclo': inicio_ciclo,
                'detalhes_corretoras': detalhes_corretoras,
                'fatura_id': fatura_atual.id if fatura_atual else None
            })
            
        return render_template(
            'admin/pagamentos.html', 
            clientes_dados=clientes_dados, 
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
            
            faturas_unicas = {f.user_id: f for f in todas_faturas}
            faturas_reais = [f for f in faturas_unicas.values() if not getattr(f.cliente, 'is_isento', False)]
            
            repasse_gaveta = sum(f.repasse for f in faturas_reais if getattr(f.cliente, 'modelo_negocio', 'comissao') == 'comissao')
            
            total = len(faturas_reais)
            if total > 0:
                pendentes = sum(1 for f in faturas_reais if f.status in ['pendente', 'parcial'])
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
    
    if not data_str or not ciclo_str:
        flash('Dados insuficientes para isentar o dia.', 'error')
        return redirect(url_for('admin.pagamentos'))
    
    try:
        data_alvo = datetime.strptime(data_str, '%Y-%m-%d').date()
        inicio_ciclo = datetime.strptime(ciclo_str, '%Y-%m-%d').date()
        
        # Buscar todas as faturas do ciclo atual
        faturas_ciclo = Fatura.query.filter_by(data_inicio=inicio_ciclo).all()
        if not faturas_ciclo:
            flash(f'Nenhuma fatura encontrada para o ciclo {inicio_ciclo}.', 'warning')
            return redirect(url_for('admin.pagamentos', ciclo=ciclo_str))
        
        # Coletar IDs das faturas do ciclo
        fatura_ids = [f.id for f in faturas_ciclo]
        
        # Buscar apenas os dias da data alvo que pertencem a essas faturas
        dias_afetados = FaturaDiaria.query.filter(
            FaturaDiaria.data_pregao == data_alvo,
            FaturaDiaria.fatura_id.in_(fatura_ids)
        ).all()
        
        if not dias_afetados:
            flash(f'Nenhum dia {data_alvo} encontrado para o ciclo selecionado.', 'warning')
            return redirect(url_for('admin.pagamentos', ciclo=ciclo_str))
        
        faturas_afetadas = set()
        sucesso = 0
        erros = 0
        
        for dia in dias_afetados:
            try:
                dia.zerar_valores(isentar=True)
                faturas_afetadas.add(dia.fatura_semanal)
                sucesso += 1
            except Exception as e:
                db.session.rollback()  # rollback parcial (apenas deste dia)
                erros += 1
                logger.error(f"Erro ao isentar dia {dia.id} (cliente {dia.fatura_semanal.cliente.nome}): {e}")
        
        # Recalcular totais apenas das faturas que foram modificadas com sucesso
        for fatura in faturas_afetadas:
            try:
                fatura.recalcular_totais()
            except Exception as e:
                erros += 1
                logger.error(f"Erro ao recalcular fatura {fatura.id}: {e}")
        
        db.session.commit()
        
        if sucesso > 0:
            registrar_log(f"Isentou globalmente o dia {data_alvo} para {sucesso} clientes do ciclo {inicio_ciclo}.", "Pagamentos")
            flash(f'{sucesso} cliente(s) tiveram o dia {data_alvo} isentado(s).', 'success')
        if erros > 0:
            flash(f'{erros} erro(s) ocorreram durante a operação. Verifique os logs.', 'error')
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erro fatal em isentar_dia_global: {e}")
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

@admin_bp.route('/pagamentos/isentar_ciclo/<int:fatura_id>', methods=['POST'])
@admin_required
def isentar_ciclo(fatura_id):
    fatura = Fatura.query.get_or_404(fatura_id)
    
    for dia in fatura.dias:
        dia.zerar_valores(isentar=True)
        
    fatura.recalcular_totais()
    db.session.commit()
    
    registrar_log(f"Isentou todos os dias do ciclo {fatura.data_inicio.strftime('%d/%m')} do cliente {fatura.cliente.nome}.", "Pagamentos")
    flash(f'O ciclo inteiro foi isentado com sucesso para {fatura.cliente.nome}.', 'success')
    
    return redirect(url_for('admin.pagamentos', ciclo=fatura.data_inicio.strftime('%Y-%m-%d')))

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
    
    grupos = []
    for template in templates:
        docs = DocumentoCliente.query.filter_by(template_id=template.id)\
            .join(User)\
            .options(joinedload(DocumentoCliente.cliente))\
            .order_by(DocumentoCliente.status.desc(), DocumentoCliente.data_envio.desc())\
            .all()
        if docs:
            grupos.append({
                'template': template,
                'documentos': docs
            })
    
    return render_template('admin/documentos.html', 
                           templates=templates, 
                           clientes=clientes,
                           grupos=grupos)

@admin_bp.route('/documentos/cadastrar_template', methods=['POST'])
@admin_required
def cadastrar_template():
    nome = request.form.get('nome')
    arquivo_local = request.form.get('arquivo_local')
    is_onboarding = True if request.form.get('is_onboarding') else False
    
    if not re.match(r'^[a-zA-Z0-9_.-]+\.pdf$', arquivo_local):
        flash('Nome de arquivo inválido. Use apenas letras, números, underscore, hífen e ponto, com extensão .pdf', 'error')
        return redirect(url_for('admin.documentos'))
    
    base_dir = os.path.join(current_app.root_path, 'static', 'documentos')
    caminho_completo = os.path.join(base_dir, arquivo_local)
    caminho_real = os.path.realpath(caminho_completo)
    if not caminho_real.startswith(os.path.realpath(base_dir)):
        flash('Caminho de arquivo não permitido.', 'error')
        return redirect(url_for('admin.documentos'))
    
    if not os.path.exists(caminho_real):
        flash(f'O arquivo "{arquivo_local}" não foi encontrado na pasta static/documentos/.', 'error')
        return redirect(url_for('admin.documentos'))
    
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

# ==================== ROTA DE UPLOAD (ROBÔ) ====================

@admin_bp.route('/robo/upload', methods=['GET', 'POST'])
@admin_required
@limiter.limit("3 per minute", methods=["POST"])
def upload_versao_robo():
    if request.method == 'POST':
        versao = request.form.get('versao')
        novidades = request.form.get('novidades')
        arquivo = request.files.get('arquivo')
        
        if not versao or not arquivo:
            flash("Versão e arquivo são obrigatórios.", "error")
            return redirect(url_for('admin.upload_versao_robo'))
        
        filename = arquivo.filename
        if '.' in filename:
            extensao = '.' + filename.rsplit('.', 1)[1].lower()
        else:
            extensao = ''
        
        if extensao not in ['.exe', '.ex5', '.zip']:
            flash("Tipo de arquivo inválido. Apenas .exe, .ex5 ou .zip são permitidos.", "error")
            return redirect(url_for('admin.upload_versao_robo'))
        
        try:
            upload_result = cloudinary.uploader.upload(arquivo, folder="dwcapital/robos", resource_type="raw")
            arquivo_url = upload_result.get('secure_url')
        except Exception as e:
            flash(f"Erro ao enviar arquivo: {str(e)}", "error")
            return redirect(url_for('admin.upload_versao_robo'))
        
        nova_versao = VersaoRobo(
            versao=versao,
            arquivo_url=arquivo_url,
            novidades=novidades,
            publicada=False,
            extensao=extensao
        )
        db.session.add(nova_versao)
        db.session.commit()
        
        registrar_log(f"Upload de nova versão do robô: {versao} (arquivo {filename})", "Robô")
        flash(f"Versão {versao} enviada com sucesso! Agora publique-a para ficar disponível.", "success")
        return redirect(url_for('admin.upload_versao_robo'))
    
    versoes = VersaoRobo.query.order_by(VersaoRobo.data_upload.desc()).all()
    return render_template('admin/upload_robo.html', versoes=versoes)

@admin_bp.route('/robo/publicar/<int:id>', methods=['POST'])
@admin_required
def publicar_versao_robo(id):
    versao = VersaoRobo.query.get_or_404(id)
    
    VersaoRobo.query.update({'publicada': False})
    db.session.commit()
    
    versao.publicada = True
    db.session.commit()
    
    removidos = DownloadControle.query.filter_by(versao_id=versao.id).delete()
    db.session.commit()
    
    registrar_log(f"Publicou a versão do robô: {versao.versao} (downloads anteriores removidos: {removidos})", "Robô")
    flash(f"Versão {versao.versao} agora é a versão ativa para download. Todos os clientes poderão baixá-la novamente.", "success")
    return redirect(url_for('admin.upload_versao_robo'))

# ==================== ROTAS DE LICENÇA (ADMIN) ====================

@admin_bp.route('/forcar_licenca_vitalicia/<int:id>', methods=['POST'])
@admin_required
@limiter.limit("5 per minute", key_func=lambda: request.view_args.get('id', 'global'))
def forcar_licenca_vitalicia(id):
    cliente = User.query.get_or_404(id)
    if cliente.modelo_negocio != 'compra':
        flash('Este cliente não está no modelo compra.', 'error')
        return redirect(url_for('admin.editar_cliente', id=id))
    
    if not cliente.conta_mt5:
        flash('Cliente não possui conta MT5 cadastrada. Preencha o campo antes de gerar a licença.', 'error')
        return redirect(url_for('admin.editar_cliente', id=id))
    
    licenca_existente = obter_licenca_ativa(cliente, tipo='vitalicia')
    if licenca_existente:
        licenca_existente.status = 'cancelada'
        db.session.add(licenca_existente)
    
    chave, msg, nova_licenca = gerar_licenca_vitalicia(cliente, cliente.conta_mt5)
    db.session.commit()
    
    registrar_log(f"Forçou a geração de nova licença vitalícia para {cliente.nome}. Chave: {chave}", "Clientes")
    flash(f'Licença vitalícia gerada/regenerada com sucesso! Chave: {chave}', 'success')
    return redirect(url_for('admin.editar_cliente', id=id))

# ==================== ROTA: DIREITO DE DOWNLOAD (BLOQUEIO DE ACESSO AO ROBÔ) ====================

@admin_bp.route('/download_rights', methods=['GET', 'POST'])
@admin_required
def download_rights():
    if request.method == 'POST':
        user_id = request.form.get('user_id')
        acao = request.form.get('acao')  # 'bloquear' ou 'desbloquear'
        user = User.query.get_or_404(user_id)
        if acao == 'bloquear':
            user.robot_acesso_bloqueado = True
            registrar_log(f"Bloqueou acesso ao robô (download e novas licenças) para {user.nome}", "Robô")
            flash(f'Cliente {user.nome} bloqueado com sucesso.', 'success')
        elif acao == 'desbloquear':
            user.robot_acesso_bloqueado = False
            registrar_log(f"Desbloqueou acesso ao robô (download e novas licenças) para {user.nome}", "Robô")
            flash(f'Cliente {user.nome} desbloqueado com sucesso.', 'success')
        db.session.commit()
        return redirect(url_for('admin.download_rights'))

    # GET: listar todos os clientes com paginação
    page = request.args.get('page', 1, type=int)
    per_page = 30
    clientes = User.query.filter_by(role='cliente').order_by(User.nome.asc()).paginate(page=page, per_page=per_page, error_out=False)
    return render_template('admin/download_rights.html', clientes=clientes)

# ==================== ROTA PARA JOB DE EXPIRAÇÃO ====================

@admin_bp.route('/cron/expirar_licencas', methods=['POST'])
@csrf.exempt
def cron_expirar_licencas():
    token = request.headers.get('X-Cron-Secret')
    if token != os.environ.get('CRON_SECRET'):
        return jsonify({"error": "Não autorizado"}), 403
    
    quantidade = expirar_licencas_semanais()
    registrar_log(f"Job automático: expirou {quantidade} licenças semanais.", "Sistema")
    return jsonify({"status": "ok", "expiradas": quantidade}), 200

@admin_bp.route('/cron/gerar_ciclos', methods=['POST'])
@csrf.exempt
def cron_gerar_ciclos():
    token = request.headers.get('X-Cron-Secret')
    if token != os.environ.get('CRON_SECRET'):
        return jsonify({"error": "Não autorizado"}), 403
    
    from app.services.fatura_service import auto_gerar_ciclos_em_lote
    clientes_ativos = User.query.filter_by(role='cliente', status_acesso='ativo').all()
    if clientes_ativos:
        auto_gerar_ciclos_em_lote(clientes_ativos)
        return jsonify({"status": "ok", "clientes_processados": len(clientes_ativos)}), 200
    return jsonify({"status": "ok", "clientes_processados": 0}), 200

# ==================== NOVA ROTA: HISTÓRICO DE LICENÇAS ====================

@admin_bp.route('/cliente_licencas/<int:id>')
@admin_required
def cliente_licencas(id):
    cliente = User.query.get_or_404(id)
    licencas = LicencaCliente.query.filter_by(user_id=cliente.id).order_by(LicencaCliente.data_geracao.desc()).all()
    return render_template('admin/cliente_licencas.html', cliente=cliente, licencas=licencas)

# ==================== ROTA: RELATÓRIO DE GESTÃO ====================

@admin_bp.route('/relatorio_gestao', methods=['GET'])
@admin_required
@limiter.limit("2 per minute")
def relatorio_gestao():
    from app.services.relatorio_service import gerar_relatorio_gestao

    mes = request.args.get('mes')
    ano = request.args.get('ano')
    logger.error(f"[DEBUG] Relatório: mes={mes}, ano={ano}")

    if not mes or not ano:
        logger.error("[DEBUG] Parâmetros ausentes")
        flash('Selecione o mês e o ano para gerar o relatório.', 'error')
        return redirect(url_for('admin.clientes_list'))

    try:
        mes_int = int(mes)
        ano_int = int(ano)
        if not (1 <= mes_int <= 12 and ano_int > 2000):
            logger.error(f"[DEBUG] Mês/ano inválidos: {mes_int}/{ano_int}")
            flash('Mês ou ano inválidos.', 'error')
            return redirect(url_for('admin.clientes_list'))
    except ValueError:
        logger.error("[DEBUG] ValueError ao converter")
        flash('Parâmetros inválidos.', 'error')
        return redirect(url_for('admin.clientes_list'))

    try:
        logger.error(f"[DEBUG] Chamando gerar_relatorio_gestao({mes_int}, {ano_int})")
        output = gerar_relatorio_gestao(mes_int, ano_int)
        logger.error(f"[DEBUG] Arquivo gerado: {output}")
        
        response = send_file(output, as_attachment=True, download_name=f'relatorio_gestao_{ano_int}_{mes_int:02d}.xlsx')
        
        registrar_log(f"Gerou relatório de gestão para {mes_int}/{ano_int}", "Relatórios")
        
        @response.call_on_close
        def cleanup():
            try:
                os.unlink(output)
                logger.error(f"[DEBUG] Arquivo temporário removido: {output}")
            except Exception as e:
                logger.error(f"[DEBUG] Erro ao remover arquivo: {e}")
        
        return response
    except Exception as e:
        logger.error(f"[DEBUG] Exceção capturada: {str(e)}", exc_info=True)
        flash(f'Erro ao gerar relatório: {str(e)}', 'error')
        return redirect(url_for('admin.clientes_list'))
    
# ==================== ROTAS DE GESTÃO DE PARCELAS (FASE 3) ====================

@admin_bp.route('/parcelas')
@admin_required
def parcelas():
    """Lista clientes compra com dados agregados (via indicação)."""
    status_filter = request.args.get('status', '')
    search = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    query = ParcelaCompra.query.join(User).filter(User.modelo_negocio == 'compra', User.is_indicado == True)
    
    if status_filter in ['pendente', 'pago']:
        query = query.filter(ParcelaCompra.status == status_filter)
    
    if search:
        query = query.filter(
            db.or_(
                User.nome.ilike(f'%{search}%'),
                User.cpf.ilike(f'%{search}%')
            )
        )
    
    # Busca todos os clientes da consulta (sem paginação na agregação, depois paginamos manualmente)
    clientes_agregados = _agregar_clientes_parcelas(query)
    
    # Paginação manual (pois a agregação é feita em memória)
    total = len(clientes_agregados)
    start = (page - 1) * per_page
    end = start + per_page
    clientes_paginados = clientes_agregados[start:end]
    
    # Cria objeto de paginação compatível com o template
    class Paginacao:
        def __init__(self, items, page, per_page, total):
            self.items = items
            self.page = page
            self.per_page = per_page
            self.total = total
            self.pages = (total + per_page - 1) // per_page
            self.has_prev = page > 1
            self.has_next = page < self.pages
            self.prev_num = page - 1 if self.has_prev else None
            self.next_num = page + 1 if self.has_next else None
    
    paginacao = Paginacao(clientes_paginados, page, per_page, total)
    
    return render_template('admin/parcelas.html', clientes=paginacao, status_filter=status_filter, search=search, tipo='indicacao')

@admin_bp.route('/parcelas_diretas')
@admin_required
def parcelas_diretas():
    """Lista clientes compra NÃO indicados (compra direta) com dados agregados."""
    status_filter = request.args.get('status', '')
    search = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    query = ParcelaCompra.query.join(User).filter(
        User.modelo_negocio == 'compra',
        User.is_indicado == False
    )
    
    if status_filter in ['pendente', 'pago']:
        query = query.filter(ParcelaCompra.status == status_filter)
    
    if search:
        query = query.filter(
            db.or_(
                User.nome.ilike(f'%{search}%'),
                User.cpf.ilike(f'%{search}%')
            )
        )
    
    clientes_agregados = _agregar_clientes_parcelas(query)
    
    total = len(clientes_agregados)
    start = (page - 1) * per_page
    end = start + per_page
    clientes_paginados = clientes_agregados[start:end]
    
    class Paginacao:
        def __init__(self, items, page, per_page, total):
            self.items = items
            self.page = page
            self.per_page = per_page
            self.total = total
            self.pages = (total + per_page - 1) // per_page
            self.has_prev = page > 1
            self.has_next = page < self.pages
            self.prev_num = page - 1 if self.has_prev else None
            self.next_num = page + 1 if self.has_next else None
    
    paginacao = Paginacao(clientes_paginados, page, per_page, total)
    
    return render_template('admin/parcelas.html', clientes=paginacao, status_filter=status_filter, search=search, tipo='direta')

@admin_bp.route('/parcela/pagar/<int:parcela_id>', methods=['POST'])
@admin_required
def parcela_pagar(parcela_id):
    """Marca uma parcela como paga (admin)."""
    parcela = ParcelaCompra.query.get_or_404(parcela_id)
    if parcela.status == 'pago':
        return jsonify({'success': False, 'message': 'Esta parcela já está paga.'}), 400
    else:
        parcela.status = 'pago'
        parcela.data_pagamento = datetime.now(tz_br)
        db.session.commit()
        registrar_log(f"Marcou a parcela ID {parcela.id} (ordem {parcela.ordem}, valor R${parcela.valor}) do cliente {parcela.cliente.nome} como PAGA.", "Pagamentos")
        return jsonify({'success': True, 'message': 'Parcela marcada como paga!'})

# ==================== ROTAS DE GESTÃO DE PRÊMIOS (FASE E) ====================

@admin_bp.route('/premios')
@admin_required
def premios():
    """Lista todas as solicitações de prêmio dos indicadores."""
    status_filter = request.args.get('status', '')
    page = request.args.get('page', 1, type=int)
    per_page = 30
    
    query = PremioSolicitacao.query
    if status_filter:
        query = query.filter(PremioSolicitacao.status == status_filter)
    
    solicitacoes = query.order_by(PremioSolicitacao.data_solicitacao.desc()).paginate(page=page, per_page=per_page, error_out=False)
    
    for sol in solicitacoes.items:
        sol.qtd_elegivel = contar_indicacoes_com_entrada_paga(sol.user_id)
    
    return render_template('admin/premios.html', solicitacoes=solicitacoes, status_filter=status_filter)

@admin_bp.route('/premio/processar/<int:solicitacao_id>', methods=['POST'])
@admin_required
def processar_premio(solicitacao_id):
    """Processa a solicitação de prêmio: aprovar, pagar, recusar."""
    solicitacao = PremioSolicitacao.query.get_or_404(solicitacao_id)
    acao = request.form.get('acao')
    
    if acao == 'aprovar':
        if solicitacao.status != 'pendente':
            flash('Esta solicitação não está pendente.', 'error')
            return redirect(url_for('admin.premios'))
        
        qtd = contar_indicacoes_com_entrada_paga(solicitacao.user_id)
        if qtd < 7:
            flash('O indicador não atende mais aos requisitos (menos de 7 entradas pagas).', 'error')
            return redirect(url_for('admin.premios'))
        
        solicitacao.status = 'aprovado'
        solicitacao.admin_id = current_user.id
        solicitacao.data_aprovacao = datetime.now(tz_br)
        
        if solicitacao.tipo_premio == 'dinheiro':
            solicitacao.status = 'pago'
            solicitacao.data_pagamento = datetime.now(tz_br)
        
        db.session.commit()
        
        if solicitacao.tipo_premio == 'dinheiro':
            registrar_log(f"Aprovou e pagou o prêmio de R$ {solicitacao.valor:.2f} para o indicador {solicitacao.user.nome}.", "Premios")
            flash(f'Prêmio de R$ {solicitacao.valor:.2f} aprovado e pago!', 'success')
        else:
            registrar_log(f"Aprovou a concessão da Licença Vitalícia para o indicador {solicitacao.user.nome}.", "Premios")
            flash('Licença vitalícia concedida com sucesso!', 'success')
    
    elif acao == 'recusar':
        solicitacao.status = 'recusado'
        solicitacao.admin_id = current_user.id
        solicitacao.data_aprovacao = datetime.now(tz_br)
        db.session.commit()
        registrar_log(f"Recusou a solicitação de prêmio do indicador {solicitacao.user.nome}.", "Premios")
        flash('Solicitação recusada.', 'success')
    
    else:
        flash('Ação inválida.', 'error')
    
    return redirect(url_for('admin.premios'))

# ==================== FUNÇÕES AUXILIARES ====================

def _executar_reprocessamento_por_corretora(corretora_nome):
    dias_enviados = FaturaDiaria.query.options(
        joinedload(FaturaDiaria.fatura_semanal).joinedload(Fatura.cliente)
    ).filter(
        FaturaDiaria.status == 'relatorio_enviado',
        FaturaDiaria.arquivo_pdf.isnot(None),
        FaturaDiaria.nome_corretora == corretora_nome
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
    
    registrar_log(f"Executou Batch Job: Reprocessou notas antigas ({corretora_nome}) (Sucesso: {sucesso}, Falhas: {erros}).", "Sistema")
    flash(f'Reprocessamento {corretora_nome} concluído! {sucesso} notas corrigidas ({erros} falhas).', 'success')
    
    return redirect(url_for('admin.dashboard'))

@admin_bp.route('/reprocessar_btg', methods=['GET'])
@admin_required
@limiter.limit("2 per minute")
def reprocessar_btg():
    return _executar_reprocessamento_por_corretora('BTG')

@admin_bp.route('/reprocessar_genial', methods=['GET'])
@admin_required
@limiter.limit("2 per minute")
def reprocessar_genial():
    return _executar_reprocessamento_por_corretora('GENIAL')

@admin_bp.route('/reprocessar_xp', methods=['GET'])
@admin_required
@limiter.limit("2 per minute")
def reprocessar_xp():
    return _executar_reprocessamento_por_corretora('XP')
