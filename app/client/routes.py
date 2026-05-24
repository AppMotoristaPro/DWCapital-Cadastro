import os
import urllib.parse
from datetime import datetime, timedelta
import pytz
import logging
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, jsonify, session, abort
from flask_login import login_required, current_user
import cloudinary.uploader
from werkzeug.utils import secure_filename
from app import db
from app.models import FaturaDiaria, Fatura, DocumentoCliente, ParcelaCompra, DocumentoTemplate, User
from app.utils.parsers.gerenciador_pdf import processar_pdf
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload
from app.services.fatura_service import atualizar_totais_semana, auto_gerar_ciclo
from app.services.documento_service import disparar_unico, verificar_status_documento_cliente, enviar_documento_local_com_link
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
def faturas():
    auto_gerar_ciclo(current_user)
    faturas_carregadas = Fatura.query.options(joinedload(Fatura.dias)).filter_by(user_id=current_user.id).order_by(Fatura.data_inicio.desc()).all()

    if request.method == 'GET':
        houve_alteracao = False
        data_cadastro = current_user.data_cadastro.date() if current_user.data_cadastro else datetime.min.date()
        for fatura in faturas_carregadas:
            for dia in list(fatura.dias):
                if dia.data_pregao.weekday() >= 5:
                    db.session.delete(dia)
                    houve_alteracao = True
            datas_da_semana = []
            data_atual = fatura.data_inicio
            
            while len(datas_da_semana) < 5 and data_atual <= fatura.data_fim:
                if data_atual.weekday() < 5:
                    datas_da_semana.append(data_atual)
                data_atual += timedelta(days=1)
                
            dias_existentes = { (d.data_pregao, d.nome_corretora) for d in fatura.dias }
            
            for data in datas_da_semana:
                for alocacao in current_user.alocacoes:
                    if (data, alocacao.nome_corretora) not in dias_existentes:
                        is_isento = data < data_cadastro
                        status_dia = 'isento' if is_isento else 'pendente'
                        
                        novo_dia = FaturaDiaria(fatura_id=fatura.id, data_pregao=data, nome_corretora=alocacao.nome_corretora, status=status_dia, is_isento=is_isento)
                        db.session.add(novo_dia)
                        houve_alteracao = True
                        
        if houve_alteracao:
            try: db.session.commit()
            except IntegrityError: db.session.rollback()

    if request.method == 'POST':
        dia_id = request.form.get('dia_id')
        senha_manual = request.form.get('senha_manual')
        arquivo = request.files.get('relatorio_pdf')
        dia = FaturaDiaria.query.get(dia_id)
        if not dia or dia.fatura_semanal.user_id != current_user.id:
            return jsonify({'success': False, 'error': 'ERRO_SEGURANCA', 'message': 'Acesso negado.'})
        if arquivo and arquivo.filename:
            nome_seguro = secure_filename(arquivo.filename)
            upload_folder = os.path.join(current_app.root_path, 'static', 'uploads')
            os.makedirs(upload_folder, exist_ok=True)
            file_path = os.path.join(upload_folder, nome_seguro)
            arquivo.save(file_path)
            try:
                dados = processar_pdf(file_path, dia.nome_corretora, current_user.cpf, senha_manual)
                if not dados:
                    if os.path.exists(file_path): os.remove(file_path)
                    return jsonify({'success': False, 'error': 'RELATORIO_INVALIDO', 'message': 'Não foi possível ler os dados do PDF.'})
                upload_res = cloudinary.uploader.upload(file_path, folder="dwcapital/relatorios")
                dia.arquivo_pdf = upload_res.get('secure_url')
                dia.bruto = dados.get('bruto')
                dia.taxas_b3 = dados.get('taxas_b3')
                dia.irrf_1 = dados.get('irrf_1')
                dia.liquido_pregao = dados.get('liquido_pregao')
                dia.irrf_19 = dados.get('irrf_19')
                dia.liquido = dados.get('liquido_dia')
                if getattr(current_user, 'is_isento', False): dia.repasse = 0.0
                else: dia.repasse = dados.get('repasse_dw')
                dia.status = 'relatorio_enviado'
                db.session.commit()
                atualizar_totais_semana(dia.fatura_semanal)
                if os.path.exists(file_path): os.remove(file_path)
                return jsonify({'success': True})
            except Exception as e:
                if os.path.exists(file_path): os.remove(file_path)
                if "SENHA_INCORRETA" in str(e): return jsonify({'success': False, 'error': 'REQUER_SENHA'})
                if "PDF_INCOMPATIVEL" in str(e): return jsonify({'success': False, 'error': 'RELATORIO_INVALIDO', 'message': str(e).split("PDF_INCOMPATIVEL: ")[-1]})
                return jsonify({'success': False, 'error': 'ERRO_TECNICO', 'message': str(e)})

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
    meus_docs = DocumentoCliente.query.filter_by(user_id=current_user.id, status='assinado').options(joinedload(DocumentoCliente.template)).order_by(DocumentoCliente.data_assinatura.desc()).all()
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

    # Se já tem link salvo (da criação ou de visualização anterior), usa ele
    if doc.link_assinatura:
        return redirect(doc.link_assinatura)

    # Se não tem link, monta a URL usando o autentique_document_id
    if doc.autentique_document_id:
        url = obter_url_visualizacao_autentique(doc.autentique_document_id)
        # Salva para próximas visualizações
        doc.link_assinatura = url
        db.session.commit()
        return redirect(url)

    flash('Não foi possível localizar o documento. Entre em contato com o suporte.', 'error')
    return redirect(url_for('client.documentos'))

@client_bp.route('/api/status_documento/<int:doc_id>')
@login_required
def api_status_documento(doc_id):
    autorizado, assinado = verificar_status_documento_cliente(doc_id, current_user.id)
    if not autorizado: return jsonify({"assinado": False}), 403
    return jsonify({"assinado": assinado})

@client_bp.route('/ajuda')
@login_required
def ajuda():
    msg_suporte = f"Olá, me chamo {current_user.nome}. Preciso de ajuda, segue minhas informações:\nID: {current_user.id}\nCPF: {current_user.cpf}"
    msg_suporte_encoded = urllib.parse.quote(msg_suporte)
    
    return render_template('client/ajuda.html', 
                           link_suporte=f"https://wa.me/5511991167709?text={msg_suporte_encoded}",
                           link_comercial=f"https://wa.me/5511920504850?text={msg_suporte_encoded}")
