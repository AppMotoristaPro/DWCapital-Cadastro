import os
import urllib.parse
from datetime import datetime, timedelta
import pytz
import logging
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, jsonify, abort, session
from flask_login import login_required, current_user
import cloudinary
import cloudinary.uploader
from app import db, limiter
from app.models import FaturaDiaria, Fatura, DocumentoCliente, ParcelaCompra, User, ContaMT5Cliente, AlocacaoCorretora
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload
from app.services.fatura_service import atualizar_totais_semana, auto_gerar_ciclo, modelo_para_fatura
from app.services.documento_service import verificar_status_documento_cliente, enviar_documento_local_com_link
from app.services.dashboard_service import obter_dados_dashboard_cliente
from app.services.pix_service import PixService
from app.utils.autentique import obter_url_visualizacao_autentique
from app.services.parcela_service import todas_parcelas_pagas, gerar_parcelas_para_conta, tem_parcelas_pendentes_por_conta
from app.services.licenca_service import obter_licenca_ativa_por_conta

logger = logging.getLogger(__name__)
tz_br = pytz.timezone('America/Sao_Paulo')
client_bp = Blueprint('client', __name__, url_prefix='/portal')


# ==================== FUNÇÃO AUXILIAR ====================
def precisa_gerar_vitalicia_aviso(user):
    """Verifica se o usuário (compra) quitou todas as parcelas e ainda não possui licença vitalícia para NENHUMA conta."""
    if user.modelo_negocio != 'compra':
        return False
    if not todas_parcelas_pagas(user.id):
        return False
    from app.models import LicencaCliente
    tem_vitalicia = LicencaCliente.query.filter_by(
        user_id=user.id, tipo='vitalicia', status='ativa'
    ).first()
    if tem_vitalicia:
        return False
    if user.produto_vitalicio_id:
        return False
    return True


# ==================== BEFORE_REQUEST ====================
@client_bp.before_request
def check_paywall():
    """Verifica pendências: documentos, parcelas (compra) e agora setup para comissionados novos."""
    if request.endpoint == 'client.buscar_dados_whatsapp':
        return

    if not current_user.is_authenticated:
        return
    if getattr(current_user, 'precisa_trocar_senha', False):
        return

    # 1. Bloqueio por documentos pendentes
    pendentes = DocumentoCliente.query.filter(
        DocumentoCliente.user_id == current_user.id,
        DocumentoCliente.status.in_(['na_fila', 'pendente', 'processando'])
    ).first()
    if pendentes:
        if request.endpoint not in ['client.assinar_termo', 'client.api_status_assinatura', 'auth.logout']:
            return redirect(url_for('client.assinar_termo'))
        return

    # 2. Bloqueio por setup não pago (apenas para clientes comissionados novos)
    if (current_user.modelo_negocio == 'comissao' and 
        not current_user.setup_pago and
        current_user.status_acesso == 'ativo'):
        if request.endpoint not in ['client.pagamento_setup', 'client.gerar_pix_setup', 'client.status_setup', 'auth.logout']:
            return redirect(url_for('client.pagamento_setup'))

    # 3. Bloqueio por parcelas de compra (modelo compra)
    if request.endpoint not in ['client.bloqueio_pagamento', 'client.gerar_pix_licenca', 'client.status_licenca_api', 'auth.logout', 'client.fechar_aviso_vitalicia']:
        if getattr(current_user, 'modelo_negocio', 'comissao') == 'compra':
            hoje = datetime.now(tz_br).date()
            parcela_pendente = ParcelaCompra.query.filter(
                ParcelaCompra.user_id == current_user.id,
                ParcelaCompra.status == 'pendente',
                ParcelaCompra.data_vencimento <= hoje
            ).order_by(ParcelaCompra.ordem.asc()).first()
            if parcela_pendente:
                return redirect(url_for('client.bloqueio_pagamento'))

    # 4. Verificação para exibir modal de aviso de licença vitalícia
    if current_user.is_authenticated and not getattr(current_user, 'precisa_trocar_senha', False):
        if precisa_gerar_vitalicia_aviso(current_user):
            session['mostrar_aviso_vitalicia'] = True
        else:
            session.pop('mostrar_aviso_vitalicia', None)


