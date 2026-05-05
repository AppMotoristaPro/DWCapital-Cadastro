import os
import urllib.parse
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, jsonify
from flask_login import login_required, current_user
import cloudinary.uploader
from app import db
from app.models import FaturaDiaria, Fatura
from app.utils.autentique import criar_documento_autentique, verificar_status_autentique
from app.utils.pdf_parser import extrair_dados_nota_corretagem

client_bp = Blueprint('client', __name__, url_prefix='/portal')

def atualizar_totais_semana(fatura):
    """Calcula os totais financeiros e define o status da semana (Pendente, Parcial ou Completo)"""
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
    elif dias_enviados == 5:
        fatura.status = 'completo'
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
    if request.method == 'POST':
        dia_id = request.form.get('dia_id')
        arquivo = request.files.get('relatorio_pdf')
        if arquivo and arquivo.filename:
            upload_folder = os.path.join(current_app.root_path, 'static', 'uploads')
            os.makedirs(upload_folder, exist_ok=True)
            file_path = os.path.join(upload_folder, arquivo.filename)
            arquivo.save(file_path)
            
            dia = FaturaDiaria.query.get(dia_id)
            dados = extrair_dados_nota_corretagem(file_path)
            
            print(f"[ROUTE LOG] Processando PDF para ID {dia_id}...")
            
            if not dados or dados.get('data_pregao') != dia.data_pregao.strftime('%d/%m/%Y'):
                print(f"[ROUTE ERROR] Divergência de data: PDF={dados.get('data_pregao') if dados else 'ERRO'} vs Banco={dia.data_pregao.strftime('%d/%m/%Y')}")
                if os.path.exists(file_path): os.remove(file_path)
                flash('PDF Inválido ou data incorreta.', 'danger')
                return redirect(url_for('client.faturas'))
            
            try:
                # Upload seguro para o Cloudinary renderizado como imagem para burlar erros de visualização direta de PDF
                upload_res = cloudinary.uploader.upload(file_path, folder="dwcapital/relatorios", resource_type="image")
                dia.arquivo_pdf = upload_res.get('secure_url')
                
                # Persistência dos valores financeiros extraídos pelo robô
                dia.bruto = dados.get('bruto')
                dia.taxas_b3 = dados.get('taxas_b3')
                dia.irrf_1 = dados.get('irrf_1')
                dia.liquido_pregao = dados.get('liquido_pregao')
                dia.irrf_19 = dados.get('irrf_19')
                dia.liquido = dados.get('liquido_dia')
                dia.repasse = dados.get('repasse_dw')
                dia.status = 'relatorio_enviado'
                
                print(f"[ROUTE LOG] Sucesso! Salvando Bruto: R$ {dia.bruto} | Repasse: R$ {dia.repasse}")
                db.session.commit()
                
                if os.path.exists(file_path): os.remove(file_path)
                atualizar_totais_semana(dia.fatura_semanal)
                flash('Relatório processado e salvo com sucesso!', 'success')
            except Exception as e:
                print(f"[ROUTE ERROR] Falha no upload/salvamento: {str(e)}")
                if os.path.exists(file_path): os.remove(file_path)
                flash(f'Erro técnico no processamento: {str(e)}', 'danger')
                
    return render_template('client/faturas.html', faturas=current_user.faturas)

@client_bp.route('/faturas/comprovante/<int:fatura_id>', methods=['POST'])
@login_required
def enviar_comprovante(fatura_id):
    fatura = Fatura.query.get_or_404(fatura_id)
    arquivo = request.files.get('comprovante')
    if arquivo:
        try:
            # Comprovantes também são enviados como image para garantir visualização no navegador
            res = cloudinary.uploader.upload(arquivo, folder="dwcapital/comprovantes", resource_type="image")
            fatura.comprovante_pix = res.get('secure_url')
            db.session.commit()
            flash('Comprovante enviado com sucesso!', 'success')
        except Exception as e:
            flash(f'Erro ao enviar para nuvem: {str(e)}', 'danger')
    return redirect(url_for('client.faturas'))

@client_bp.route('/faturas/remover/<int:dia_id>', methods=['POST'])
@login_required
def remover_fatura(dia_id):
    dia = FaturaDiaria.query.get_or_404(dia_id)
    dia.arquivo_pdf, dia.status = None, 'pendente'
    db.session.commit()
    atualizar_totais_semana(dia.fatura_semanal)
    return redirect(url_for('client.faturas'))

@client_bp.route('/ajuda')
@login_required
def ajuda():
    mensagem = f"Olá, sou {current_user.nome}. Preciso de suporte referente ao portal DW Capital."
    msg_encoded = urllib.parse.quote(mensagem)
    return render_template('client/ajuda.html', link_suporte=f"https://wa.me/5511991167709?text={msg_encoded}")

