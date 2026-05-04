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
        flash("Por favor, assine o termo de adesão para aceder ao portal.", "warning")
        return redirect(url_for('client.assinar_termo'))
        
    return render_template('client/dashboard.html', user=current_user)

@client_bp.route('/assinar', methods=['GET', 'POST'])
@login_required
def assinar_termo():
    if current_user.termo_assinado:
        return redirect(url_for('client.dashboard'))
        
    url_assinatura = None
        
    if request.method == 'POST':
        caminho_pdf = os.path.join(current_app.root_path, 'static', 'documentos', 'termo_adesao.pdf')
        
        if not os.path.exists(caminho_pdf):
            flash("Erro interno: O modelo do contrato não foi encontrado no servidor.", "danger")
            return render_template('client/assinar_termo.html', url_assinatura=url_assinatura)

        try:
            doc_id, url_assinatura = criar_documento_autentique(
                nome_signer=current_user.nome,
                email_signer=current_user.email,
                caminho_pdf=caminho_pdf
            )
            
            # Mantemos a coluna docusign_envelope_id para evitar migração no DB agora
            current_user.docusign_envelope_id = doc_id 
            db.session.commit()
            flash("Contrato gerado com sucesso! Siga as instruções abaixo.", "success")
            
        except Exception as e:
            flash(f"Falha ao conectar com o serviço de contratos: {str(e)}", "danger")
            
    return render_template('client/assinar_termo.html', url_assinatura=url_assinatura)

@client_bp.route('/retorno_assinatura')
@login_required
def retorno_assinatura():
    doc_id = current_user.docusign_envelope_id
    
    if not doc_id:
        flash("Nenhum contrato pendente foi encontrado no sistema.", "warning")
        return redirect(url_for('client.assinar_termo'))
        
    try:
        # Chama a API da Autentique para confirmar se o cliente de fato assinou
        if verificar_status_autentique(doc_id):
            current_user.termo_assinado = True
            db.session.commit()
            flash("Assinatura confirmada com sucesso! Bem-vindo ao portal DW Capital.", "success")
            return redirect(url_for('client.dashboard'))
        else:
            flash("Ainda não identificamos a sua assinatura. Por favor, conclua na nova aba e clique novamente.", "warning")
            return redirect(url_for('client.assinar_termo'))
            
    except Exception as e:
        flash("Erro interno ao atualizar o status da sua assinatura.", "danger")
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