# ==================== SETUP (taxa única) ====================
@client_bp.route('/setup')
@login_required
def pagamento_setup():
    if current_user.setup_pago:
        return redirect(url_for('client.dashboard'))
    inter_sandbox = os.environ.get('INTER_SANDBOX', 'true').lower() in ('true', '1', 't')
    return render_template('client/setup_pagamento.html', inter_sandbox=inter_sandbox)


@client_bp.route('/setup/gerar_pix', methods=['POST'])
@login_required
def gerar_pix_setup():
    if current_user.setup_pago:
        return jsonify({"success": False, "message": "Setup já foi pago."}), 400
    try:
        dados_pix = PixService.criar_cobranca_imediata(399.90, current_user.nome, current_user.cpf)
        current_user.setup_txid = dados_pix["txid"]
        current_user.setup_payload = dados_pix["pix_copia_e_cola"]
        db.session.commit()
        return jsonify({"success": True, "txid": dados_pix["txid"], "pix_copia_e_cola": dados_pix["pix_copia_e_cola"]})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@client_bp.route('/setup/status')
@login_required
def status_setup():
    return jsonify({"pago": current_user.setup_pago})


# ==================== NOTIFICAÇÕES ====================
@client_bp.route('/api/notificacoes')
@login_required
def api_notificacoes():
    """Retorna as notificações não lidas do cliente."""
    from app.models import Notificacao
    notificacoes = Notificacao.query.filter_by(
        user_id=current_user.id, 
        lida=False
    ).order_by(Notificacao.data_criacao.desc()).all()
    
    return jsonify([{
        'id': n.id,
        'titulo': n.titulo,
        'mensagem': n.mensagem,
        'link': n.link,
        'data': n.data_criacao.strftime('%d/%m/%Y')
    } for n in notificacoes])


@client_bp.route('/api/notificacao/marcar_lida/<int:notif_id>', methods=['POST'])
@login_required
def marcar_notificacao_lida(notif_id):
    """Marca uma notificação como lida."""
    from app.models import Notificacao
    notif = Notificacao.query.get_or_404(notif_id)
    if notif.user_id != current_user.id:
        return jsonify({"error": "Não autorizado"}), 403
    notif.lida = True
    db.session.commit()
    return jsonify({"success": True})


# ==================== COMPRA DE ROBÔ ====================
@client_bp.route('/comprar_robo', methods=['GET', 'POST'])
@login_required
def comprar_robo():
    from app.services.parcela_service import gerar_parcelas_compra_unificado
    from app.models import Notificacao

    if current_user.modelo_negocio == 'compra':
        flash('Você já está no modelo de compra.', 'info')
        return redirect(url_for('client.dashboard'))
    
    if request.method == 'POST':
        current_user.modelo_negocio = 'compra'
        current_user.data_migracao_compra = datetime.now(tz_br)
        parcelas = gerar_parcelas_compra_unificado(current_user.id)
        db.session.add_all(parcelas)
        Notificacao.query.filter_by(user_id=current_user.id, tipo='migracao').update({'lida': True})
        db.session.commit()
        flash('Parabéns! Agora você é um cliente compra. As parcelas foram geradas e o acesso ao robô será liberado após o pagamento da entrada.', 'success')
        return redirect(url_for('client.dashboard'))
    
    return render_template('client/comprar_robo.html')


