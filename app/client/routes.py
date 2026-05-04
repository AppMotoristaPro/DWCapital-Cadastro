import os
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, jsonify
from flask_login import login_required, current_user
from app import db
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
        
    # ENVIO AUTOMÁTICO: O servidor envia o e-mail logo ao carregar a página
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
    """
    Rota invisível que o JavaScript da tela fica consultando de 5 em 5 segundos.
    """
    doc_id = current_user.docusign_envelope_id
    
    if not doc_id:
        return jsonify({"assinado": False})
        
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

@client_bp.route('/faturas')
@login_required
def faturas():
    if not current_user.termo_assinado:
        return redirect(url_for('client.assinar_termo'))
    
    faturas = current_user.faturas
    return render_template('client/faturas.html', user=current_user, faturas=faturas)

