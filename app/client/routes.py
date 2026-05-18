import os
import urllib.parse
from datetime import datetime, timedelta
import pytz
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, jsonify
from flask_login import login_required, current_user
import cloudinary.uploader
from werkzeug.utils import secure_filename
from app import db
from app.models import FaturaDiaria, Fatura, DocumentoCliente, ParcelaCompra
from app.utils.parsers.gerenciador_pdf import processar_pdf
from sqlalchemy.exc import IntegrityError
from app.services.fatura_service import atualizar_totais_semana, auto_gerar_ciclo
from app.services.documento_service import gerar_termo_adesao, verificar_status_termo, verificar_status_documento_cliente
from app.services.dashboard_service import obter_dados_dashboard_cliente
from app.services.pix_service import PixService

tz_br = pytz.timezone('America/Sao_Paulo')
client_bp = Blueprint('client', __name__, url_prefix='/portal')

@client_bp.before_request
def check_paywall():
    if not current_user.is_authenticated:
        return
    if getattr(current_user, 'precisa_trocar_senha', False):
        return
    if not current_user.termo_assinado:
        if request.endpoint in ['client.assinar_termo', 'client.api_status_assinatura']:
            return
            
    # CORREÇÃO CIRÚRGICA: Permite que a tela de bloqueio e seus endpoints assíncronos funcionem sem sofrer interceptação
    if request.endpoint in ['client.bloqueio_pagamento', 'client.gerar_pix_licenca', 'client.status_licenca_api']:
        return
        
    if getattr(current_user, 'modelo_negocio', 'comissao') == 'compra':
        hoje = datetime.now(tz_br).date()
        parcela_pendente = ParcelaCompra.query.filter(
            ParcelaCompra.user_id == current_user.id,
            ParcelaCompra.status == 'pendente',
            ParcelaCompra.data_vencimento <= hoje
        ).order_by(ParcelaCompra.ordem.asc()).first()
        
        if parcela_pendente:
            return redirect(url_for('client.bloqueio_pagamento'))

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
        
    return render_template('client/bloqueio_pix.html', parcela=parcela_pendente)


# ===================================================
# ENDPOINTS ASSÍNCRONOS DO MOTOR PIX INTER
# ===================================================
@client_bp.route('/faturas/gerar_pix/<int:fatura_id>', methods=['POST'])
@login_required
def gerar_pix_fatura(fatura_id):
    fatura = Fatura.query.get_or_404(fatura_id)
    if fatura.user_id != current_user.id:
        return jsonify({"success": False, "message": "Acesso negado."}), 403

    # TRAVA DE SEGURANÇA: Verifica se existem notas pendentes no ciclo
    tem_notas_pendentes = any(d.status == 'pendente' for d in fatura.dias)
    if tem_notas_pendentes:
        return jsonify({
            "success": False, 
            "error": "NOTAS_PENDENTES", 
            "message": "Você possui faturas de corretagem pendentes neste ciclo. Anexe todas para liberar o PIX."
        }), 200

    # Se já foi gerado anteriormente, reaproveita o mesmo payload economizando requisição
    if fatura.txid_pix and fatura.payload_pix:
        return jsonify({"success": True, "txid": fatura.txid_pix, "pix_copia_e_cola": fatura.payload_pix})

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

    if parcela.txid_pix and parcela.payload_pix:
        return jsonify({"success": True, "txid": parcela.txid_pix, "pix_copia_e_cola": parcela.payload_pix})

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
# ===================================================


@client_bp.route('/dashboard')
@login_required
def dashboard():
    if getattr(current_user, 'precisa_trocar_senha', False):
        return redirect(url_for('auth.forcar_troca_senha'))
    if not current_user.termo_assinado:
        return redirect(url_for('client.assinar_termo'))
        
    auto_gerar_ciclo(current_user)
    
    filtro_dia = request.args.get('dia')
    filtro_semana_dia = request.args.get('semana_dia') 
    filtro_ano = request.args.get('ano') 
    
    dados = obter_dados_dashboard_cliente(current_user.id, filtro_dia, filtro_semana_dia, filtro_ano)
    return render_template('client/index.html', user=current_user, **dados)

@client_bp.route('/assinar')
@login_required
def assinar_termo():
    if current_user.termo_assinado: 
        return redirect(url_for('client.dashboard'))
    
    documento_enviado = bool(current_user.docusign_envelope_id)
    if not documento_enviado:
        try:
            get_doc = gerar_termo_adesao(current_user)
            documento_enviado = True
        except Exception as e:
            flash(f"Erro ao gerar contrato: {str(e)}", "danger")
            
    return render_template('client/assinar_termo.html', documento_enviado=documento_enviado)

@client_bp.route('/api/status_assinatura')
@login_required
def api_status_assinatura():
    if verificar_status_termo(current_user):
        return jsonify({"assinado": True})
    return jsonify({"assinado": False})

