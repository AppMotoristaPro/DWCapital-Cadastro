import os
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from app import db
from app.utils.autentique import criar_documento_autentique, verificar_status_autentique

client_bp = Blueprint('client', __name__, url_prefix='/portal')

@client_bp.route('/dashboard')
@login_required
def dashboard():
    # Pedágio: se não assinou, vai para a tela de assinatura
    if not current_user.termo_assinado:
        return redirect(url_for('client.assinar_termo'))
        
    # CORREÇÃO: Redireciona para a sua tela inicial verdadeira (index.html)
    return render_template('client/index.html', user=current_user)

@client_bp.route('/assinar', methods=['GET', 'POST'])
@login_required
def assinar_termo():
    if current_user.termo_assinado:
        return redirect(url_for('client.dashboard'))
        
    documento_enviado = bool(current_user.docusign_envelope_id)
        
    if request.method == 'POST':
        if not documento_enviado:
            caminho_pdf = os.path.join(current_app.root_path, 'static', 'documentos', 'termo_adesao.pdf')
            
            if not os.path.exists(caminho_pdf):
                flash("Erro interno: O modelo do contrato não foi encontrado no servidor.", "danger")
                return render_template('client/assinar_termo.html', documento_enviado=documento_enviado)

            try:
                doc_id = criar_documento_autentique(
                    nome_signer=current_user.nome,
                    email_signer=current_user.email,
                    caminho_pdf=caminho_pdf
                )
                
                current_user.docusign_envelope_id = doc_id 
                db.session.commit()
                flash("Termo de adesão enviado para o seu e-mail com sucesso!", "success")
                
                documento_enviado = True
                
            except Exception as e:
                flash(f"Não foi possível enviar o documento: {str(e)}", "danger")
            
    return render_template('client/assinar_termo.html', documento_enviado=documento_enviado, email=current_user.email)

@client_bp.route('/retorno_assinatura')
@login_required
def retorno_assinatura():
    doc_id = current_user.docusign_envelope_id
    
    if not doc_id:
        flash("Nenhum contrato pendente foi encontrado.", "warning")
        return redirect(url_for('client.assinar_termo'))
        
    try:
        if verificar_status_autentique(doc_id):
            current_user.termo_assinado = True
            db.session.commit()
            flash("Identificamos a sua assinatura! Bem-vindo ao portal DW Capital.", "success")
            return redirect(url_for('client.dashboard'))
        else:
            flash("Ainda não identificamos a assinatura. Verifique o seu e-mail, assine o documento e tente novamente.", "warning")
            return redirect(url_for('client.assinar_termo'))
            
    except Exception as e:
        flash("Erro ao validar o seu status de assinatura.", "danger")
        return redirect(url_for('client.assinar_termo'))

# CORREÇÃO: Função ajustada para abrir "dados_pessoais.html"
@client_bp.route('/dados_pessoais')
@login_required
def dados_pessoais():
    if not current_user.termo_assinado:
        return redirect(url_for('client.assinar_termo'))
    return render_template('client/dados_pessoais.html', user=current_user)

# CORREÇÃO: Função ajustada para abrir "faturas.html" e passar os dados corretos
@client_bp.route('/faturas')
@login_required
def faturas():
    if not current_user.termo_assinado:
        return redirect(url_for('client.assinar_termo'))
    
    # Busca as faturas do cliente para exibir na tela
    faturas = current_user.faturas
    return render_template('client/faturas.html', user=current_user, faturas=faturas)

