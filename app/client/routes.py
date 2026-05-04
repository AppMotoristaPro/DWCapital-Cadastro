import os
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from app import db
from app.utils.autentique import criar_documento_autentique, verificar_status_autentique

client_bp = Blueprint('client', __name__, url_prefix='/portal')

@client_bp.route('/dashboard')
@login_required
def dashboard():
    if not current_user.termo_assinado:
        return redirect(url_for('client.assinar_termo'))
        
    return render_template('client/dashboard.html', user=current_user)

@client_bp.route('/assinar', methods=['GET', 'POST'])
@login_required
def assinar_termo():
    if current_user.termo_assinado:
        return redirect(url_for('client.dashboard'))
        
    # Verifica se o cliente já tem um contrato pendente gerado
    documento_enviado = bool(current_user.docusign_envelope_id)
        
    if request.method == 'POST':
        # Se ele ainda não tem contrato pendente, gera um novo
        if not documento_enviado:
            caminho_pdf = os.path.join(current_app.root_path, 'static', 'documentos', 'termo_adesao.pdf')
            
            if not os.path.exists(caminho_pdf):
                flash("Erro interno: O modelo do contrato não foi encontrado no servidor.", "danger")
                return render_template('client/assinar_termo.html', documento_enviado=documento_enviado)

            try:
                # Agora a função só retorna o ID, e o e-mail é disparado silenciosamente
                doc_id = criar_documento_autentique(
                    nome_signer=current_user.nome,
                    email_signer=current_user.email,
                    caminho_pdf=caminho_pdf
                )
                
                current_user.docusign_envelope_id = doc_id 
                db.session.commit()
                flash("Termo de adesão enviado para o seu e-mail com sucesso!", "success")
                
                # Atualiza a variável para a tela mudar de estado imediatamente
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
        # Consulta se ele realmente assinou lá no e-mail
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

@client_bp.route('/perfil')
@login_required
def perfil():
    if not current_user.termo_assinado:
        return redirect(url_for('client.assinar_termo'))
    return render_template('client/perfil.html', user=current_user)

@client_bp.route('/investimentos')
@login_required
def historico_investimentos():
    if not current_user.termo_assinado:
        return redirect(url_for('client.assinar_termo'))
    return render_template('client/investimentos.html', user=current_user)

