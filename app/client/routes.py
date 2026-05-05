import os
import urllib.parse
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, jsonify
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app import db
from app.models import FaturaDiaria
from app.utils.autentique import criar_documento_autentique, verificar_status_autentique

client_bp = Blueprint('client', __name__, url_prefix='/portal')

@client_bp.route('/dashboard')
@login_required
def dashboard():
    if not current_user.termo_assinado:
        return redirect(url_for('client.assinar_termo'))
        
    return render_template('client/index.html', user=current_user)

@client_bp.route('/assinar')
@login_required
def assinar_termo():
    if current_user.termo_assinado:
        return redirect(url_for('client.dashboard'))
        
    documento_enviado = bool(current_user.docusign_envelope_id)
        
    if not documento_enviado:
        caminho_pdf = os.path.join(current_app.root_path, 'static', 'documentos', 'termo_adesao.pdf')
        
        if not os.path.exists(caminho_pdf):
            flash("Erro interno: O modelo do contrato não foi encontrado no servidor.", "danger")
            return render_template('client/assinar_termo.html', documento_enviado=False, email=current_user.email)

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
            flash(f"Não foi possível enviar o documento automaticamente: {str(e)}", "danger")
            
    return render_template('client/assinar_termo.html', documento_enviado=documento_enviado, email=current_user.email)

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
    except Exception:
        pass
    return jsonify({"assinado": False})

@client_bp.route('/dados_pessoais')
@login_required
def dados_pessoais():
    if not current_user.termo_assinado:
        return redirect(url_for('client.assinar_termo'))
    return render_template('client/dados_pessoais.html', user=current_user)

@client_bp.route('/faturas', methods=['GET', 'POST'])
@login_required
def faturas():
    if not current_user.termo_assinado:
        return redirect(url_for('client.assinar_termo'))
    
    if request.method == 'POST':
        dia_id = request.form.get('dia_id')
        arquivo = request.files.get('relatorio_pdf')
        
        if arquivo and arquivo.filename:
            if arquivo.filename.lower().endswith('.pdf'):
                filename = secure_filename(arquivo.filename)
                filename = f"dia_{dia_id}_{filename}"
                
                upload_folder = os.path.join(current_app.root_path, 'static', 'uploads')
                os.makedirs(upload_folder, exist_ok=True) 
                
                file_path = os.path.join(upload_folder, filename)
                arquivo.save(file_path)
                
                dia = FaturaDiaria.query.get(dia_id)
                if dia:
                    if dia.fatura_semanal.user_id == current_user.id:
                        dia.arquivo_pdf = filename
                        dia.status = 'relatorio_enviado'
                        db.session.commit()
                        flash('Relatório anexado com sucesso! Nossos robôs irão processá-lo em breve.', 'success')
                    else:
                        flash('Erro de segurança: Você não tem permissão para alterar esta fatura.', 'danger')
                else:
                    flash('O dia de operação não foi encontrado no sistema.', 'danger')
            else:
                flash('Formato inválido. Por favor, envie apenas arquivos em .PDF', 'danger')
        else:
            flash('Nenhum arquivo foi selecionado para envio.', 'warning')
            
        return redirect(url_for('client.faturas'))

    faturas = current_user.faturas
    return render_template('client/faturas.html', user=current_user, faturas=faturas)

@client_bp.route('/ajuda')
@login_required
def ajuda():
    if not current_user.termo_assinado:
        return redirect(url_for('client.assinar_termo'))
        
    mensagem = f"Olá, sou {current_user.nome}, ID {current_user.matricula or 'Pendente'}. Preciso de um suporte."
    msg_encoded = urllib.parse.quote(mensagem)
    
    link_comercial = f"https://wa.me/5511920504850?text={msg_encoded}"
    link_suporte = f"https://wa.me/5511991167709?text={msg_encoded}"
    
    return render_template('client/ajuda.html', user=current_user, link_comercial=link_comercial, link_suporte=link_suporte)

