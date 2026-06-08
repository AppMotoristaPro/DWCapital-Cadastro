import os
import urllib.parse
from datetime import datetime, timedelta
import pytz
import logging
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, jsonify, abort
from flask_login import login_required, current_user
import cloudinary
import cloudinary.uploader
from app import db, limiter
from app.models import FaturaDiaria, Fatura, DocumentoCliente, ParcelaCompra, User, PremioSolicitacao
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload
from app.services.fatura_service import atualizar_totais_semana, auto_gerar_ciclo
from app.services.documento_service import verificar_status_documento_cliente, enviar_documento_local_com_link
from app.services.dashboard_service import obter_dados_dashboard_cliente
from app.services.pix_service import PixService
from app.utils.autentique import obter_url_visualizacao_autentique

logger = logging.getLogger(__name__)
tz_br = pytz.timezone('America/Sao_Paulo')
client_bp = Blueprint('client', __name__, url_prefix='/portal')

@client_bp.before_request
def check_paywall():
    if request.endpoint == 'client.buscar_dados_whatsapp':
        return

    if not current_user.is_authenticated:
        return
    if getattr(current_user, 'precisa_trocar_senha', False):
        return
        
    pendentes = DocumentoCliente.query.filter(
        DocumentoCliente.user_id == current_user.id,
        DocumentoCliente.status.in_(['na_fila', 'pendente', 'processando'])
    ).first()

    if pendentes:
        if request.endpoint not in ['client.assinar_termo', 'client.api_status_assinatura', 'auth.logout']:
            return redirect(url_for('client.assinar_termo'))
        return 
            
    if request.endpoint not in ['client.bloqueio_pagamento', 'client.gerar_pix_licenca', 'client.status_licenca_api', 'auth.logout']:
        if getattr(current_user, 'modelo_negocio', 'comissao') == 'compra':
            hoje = datetime.now(tz_br).date()
            parcela_pendente = ParcelaCompra.query.filter(
                ParcelaCompra.user_id == current_user.id,
                ParcelaCompra.status == 'pendente',
                ParcelaCompra.data_vencimento <= hoje
            ).order_by(ParcelaCompra.ordem.asc()).first()
            
            if parcela_pendente:
                return redirect(url_for('client.bloqueio_pagamento'))

@client_bp.route('/api/buscar_dados_whatsapp', methods=['POST'])
def buscar_dados_whatsapp():
    data = request.get_json()
    cpf_puro = ''.join(filter(str.isdigit, data.get('cpf', '')))
    
    user = User.query.filter_by(cpf=cpf_puro).first()
    if user:
        msg = f"Olá, me chamo {user.nome}. Preciso alterar minha senha, segue minhas informações:\nID: {user.id}\nCPF: {user.cpf}"
        link = f"https://wa.me/5511991167709?text={urllib.parse.quote(msg)}"
        return jsonify({"success": True, "link": link})
        
    return jsonify({"success": False, "message": "O CPF informado não foi encontrado em nossa base de dados."})

@client_bp.route('/bloqueio_pagamento')
@login_required
def bloqueio_pagamento():
    if getattr(current_user, 'modelo_negocio', 'comissao') != 'compra':
        return redirect(url_for('client.dashboard'))
    
    hoje = datetime.now(tz_br).date()
    parcela_pendente = ParcelaCompra.query.filter(
        ParcelaCompra.user_id == current_user.id,
        ParcelaCompra.status == 'pendente',
        ParcelaCompra.data_vencimento <= hoje
    ).order_by(ParcelaCompra.ordem.asc()).first()
    
    if not parcela_pendente:
        return redirect(url_for('client.dashboard'))
        
    inter_sandbox = os.environ.get('INTER_SANDBOX', 'true').lower() in ('true', '1', 't')
    return render_template('client/bloqueio_pix.html', parcela=parcela_pendente, inter_sandbox=inter_sandbox)