# ==================== COMPRA DE LICENÇA POR CONTA MT5 ====================
@client_bp.route('/comprar_licenca_conta/<int:conta_id>', methods=['GET', 'POST'])
@login_required
def comprar_licenca_conta(conta_id):
    """
    Permite que o cliente compre uma licença para uma conta MT5 específica.
    Se o cliente ainda for comissão, migra para compra e marca APENAS a conta selecionada como comprada.
    As demais contas ficam com licenca_comprada = False.
    GET: exibe página de confirmação.
    POST: gera as 10 parcelas e marca a conta como licenca_comprada = True.
    """
    conta = ContaMT5Cliente.query.filter_by(id=conta_id, user_id=current_user.id, ativo=True).first()
    if not conta:
        flash('Conta MT5 não encontrada ou inativa.', 'error')
        return redirect(url_for('client.minhas_contas'))

    # Verifica se a conta já possui parcelas
    from app.services.parcela_service import parcelas_por_conta
    parcelas_existentes = parcelas_por_conta(conta.id)
    if parcelas_existentes:
        flash('Esta conta já possui parcelas geradas. Verifique o status no seu extrato.', 'warning')
        return redirect(url_for('client.faturas'))

    # Verifica se já existe licença vitalícia ativa para esta conta
    licenca_vital = obter_licenca_ativa_por_conta(conta.id, tipo='vitalicia')
    if licenca_vital:
        flash('Esta conta já possui licença vitalícia ativa.', 'info')
        return redirect(url_for('client.faturas'))

    if request.method == 'POST':
        try:
            from app.services.parcela_service import gerar_parcelas_para_conta

            # ===== SE O CLIENTE AINDA FOR COMISSÃO, MIGRA PARA COMPRA =====
            if current_user.modelo_negocio == 'comissao':
                current_user.modelo_negocio = 'compra'
                current_user.data_migracao_compra = datetime.now(tz_br)

                # ===== CORREÇÃO ETAPA 5: Marcar APENAS a conta selecionada como comprada =====
                # Busca todas as contas ativas do cliente (exceto a selecionada)
                outras_contas = ContaMT5Cliente.query.filter(
                    ContaMT5Cliente.user_id == current_user.id,
                    ContaMT5Cliente.id != conta.id,
                    ContaMT5Cliente.ativo == True
                ).all()

                # Desmarca a licença comprada para as demais contas
                for outra in outras_contas:
                    outra.licenca_comprada = False
                    db.session.add(outra)

                # Marca a conta selecionada como comprada
                conta.licenca_comprada = True
                db.session.add(conta)

            # Gera as parcelas para a conta (isso já define licenca_comprada = True novamente, mas já está True)
            parcelas = gerar_parcelas_para_conta(conta.id)
            db.session.add_all(parcelas)
            db.session.commit()

            flash(f'Compra realizada com sucesso! Foram geradas 10 parcelas para a conta {conta.numero_conta}. A primeira parcela vence hoje.', 'success')
            return redirect(url_for('client.faturas'))
        except ValueError as e:
            flash(str(e), 'error')
            return redirect(url_for('client.minhas_contas'))
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao gerar parcelas: {str(e)}', 'error')
            return redirect(url_for('client.minhas_contas'))

    # GET: exibe página de confirmação
    return render_template('client/comprar_licenca_conta.html', conta=conta)

# ==================== OUTRAS ROTAS ====================
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


@client_bp.route('/fechar_aviso_vitalicia', methods=['POST'])
@login_required
def fechar_aviso_vitalicia():
    session.pop('mostrar_aviso_vitalicia', None)
    return jsonify({"success": True})


