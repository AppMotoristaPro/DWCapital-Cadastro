import os
import urllib.parse
from datetime import timedelta
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, jsonify
from flask_login import login_required, current_user
import cloudinary.uploader
from app import db
from app.models import FaturaDiaria, Fatura
from app.utils.autentique import criar_documento_autentique, verificar_status_autentique
from app.utils.parsers.gerenciador_pdf import processar_pdf

client_bp = Blueprint('client', __name__, url_prefix='/portal')

def atualizar_totais_semana(fatura):
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
    else:
        fatura.status = 'parcial'
        
    db.session.commit()

@client_bp.route('/dashboard')
@login_required
def dashboard():
    if getattr(current_user, 'precisa_trocar_senha', False):
        return redirect(url_for('auth.forcar_troca_senha'))
    if not current_user.termo_assinado:
        return redirect(url_for('client.assinar_termo'))
    return render_template('client/index.html', user=current_user)

@client_bp.route('/assinar')
@login_required
def assinar_termo():
    if current_user.termo_assinado: return redirect(url_for('client.dashboard'))
    documento_enviado = bool(current_user.docusign_envelope_id)
    if not documento_enviado:
        caminho_pdf = os.path.join(current_app.root_path, 'static', 'documentos', 'termo_adesao.pdf')
        try:
            doc_id = criar_documento_autentique(
                nome_signer=current_user.nome,
                email_signer=current_user.email,
                caminho_pdf=caminho_pdf
            )
            current_user.docusign_envelope_id = doc_id 
            db.session.commit()
            documento_enviado = True
        except Exception as e:
            flash(f"Erro ao gerar contrato: {str(e)}", "danger")
    return render_template('client/assinar_termo.html', documento_enviado=documento_enviado)

@client_bp.route('/api/status_assinatura')
@login_required
def api_status_assinatura():
    doc_id = current_user.docusign_envelope_id
    if not doc_id: return jsonify({"assinado": False})
    try:
        if verificar_status_autentique(doc_id):
            current_user.termo_assinado = True
            db.session.commit()
            return jsonify({"assinado": True})
    except: pass
    return jsonify({"assinado": False})

@client_bp.route('/dados_pessoais')
@login_required
def dados_pessoais():
    return render_template('client/dados_pessoais.html', user=current_user)

@client_bp.route('/faturas', methods=['GET', 'POST'])
@login_required
def faturas():
    if request.method == 'GET':
        for fatura in current_user.faturas:
            datas_da_semana = [fatura.data_inicio + timedelta(days=i) for i in range(5)]
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
        db.session.commit()

    if request.method == 'POST':
        dia_id = request.form.get('dia_id')
        senha_manual = request.form.get('senha_manual')
        arquivo = request.files.get('relatorio_pdf')
        
        print(f"\n[ROUTES] --- INÍCIO DE UPLOAD ---")
        print(f"[ROUTES] FaturaDiaria ID: {dia_id} | Senha Manual: {'Sim' if senha_manual else 'Não'}")
        
        if arquivo and arquivo.filename:
            print(f"[ROUTES] Arquivo recebido: {arquivo.filename}")
            upload_folder = os.path.join(current_app.root_path, 'static', 'uploads')
            os.makedirs(upload_folder, exist_ok=True)
            file_path = os.path.join(upload_folder, arquivo.filename)
            arquivo.save(file_path)
            
            dia = FaturaDiaria.query.get(dia_id)
            
            try:
                print(f"[ROUTES] Chamando processar_pdf para {dia.nome_corretora}...")
                dados = processar_pdf(file_path, dia.nome_corretora, current_user.cpf, senha_manual)
                
                # === TRAVA DE DATA DESATIVADA TEMPORARIAMENTE PARA TESTES ===
                if not dados:
                    print("[ROUTES] ERRO: Retorno do processar_pdf foi None.")
                    if os.path.exists(file_path): os.remove(file_path)
                    return jsonify({'success': False, 'error': 'RELATORIO_INVALIDO', 'message': 'Não foi possível ler os dados do PDF.'})

                print("[ROUTES] Sucesso na leitura! Iniciando envio Cloudinary...")
                upload_res = cloudinary.uploader.upload(file_path, folder="dwcapital/relatorios")
                print("[ROUTES] Envio Cloudinary finalizado.")
                
                dia.arquivo_pdf = upload_res.get('secure_url')
                dia.bruto = dados.get('bruto')
                dia.taxas_b3 = dados.get('taxas_b3')
                dia.irrf_1 = dados.get('irrf_1')
                dia.liquido_pregao = dados.get('liquido_pregao')
                dia.irrf_19 = dados.get('irrf_19')
                dia.liquido = dados.get('liquido_dia')
                dia.repasse = dados.get('repasse_dw')
                dia.status = 'relatorio_enviado'
                
                db.session.commit()
                atualizar_totais_semana(dia.fatura_semanal)
                print("[ROUTES] Dados gravados no banco. Processo concluído.")
                
                if os.path.exists(file_path): os.remove(file_path)
                return jsonify({'success': True})

            except Exception as e:
                print(f"[ROUTES] EXCEÇÃO NO FLUXO: {str(e)}")
                if os.path.exists(file_path): os.remove(file_path)
                
                if "SENHA_INCORRETA" in str(e):
                    print("[ROUTES] Disparando alerta de REQUER_SENHA para o Frontend.")
                    return jsonify({'success': False, 'error': 'REQUER_SENHA'})
                
                return jsonify({'success': False, 'error': 'ERRO_TECNICO', 'message': str(e)})

    return render_template('client/faturas.html', faturas=current_user.faturas)

@client_bp.route('/faturas/comprovante/<int:fatura_id>', methods=['POST'])
@login_required
def enviar_comprovante(fatura_id):
    fatura = Fatura.query.get_or_404(fatura_id)
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
    dia.arquivo_pdf = None
    dia.status = 'pendente'
    db.session.commit()
    atualizar_totais_semana(dia.fatura_semanal)
    return redirect(url_for('client.faturas'))

@client_bp.route('/ajuda')
@login_required
def ajuda():
    mensagem = f"Olá, sou {current_user.nome}. Preciso de suporte referente ao portal DW Capital."
    msg_encoded = urllib.parse.quote(mensagem)
    return render_template('client/ajuda.html', link_suporte=f"https://wa.me/5511991167709?text={msg_encoded}")

