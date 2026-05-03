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
    # Fix: Redireciona a raiz para o login
    return redirect(url_for('auth.login'))

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
            if os.path.exists(path): os.remove(path)
            
            if dados:
                fatura = Fatura.query.get(f_id)
                if fatura and fatura.user_id == current_user.id:
                    fatura.bruto = dados['bruto']
                    fatura.liquido = dados['liquido']
                    # Regra: (Líquido - 19% IRRF) * 30% repasse
                    fatura.repasse = (dados['liquido'] * 0.81) * 0.30 if dados['liquido'] > 0 else 0.0
                    fatura.status = 'aguardando_pagamento'
                    db.session.commit()
                    flash('Nota processada com sucesso!', 'success')
            else:
                flash('Não foi possível ler os dados do PDF.', 'error')
        return redirect(url_for('client.faturas'))
    
    faturas = Fatura.query.filter_by(user_id=current_user.id).order_by(Fatura.id.desc()).all()
    return render_template('client/faturas.html', user=current_user, faturas=faturas)

@client_bp.route('/perfil', methods=['GET', 'POST'])
@login_required
def perfil():
    if request.method == 'POST':
        current_user.nome = request.form.get('nome')
        current_user.corretora = request.form.get('corretora')
        current_user.perfil_risco = request.form.get('perfil_risco')
        db.session.commit()
        flash('Perfil atualizado!')
    return render_template('client/perfil.html', user=current_user)

