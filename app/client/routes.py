import os
from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app import db
from app.models import Fatura
from app.utils.pdf_parser import extrair_dados_nota_corretagem

client_bp = Blueprint('client', __name__)

@client_bp.route('/dashboard')
@login_required
def dashboard():
    return render_template('client/index.html', user=current_user)

@client_bp.route('/faturas', methods=['GET', 'POST'])
@login_required
def faturas():
    if request.method == 'POST':
        f_id = request.form.get('fatura_id')
        pdf = request.files.get('relatorio_pdf')
        if pdf and pdf.filename.lower().endswith('.pdf'):
            path = os.path.join('/tmp', secure_filename(pdf.filename))
            pdf.save(path)
            dados = extrair_dados_nota_corretagem(path)
            os.remove(path) if os.path.exists(path) else None
            
            if dados:
                fatura = Fatura.query.get(f_id)
                if fatura and fatura.user_id == current_user.id:
                    fatura.bruto = dados['bruto']
                    fatura.liquido = dados['liquido']
                    # Regra: (Líquido - 19% IRRF) * 30% repasse
                    fatura.repasse = (dados['liquido'] * 0.81) * 0.30 if dados['liquido'] > 0 else 0.0
                    fatura.status = 'aguardando_pagamento'
                    db.session.commit()
                    flash('Nota processada!')
        return redirect(url_for('client.faturas'))
    
    faturas = Fatura.query.filter_by(user_id=current_user.id).order_by(Fatura.id.desc()).all()
    return render_template('client/faturas.html', user=current_user, faturas=faturas)