@client_bp.route('/dados_pessoais')
@login_required
def dados_pessoais():
    return render_template('client/dados_pessoais.html', user=current_user)

@client_bp.route('/faturas', methods=['GET', 'POST'])
@login_required
def faturas():
    auto_gerar_ciclo(current_user)

    if request.method == 'GET':
        for fatura in current_user.faturas:
            for dia in list(fatura.dias):
                if dia.data_pregao.weekday() >= 5:
                    db.session.delete(dia)
            db.session.commit()

            datas_da_semana = []
            data_atual = fatura.data_inicio
            while len(datas_da_semana) < 5:
                if data_atual.weekday() < 5:
                    datas_da_semana.append(data_atual)
                data_atual += timedelta(days=1)
                
            for data in datas_da_semana:
                for alocacao in current_user.alocacoes:
                    dia_existente = FaturaDiaria.query.filter_by(
                        fatura_id=fatura.id, 
                        data_pregao=data, 
                        nome_corretora=alocacao.nome_corretora
                    ).first()
                    if not dia_existente:
                        novo_dia = FaturaDiaria(
                            fatura_id=fatura.id, 
                            data_pregao=data, 
                            nome_corretora=alocacao.nome_corretora, 
                            status='pendente'
                        )
                        db.session.add(novo_dia)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()

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
                bloq_data_env = os.environ.get('BLOQ_DATA', 'False').lower()
                bloquear_data = bloq_data_env in ('true', '1', 't')
          
                if not dados:
                    if os.path.exists(file_path): os.remove(file_path)
                    return jsonify({'success': False, 'error': 'RELATORIO_INVALIDO', 'message': 'Não foi possível ler os dados do PDF.'})

                data_pdf = dados.get('data_pregao')
                data_esperada = dia.data_pregao.strftime('%d/%m/%Y')
                
                if bloquear_data and data_pdf != data_esperada:
                    if os.path.exists(file_path): os.remove(file_path)
                    return jsonify({'success': False, 'error': 'RELATORIO_INVALIDO', 'message': f'Data incorreta. Esperado: {data_esperada}.'})

                upload_res = cloudinary.uploader.upload(file_path, folder="dwcapital/relatorios")
                
                dia.arquivo_pdf = upload_res.get('secure_url')
                dia.bruto = dados.get('bruto')
                dia.taxas_b3 = dados.get('taxas_b3')
                dia.irrf_1 = dados.get('irrf_1')
                dia.liquido_pregao = dados.get('liquido_pregao')
                dia.irrf_19 = dados.get('irrf_19')
                dia.liquido = dados.get('liquido_dia')
                
                if getattr(current_user, 'is_isento', False):
                    dia.repasse = 0.0
                else:
                    dia.repasse = dados.get('repasse_dw')
                    
                dia.status = 'relatorio_enviado'
                
                db.session.commit()
                atualizar_totais_semana(dia.fatura_semanal)
                
                if os.path.exists(file_path): os.remove(file_path)
                return jsonify({'success': True})

            except Exception as e:
                if os.path.exists(file_path): os.remove(file_path)
                if "SENHA_INCORRETA" in str(e):
                    return jsonify({'success': False, 'error': 'REQUER_SENHA'})
                if "PDF_INCOMPATIVEL" in str(e):
                    msg_erro = str(e).split("PDF_INCOMPATIVEL: ")[-1]
                    return jsonify({'success': False, 'error': 'RELATORIO_INVALIDO', 'message': msg_erro})
                
                return jsonify({'success': False, 'error': 'ERRO_TECNICO', 'message': str(e)})

    return render_template('client/faturas.html', faturas=current_user.faturas)

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
    meus_docs = DocumentoCliente.query.filter_by(user_id=current_user.id).order_by(DocumentoCliente.data_envio.desc()).all()
    return render_template('client/documentos.html', documentos=meus_docs)

@client_bp.route('/api/status_documento/<int:doc_id>')
@login_required
def api_status_documento(doc_id):
    autorizado, assinado = verificar_status_documento_cliente(doc_id, current_user.id)
    if not autorizado:
        return jsonify({"assinado": False}), 403
    return jsonify({"assinado": assinado})

@client_bp.route('/ajuda')
@login_required
def ajuda():
    msg_suporte = f"Olá, sou {current_user.nome}. Preciso de suporte técnico no portal DW Capital."
    msg_suporte_encoded = urllib.parse.quote(msg_suporte)
    msg_comercial = f"Olá, sou {current_user.nome}. Preciso de atendimento comercial/financeiro."
    msg_comercial_encoded = urllib.parse.quote(msg_comercial)
    
    return render_template('client/ajuda.html', 
                           link_suporte=f"https://wa.me/5511991167709?text={msg_suporte_encoded}",
                           link_comercial=f"https://wa.me/5511920504850?text={msg_comercial_encoded}")