@client_bp.route('/faturas/gerar_pix/<int:fatura_id>', methods=['POST'])
@login_required
def gerar_pix_fatura(fatura_id):
    fatura = Fatura.query.get_or_404(fatura_id)
    if fatura.user_id != current_user.id:
        return jsonify({"success": False, "message": "Acesso negado."}), 403

    tem_notas_pendentes = any(d.status == 'pendente' for d in fatura.dias)
    if tem_notas_pendentes:
        return jsonify({"success": False, "error": "NOTAS_PENDENTES", "message": "Você possui faturas de corretagem pendentes."}), 200

    try:
        dados_pix = PixService.criar_cobranca_imediata(fatura.repasse, current_user.nome, current_user.cpf)
        fatura.txid_pix = dados_pix["txid"]
        fatura.payload_pix = dados_pix["pix_copia_e_cola"]
        db.session.commit()
        return jsonify({"success": True, "txid": fatura.txid_pix, "pix_copia_e_cola": fatura.payload_pix})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@client_bp.route('/licencas/gerar_pix/<int:parcela_id>', methods=['POST'])
@login_required
def gerar_pix_licenca(parcela_id):
    parcela = ParcelaCompra.query.get_or_404(parcela_id)
    if parcela.user_id != current_user.id:
        return jsonify({"success": False, "message": "Acesso negado."}), 403

    try:
        dados_pix = PixService.criar_cobranca_imediata(parcela.valor, current_user.nome, current_user.cpf)
        parcela.txid_pix = dados_pix["txid"]
        parcela.payload_pix = dados_pix["pix_copia_e_cola"]
        db.session.commit()
        return jsonify({"success": True, "txid": parcela.txid_pix, "pix_copia_e_cola": parcela.payload_pix})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@client_bp.route('/api/status_fatura/<int:fatura_id>')
@login_required
def status_fatura_api(fatura_id):
    fatura = Fatura.query.get_or_404(fatura_id)
    return jsonify({"pago": fatura.status == 'pago'})

@client_bp.route('/api/status_licenca/<int:parcela_id>')
@login_required
def status_licenca_api(parcela_id):
    parcela = ParcelaCompra.query.get_or_404(parcela_id)
    return jsonify({"pago": parcela.status == 'pago'})

@client_bp.route('/dashboard')
@login_required
def dashboard():
    if getattr(current_user, 'precisa_trocar_senha', False):
        return redirect(url_for('auth.forcar_troca_senha'))
    auto_gerar_ciclo(current_user)
    dados = obter_dados_dashboard_cliente(current_user.id, request.args.get('dia'), request.args.get('semana_dia'), request.args.get('ano'))
    return render_template('client/index.html', user=current_user, **dados)

@client_bp.route('/assinar')
@login_required
def assinar_termo():
    docs_na_fila = DocumentoCliente.query.filter_by(user_id=current_user.id, status='na_fila').all()
    
    for doc in docs_na_fila:
        try:
            doc.status = 'processando'
            db.session.commit()
            
            caminho_pdf = os.path.join(current_app.root_path, 'static', 'documentos', doc.template.arquivo_local)
            nome_doc = f"{doc.template.nome} - {current_user.nome}"
            
            doc_id, link = enviar_documento_local_com_link(current_user.nome, current_user.email, caminho_pdf, nome_doc)
            
            doc.autentique_document_id = doc_id
            doc.link_assinatura = link
            doc.status = 'pendente'
            db.session.commit()
        except Exception as e:
            doc.status = 'na_fila' 
            db.session.commit()
            print(f"Erro ao disparar Just-in-Time: {e}")

    pendentes = DocumentoCliente.query.filter(
        DocumentoCliente.user_id == current_user.id, 
        DocumentoCliente.status.in_(['pendente', 'processando'])
    ).options(joinedload(DocumentoCliente.template)).all()
    
    return render_template('client/assinar_termo.html', documentos=pendentes)

@client_bp.route('/api/status_assinatura')
@login_required
def api_status_assinatura():
    pendentes = DocumentoCliente.query.filter_by(user_id=current_user.id, status='pendente').all()
    all_signed = True
    for doc in pendentes:
        _, assinado = verificar_status_documento_cliente(doc.id, current_user.id)
        if not assinado:
            all_signed = False
    return jsonify({"assinado": all_signed})

@client_bp.route('/dados_pessoais')
@login_required
def dados_pessoais():
    return render_template('client/dados_pessoais.html', user=current_user)

