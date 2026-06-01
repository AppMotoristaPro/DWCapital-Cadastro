import os
import urllib.parse
from datetime import datetime, timedelta
import pytz
import logging
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, jsonify, session, abort, send_file
from flask_login import login_required, current_user
import cloudinary.uploader
from werkzeug.utils import secure_filename
import requests
import io
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
from app.services.robo_service import versao_atual, liberado_para_download, registrar_download, historico_downloads_cliente
from app.services.licenca_service import (
    verificar_condicoes_comissao,
    gerar_licenca_comissao,
    gerar_licenca_vitalicia,
    obter_licenca_ativa,
    salvar_conta_mt5_e_gerar_vitalicia_se_necessario,
    calcular_ciclo_anterior,
    obter_semana_id,
    is_modo_teste,
    is_licenca_bloqueada
)

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

    # Pré-calcular o subtotal exato para cada fatura
    for fatura in faturas_carregadas:
        if current_user.modelo_negocio == 'compra':
            subtotal = sum(dia.liquido for dia in fatura.dias if dia.status == 'relatorio_enviado')
        else:
            subtotal = sum(dia.repasse for dia in fatura.dias if dia.status == 'relatorio_enviado')
        fatura.subtotal_exibicao = subtotal

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
    if not autorizado: return jsonify({"assinado": False}), 403
    return jsonify({"assinado": assinado})

# ==================== ROTAS DO ROBÔ E LICENÇAS (UNIFICADAS) ====================

@client_bp.route('/robo')
@login_required
def robo_download():
    versao = versao_atual()
    if not versao:
        flash("Nenhuma versão do robô disponível no momento.", "warning")
        return render_template('client/robo_download.html', versao=None, botao_liberado=False, historico=[])
    
    liberado, msg = liberado_para_download(current_user, versao)
    historico = historico_downloads_cliente(current_user)
    
    return render_template(
        'client/robo_download.html',
        versao=versao,
        botao_liberado=liberado,
        msg_bloqueio=msg if not liberado else None,
        historico=historico
    )

@client_bp.route('/robo/download', methods=['POST'])
@login_required
def baixar_robo():
    versao = versao_atual()
    if not versao:
        return jsonify({"error": "Nenhuma versão disponível"}), 404
    
    liberado, msg = liberado_para_download(current_user, versao)
    if not liberado:
        return jsonify({"error": msg}), 403
    
    registrar_download(current_user, versao.id)
    
    try:
        response = requests.get(versao.arquivo_url, stream=True, timeout=30)
        response.raise_for_status()
    except Exception as e:
        logger.error(f"Erro ao baixar arquivo do Cloudinary: {e}")
        return jsonify({"error": "Falha ao obter o arquivo do robô"}), 500
    
    extensao = versao.extensao if versao.extensao else '.exe'
    nome_arquivo = f"dwcapital_robo_v{versao.versao}{extensao}"
    
    return send_file(
        io.BytesIO(response.content),
        as_attachment=True,
        download_name=nome_arquivo,
        mimetype='application/octet-stream'
    )

@client_bp.route('/licenca/status', methods=['GET'])
@login_required
def licenca_status():
    licenca = obter_licenca_ativa(current_user)
    if licenca:
        return jsonify({
            "success": True,
            "tem_licenca": True,
            "tipo": licenca.tipo,
            "chave": licenca.chave_licenca,
            "validade": licenca.data_expiracao.strftime('%d/%m/%Y %H:%M') if licenca.data_expiracao else "Vitalícia",
            "status": licenca.status
        })
    else:
        return jsonify({
            "success": True,
            "tem_licenca": False
        })

@client_bp.route('/licenca/gerar', methods=['POST'])
@login_required
def licenca_gerar():
    if is_licenca_bloqueada(current_user):
        return jsonify({
            "success": False,
            "error": "BLOQUEADO",
            "message": "A geração de licenças está bloqueada para este cliente. Entre em contato com o suporte."
        }), 403
    
    hoje = datetime.now(tz_br).date()
    if not is_modo_teste():
        if hoje.weekday() >= 5:
            return jsonify({
                "success": False,
                "error": "DIA_INVALIDO",
                "message": "A geração de licenças semanais só é permitida em dias úteis (segunda a sexta)."
            }), 400
    
    if not current_user.conta_mt5:
        return jsonify({
            "success": False,
            "error": "PRECISA_CONTA",
            "message": "Você precisa cadastrar sua conta MT5 antes de gerar a licença."
        }), 200
    
    chave, msg, licenca_obj, ja_existente = gerar_licenca_comissao(current_user, current_user.conta_mt5)
    if not chave:
        return jsonify({
            "success": False,
            "error": "CONDICOES_NAO_ATENDIDAS",
            "message": msg
        }), 400
    
    return jsonify({
        "success": True,
        "chave": chave,
        "message": msg,
        "validade": licenca_obj.data_expiracao.strftime('%d/%m/%Y %H:%M') if licenca_obj.data_expiracao else None,
        "ja_existente": ja_existente
    })

@client_bp.route('/licenca/visualizar', methods=['POST'])
@login_required
def licenca_visualizar():
    return licenca_gerar()

@client_bp.route('/api/salvar_conta_mt5', methods=['POST'])
@login_required
def api_salvar_conta_mt5():
    data = request.get_json()
    nova_conta = data.get('conta_mt5', '').strip()
    if not nova_conta:
        return jsonify({"success": False, "message": "Número da conta MT5 é obrigatório."}), 400
    
    if not nova_conta.isdigit():
        return jsonify({"success": False, "message": "A conta MT5 deve conter apenas números."}), 400
    
    gerou, chave, msg = salvar_conta_mt5_e_gerar_vitalicia_se_necessario(current_user, nova_conta)
    
    return jsonify({
        "success": True,
        "conta_salva": nova_conta,
        "licenca_gerada": gerou,
        "chave_licenca": chave,
        "message": msg
    })

@client_bp.route('/faturas/gerar_licenca', methods=['POST'])
@login_required
def gerar_licenca_antiga():
    return licenca_gerar()

@client_bp.route('/ajuda')
@login_required
def ajuda():
    msg_suporte = f"Olá, me chamo {current_user.nome}. Preciso de ajuda, segue minhas informações:\nID: {current_user.id}\nCPF: {current_user.cpf}"
    msg_suporte_encoded = urllib.parse.quote(msg_suporte)
    
    return render_template('client/ajuda.html', 
                           link_suporte=f"https://wa.me/5511991167709?text={msg_suporte_encoded}",
                           link_comercial=f"https://wa.me/5511920504850?text={msg_suporte_encoded}")