@client_bp.route('/dashboard')
@login_required
def dashboard():
    if getattr(current_user, 'precisa_trocar_senha', False):
        return redirect(url_for('auth.forcar_troca_senha'))
    auto_gerar_ciclo(current_user)
    dados = obter_dados_dashboard_cliente(current_user.id, request.args.get('dia'), request.args.get('semana_dia'), request.args.get('ano'))
    mostrar_aviso = session.get('mostrar_aviso_vitalicia', False)
    return render_template('client/index.html', user=current_user, mostrar_aviso_vitalicia=mostrar_aviso, **dados)


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
        modelo = modelo_para_fatura(current_user, fatura.data_inicio)
        if modelo == 'compra':
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
    
    todas_parcelas_quitadas = False
    if current_user.modelo_negocio == 'compra':
        todas_parcelas_quitadas = todas_parcelas_pagas(current_user.id)
    
    from app.services.conta_mt5_service import listar_contas
    contas_ativas = listar_contas(current_user.id, apenas_ativas=True)
    
    return render_template('client/faturas.html', 
                           faturas=faturas_carregadas, 
                           inter_sandbox=inter_sandbox,
                           todas_parcelas_quitadas=todas_parcelas_quitadas,
                           contas_ativas=contas_ativas)


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


@client_bp.route('/api/explicacao_dashboard', methods=['GET'])
@login_required
def api_explicacao_dashboard():
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
        ultima_fatura = faturas_base.order_by(Fatura.data_inicio.desc()).first()
        if ultima_fatura:
            faturas = [ultima_fatura]
            periodo = f"Semana de {ultima_fatura.data_inicio.strftime('%d/%m/%Y')} a {ultima_fatura.data_fim.strftime('%d/%m/%Y')}"
        else:
            faturas = []
            periodo = "Nenhuma fatura encontrada"
    dias = []
    totais = {'bruto': 0.0, 'liquido': 0.0, 'repasse': 0.0}
    for fatura in faturas:
        modelo = modelo_para_fatura(current_user, fatura.data_inicio)
        for dia in fatura.dias:
            if dia.status != 'relatorio_enviado':
                continue
            custos = (dia.taxas_b3 or 0.0) + (dia.irrf_1 or 0.0)
            liquido_pregao = dia.liquido_pregao or 0.0
            if liquido_pregao > 0:
                irrf_19 = liquido_pregao * 0.19
            else:
                irrf_19 = 0.0
            liquido_real = liquido_pregao - irrf_19
            if modelo == 'comissao' and not current_user.is_isento:
                repasse = (dia.repasse or 0.0)
            else:
                repasse = 0.0
            dias.append({
                'data': dia.data_pregao.isoformat(),
                'data_formatada': dia.data_pregao.strftime('%d/%m/%Y'),
                'bruto': liquido_pregao,
                'custos_b3_irrf1': custos,
                'liquido_pregao': liquido_pregao,
                'irrf_19': irrf_19,
                'liquido': liquido_real,
                'repasse': repasse,
                'is_comissao': (modelo == 'comissao')
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


# ==================== MÚLTIPLAS CONTAS MT5 ====================
from app.services.conta_mt5_service import (
    listar_contas, adicionar_conta, atualizar_conta, desativar_conta,
    obter_conta, validar_numero_conta, contar_contas_ativas,
    marcar_licenca_comprada, verificar_licenca_comprada  # <-- NOVAS
)

@client_bp.route('/minhas_contas')
@login_required
def minhas_contas():
    """Página para gerenciar as contas MT5 do cliente."""
    contas = ContaMT5Cliente.query.filter_by(
        user_id=current_user.id
    ).options(
        joinedload(ContaMT5Cliente.parcelas),
        joinedload(ContaMT5Cliente.licencas)
    ).order_by(ContaMT5Cliente.data_cadastro.desc()).all()
    return render_template('client/minhas_contas.html', contas=contas)


@client_bp.route('/api/contas', methods=['GET'])
@login_required
def api_listar_contas():
    """Retorna as contas ativas do cliente em JSON (para selects dinâmicos)."""
    contas = listar_contas(current_user.id, apenas_ativas=True)
    return jsonify([{
        'id': c.id,
        'numero_conta': c.numero_conta,
        'nome_corretora': c.nome_corretora,
        'capital_alocado': c.capital_alocado,
        'bloqueada': c.bloqueada
    } for c in contas])


@client_bp.route('/api/contas', methods=['POST'])
@login_required
@limiter.limit("10 per minute")
def api_adicionar_conta():
    """Adiciona uma nova conta MT5 e regera os ciclos de faturamento APENAS para a nova alocação."""
    data = request.get_json()
    numero_conta = data.get('numero_conta', '').strip()
    nome_corretora = data.get('nome_corretora', '').strip().upper()
    capital_alocado = float(data.get('capital_alocado', 0))

    if not validar_numero_conta(numero_conta):
        return jsonify({'success': False, 'message': 'Número da conta inválido. Use apenas números.'}), 400

    if nome_corretora not in ['GENIAL', 'BTG', 'XP']:
        return jsonify({'success': False, 'message': 'Corretora inválida.'}), 400

    if capital_alocado < 0:
        return jsonify({'success': False, 'message': 'Capital alocado não pode ser negativo.'}), 400

    try:
        nova = adicionar_conta(current_user.id, numero_conta, nome_corretora, capital_alocado)
        
        # Busca a alocação recém-criada
        nova_alocacao = AlocacaoCorretora.query.filter_by(
            user_id=current_user.id,
            nome_corretora=nome_corretora
        ).first()
        
        # Gera os ciclos apenas para a nova alocação
        if nova_alocacao:
            auto_gerar_ciclo(current_user, alocacoes_especificas=[nova_alocacao])
        
        return jsonify({'success': True, 'conta': {
            'id': nova.id,
            'numero_conta': nova.numero_conta,
            'nome_corretora': nova.nome_corretora,
            'capital_alocado': nova.capital_alocado,
            'bloqueada': nova.bloqueada
        }})
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400


@client_bp.route('/api/contas/<int:conta_id>', methods=['PUT'])
@login_required
def api_atualizar_conta(conta_id):
    """Atualiza capital alocado e/ou corretora de uma conta (cliente logado)."""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'Dados não enviados.'}), 400

    capital_alocado = data.get('capital_alocado')
    nome_corretora = data.get('nome_corretora')

    kwargs = {}
    if capital_alocado is not None:
        try:
            capital = float(capital_alocado)
            if capital < 0:
                return jsonify({'success': False, 'message': 'Capital não pode ser negativo.'}), 400
            kwargs['capital_alocado'] = capital
        except (TypeError, ValueError):
            return jsonify({'success': False, 'message': 'Valor de capital inválido.'}), 400

    if nome_corretora:
        nome_corretora = nome_corretora.upper()
        if nome_corretora not in ['GENIAL', 'BTG', 'XP']:
            return jsonify({'success': False, 'message': 'Corretora inválida.'}), 400
        kwargs['nome_corretora'] = nome_corretora

    if not kwargs:
        return jsonify({'success': False, 'message': 'Nenhum campo para atualizar.'}), 400

    try:
        atualizar_conta(conta_id, current_user.id, **kwargs)
        return jsonify({'success': True, 'message': 'Conta atualizada com sucesso.'})
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 404
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro interno: {str(e)}'}), 500


@client_bp.route('/api/contas/<int:conta_id>', methods=['DELETE'])
@login_required
def api_desativar_conta(conta_id):
    """Desativa uma conta (não exclui fisicamente)."""
    try:
        desativar_conta(conta_id, current_user.id)
        return jsonify({'success': True})
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 404


@client_bp.route('/ajuda')
@login_required
def ajuda():
    msg_suporte = f"Olá, me chamo {current_user.nome}. Preciso de ajuda, segue minhas informações:\nID: {current_user.id}\nCPF: {current_user.cpf}"
    msg_suporte_encoded = urllib.parse.quote(msg_suporte)
    return render_template('client/ajuda.html',
                           link_suporte=f"https://wa.me/5511991167709?text={msg_suporte_encoded}",
                           link_comercial=f"https://wa.me/5511920504850?text={msg_suporte_encoded}")