@client_bp.route('/faturas', methods=['GET', 'POST'])
@login_required
@limiter.limit("5 per minute", methods=["POST"])
def faturas():
    auto_gerar_ciclo(current_user)
    faturas_carregadas = Fatura.query.options(joinedload(Fatura.dias)).filter_by(user_id=current_user.id).order_by(Fatura.data_inicio.desc()).all()

    for fatura in faturas_carregadas:
        if current_user.modelo_negocio == 'compra':
            subtotal = sum(dia.liquido for dia in fatura.dias if dia.status == 'relatorio_enviado')
        else:
            subtotal = sum(dia.repasse for dia in fatura.dias if dia.status == 'relatorio_enviado')
        fatura.subtotal_exibicao = subtotal

    if request.method == 'GET':
        from app.services.fatura_service import garantir_dias_faltantes_para_fatura
        houve_alteracao_global = False
        for fatura in faturas_carregadas:
            if garantir_dias_faltantes_para_fatura(current_user, fatura):
                houve_alteracao_global = True
        if houve_alteracao_global:
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()

    if request.method == 'POST':
        from app.services.nota_service import processar_upload_nota
        resultado = processar_upload_nota(
            user=current_user,
            dia_id=request.form.get('dia_id'),
            arquivo=request.files.get('relatorio_pdf'),
            senha_manual=request.form.get('senha_manual')
        )
        return jsonify(resultado)

    inter_sandbox = os.environ.get('INTER_SANDBOX', 'true').lower() in ('true', '1', 't')
    return render_template('client/faturas.html', faturas=faturas_carregadas, inter_sandbox=inter_sandbox)

@client_bp.route('/faturas/comprovante/<int:fatura_id>', methods=['POST'])
@login_required
def enviar_comprovante(fatura_id):
    fatura = Fatura.query.get_or_404(fatura_id)
    if fatura.user_id != current_user.id:
        flash('Acesso negado.', 'danger')
        return redirect(url_for('client.faturas'))
    arquivo = request.files.get('comprovante')
    if arquivo:
        try:
            res = cloudinary.uploader.upload(arquivo, folder="dwcapital/comprovantes", resource_type="image")
            fatura.comprovante_pix = res.get('secure_url')
            db.session.commit()
            flash('Comprovante enviado com sucesso!', 'success')
        except Exception as e:
            flash(f"Erro ao enviar para nuvem: {str(e)}", "danger")
    return redirect(url_for('client.faturas'))

@client_bp.route('/faturas/remover/<int:dia_id>', methods=['POST'])
@login_required
def remover_fatura(dia_id):
    dia = FaturaDiaria.query.get_or_404(dia_id)
    if dia.fatura_semanal.user_id != current_user.id:
        flash('Acesso negado.', 'danger')
        return redirect(url_for('client.faturas'))
    dia.zerar_valores(isentar=False)
    db.session.commit()
    atualizar_totais_semana(dia.fatura_semanal)
    return redirect(url_for('client.faturas'))

@client_bp.route('/documentos')
@login_required
def documentos():
    meus_docs = DocumentoCliente.query.filter_by(user_id=current_user.id, status='assinado').options(joinedload(DocumentoCliente.template)).order_by(DocumentoCliente.data_envio.desc()).all()
    return render_template('client/documentos.html', documentos=meus_docs)

@client_bp.route('/documentos/visualizar/<int:doc_id>')
@login_required
def visualizar_documento(doc_id):
    doc = DocumentoCliente.query.get_or_404(doc_id)
    if doc.user_id != current_user.id:
        abort(403)

    if doc.status != 'assinado':
        flash('Este documento ainda não foi assinado.', 'warning')
        return redirect(url_for('client.documentos'))

    if doc.autentique_document_id:
        url = obter_url_visualizacao_autentique(doc.autentique_document_id)
        if doc.link_assinatura != url:
            doc.link_assinatura = url
            db.session.commit()
        return redirect(url)

    flash('Não foi possível localizar o documento. Entre em contato com o suporte.', 'error')
    return redirect(url_for('client.documentos'))

