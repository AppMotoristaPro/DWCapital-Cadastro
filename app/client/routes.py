import os
from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app import db
from app.models import Fatura
from app.utils.pdf_parser import extrair_dados_nota_corretagem

client_bp = Blueprint('client', __name__)

@client_bp.route('/')
def index():
    return redirect(url_for('auth.login'))

@client_bp.route('/faturas', methods=['GET', 'POST'])
@login_required
def faturas():
    if request.method == 'POST':
        f_id = request.form.get('fatura_id')
        pdf = request.files.get('relatorio_pdf')
        
        if pdf and pdf.filename.lower().endswith('.pdf'):
            path = os.path.join('/tmp', secure_filename(pdf.filename))
            pdf.save(path)
            print(f"DEBUG: PDF salvo em {path}. Iniciando parser...")
            
            dados = extrair_dados_nota_corretagem(path)
            if os.path.exists(path): os.remove(path)
            
            if dados:
                fatura = Fatura.query.get(f_id)
                if fatura and fatura.user_id == current_user.id:
                    fatura.bruto = dados['bruto']
                    fatura.liquido = dados['liquido']
                    
                    # Regra DW: Descontar 19% do IRRF restante e aplicar 30% de repasse
                    # Fórmula: $$ (Liquido \times 0.81) \times 0.30 $$
                    if dados['liquido'] > 0:
                        fatura.repasse = (dados['liquido'] * 0.81) * 0.30
                    else:
                        fatura.repasse = 0.0
                        
                    fatura.status = 'aguardando_pagamento'
                    db.session.commit()
                    print(f"DEBUG: Fatura {f_id} atualizada com repasse de R$ {fatura.repasse}")
                    flash('Nota de Corretagem processada!', 'success')
            else:
                flash('Erro na leitura do PDF. Verifique os logs do servidor.', 'error')
                
        return redirect(url_for('client.faturas'))

    faturas_db = Fatura.query.filter_by(user_id=current_user.id).order_by(Fatura.id.desc()).all()
    return render_template('client/faturas.html', user=current_user, faturas=faturas_db)