@client_bp.route('/api/status_documento/<int:doc_id>')
@login_required
def api_status_documento(doc_id):
    autorizado, assinado = verificar_status_documento_cliente(doc_id, current_user.id)
    if not autorizado:
        return jsonify({"assinado": False}), 403
    return jsonify({"assinado": assinado})

# ==================== ROTA DE EXPLICAÇÃO DO DASHBOARD ====================

@client_bp.route('/api/explicacao_dashboard', methods=['GET'])
@login_required
def api_explicacao_dashboard():
    """Retorna os dados diários (bruto, custos, líquido, IRRF) para explicar os resultados."""
    filtro_dia = request.args.get('dia')
    filtro_semana_dia = request.args.get('semana_dia')
    filtro_ano = request.args.get('ano')
    
    faturas_base = Fatura.query.filter_by(user_id=current_user.id).options(joinedload(Fatura.dias))
    
    if filtro_dia:
        dt_dia = datetime.strptime(filtro_dia, '%Y-%m-%d').date()
        faturas = faturas_base.filter(Fatura.data_inicio <= dt_dia, Fatura.data_fim >= dt_dia).all()
        periodo = f"Dia {dt_dia.strftime('%d/%m/%Y')}"
    elif filtro_semana_dia:
        dt_ref = datetime.strptime(filtro_semana_dia, '%Y-%m-%d').date()
        dias_para_sexta = (dt_ref.weekday() - 4) % 7
        dt_inicio_sem = dt_ref - timedelta(days=dias_para_sexta)
        dt_fim_sem = dt_inicio_sem + timedelta(days=6)
        faturas = faturas_base.filter(Fatura.data_inicio >= dt_inicio_sem, Fatura.data_inicio <= dt_fim_sem).all()
        periodo = f"Ciclo {dt_inicio_sem.strftime('%d/%m/%Y')} a {dt_fim_sem.strftime('%d/%m/%Y')}"
    elif filtro_ano:
        ano = int(filtro_ano)
        dt_inicio_ano = datetime(ano, 1, 1).date()
        dt_fim_ano = datetime(ano, 12, 31).date()
        faturas = faturas_base.filter(Fatura.data_inicio >= dt_inicio_ano, Fatura.data_inicio <= dt_fim_ano).all()
        periodo = f"Ano {ano}"
    else:
        # CORREÇÃO: comportamento igual ao dashboard – pegar apenas a última fatura (última semana)
        ultima_fatura = faturas_base.order_by(Fatura.data_inicio.desc()).first()
        if ultima_fatura:
            faturas = [ultima_fatura]
            periodo = f"Semana de {ultima_fatura.data_inicio.strftime('%d/%m/%Y')} a {ultima_fatura.data_fim.strftime('%d/%m/%Y')}"
        else:
            faturas = []
            periodo = "Nenhuma fatura encontrada"
    
    dias = []
    totais = {'bruto': 0.0, 'liquido': 0.0, 'repasse': 0.0}
    is_comissao = (current_user.modelo_negocio != 'compra' and not current_user.is_isento)
    
    for fatura in faturas:
        for dia in fatura.dias:
            if dia.status != 'relatorio_enviado':
                continue
            # Cálculo dos custos (taxas B3 + IRRF1)
            custos = (dia.taxas_b3 or 0.0) + (dia.irrf_1 or 0.0)
            # CORREÇÃO: Performance Bruta usa liquido_pregao (igual ao card)
            liquido_pregao = dia.liquido_pregao or 0.0
            if liquido_pregao > 0:
                irrf_19 = liquido_pregao * 0.19
            else:
                irrf_19 = 0.0
            liquido_real = liquido_pregao - irrf_19
            if is_comissao:
                repasse = (dia.repasse or 0.0)
            else:
                repasse = 0.0
            
            dias.append({
                'data': dia.data_pregao.isoformat(),
                'data_formatada': dia.data_pregao.strftime('%d/%m/%Y'),
                'bruto': liquido_pregao,  # Agora é o mesmo que o card (líquido do pregão)
                'custos_b3_irrf1': custos,
                'liquido_pregao': liquido_pregao,
                'irrf_19': irrf_19,
                'liquido': liquido_real,
                'repasse': repasse,
                'is_comissao': is_comissao
            })
            totais['bruto'] += liquido_pregao
            totais['liquido'] += liquido_real
            totais['repasse'] += repasse
    
    return jsonify({
        'periodo': periodo,
        'dias': dias,
        'totais': totais,
        'is_isento': current_user.is_isento,
        'modelo_negocio': current_user.modelo_negocio
    })

@client_bp.route('/faturas/nao_operei_html/<int:dia_id>', methods=['POST'])
@login_required
@limiter.limit("5 per minute")
def nao_operei_html(dia_id):
    dia = FaturaDiaria.query.get_or_404(dia_id)
    if dia.fatura_semanal.user_id != current_user.id:
        return jsonify({'success': False, 'error': 'Acesso negado.'}), 403

    if dia.status != 'pendente':
        return jsonify({'success': False, 'error': 'Dia já processado.'}), 400

    arquivo = request.files.get('relatorio_html')
    if not arquivo or not arquivo.filename.endswith(('.html', '.htm')):
        return jsonify({'success': False, 'error': 'Arquivo HTML inválido.'}), 400

    conteudo = arquivo.read()
    from app.services.html_relatorio_service import validar_estrutura_html_mt5, extrair_datas_operacoes

    # 1. Validar estrutura
    valido, msg = validar_estrutura_html_mt5(conteudo)
    if not valido:
        return jsonify({'success': False, 'error': 'ESTRUTURA_INVALIDA', 'message': msg}), 400

    # 2. Extrair datas das operações (apenas Posições e Transações)
    datas_operacoes = extrair_datas_operacoes(conteudo)
    data_alvo_str = dia.data_pregao.isoformat()

    # 3. Verificar se há operações em datas diferentes da data alvo
    datas_erradas = [d for d in datas_operacoes if d != data_alvo_str]
    if datas_erradas:
        return jsonify({
            'success': False,
            'error': 'DATAS_DIFERENTES',
            'message': f'O relatório contém operações em outras datas: {", ".join(datas_erradas)}. Gere um relatório apenas para o dia {data_alvo_str}.'
        }), 400

    # 4. Verificar se há operações exatamente na data alvo
    teve_operacao = data_alvo_str in datas_operacoes

    # 5. Upload do HTML para o Cloudinary
    from io import BytesIO
    arquivo_stream = BytesIO(conteudo)
    arquivo_stream.name = arquivo.filename
    try:
        upload_result = cloudinary.uploader.upload(
            arquivo_stream,
            folder="dwcapital/relatorios_nao_operei",
            resource_type="raw",
            public_id=f"nao_operei_{current_user.id}_{dia.id}_{dia.data_pregao.isoformat()}"
        )
        relatorio_url = upload_result.get('secure_url')
    except Exception as e:
        return jsonify({'success': False, 'error': 'UPLOAD_FAIL', 'message': str(e)}), 500

    # 6. Atualizar o dia
    dia.relatorio_html_url = relatorio_url
    dia.motivo_isencao = 'nao_operou'
    dia.operacao_detectada = teve_operacao
    dia.is_isento = True
    dia.status = 'isento'
    dia.zerar_valores(isentar=True)
    db.session.commit()
    atualizar_totais_semana(dia.fatura_semanal)

    if teve_operacao:
        return jsonify({'success': True, 'warning': 'Dia isentado, mas o sistema identificou operações neste dia. O relatório será auditado pelo administrador.'})
    else:
        return jsonify({'success': True, 'message': 'Dia isentado com sucesso!'})

@client_bp.route('/ajuda')
@login_required
def ajuda():
    msg_suporte = f"Olá, me chamo {current_user.nome}. Preciso de ajuda, segue minhas informações:\nID: {current_user.id}\nCPF: {current_user.cpf}"
    msg_suporte_encoded = urllib.parse.quote(msg_suporte)
    
    return render_template('client/ajuda.html', 
                           link_suporte=f"https://wa.me/5511991167709?text={msg_suporte_encoded}",
                           link_comercial=f"https://wa.me/5511920504850?text={msg_suporte_encoded}")