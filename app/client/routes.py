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

@client_bp.route('/dashboard')
@login_required
def dashboard():
    return render_template('client/index.html', user=current_user)

@client_bp.route('/faturas', methods=['GET', 'POST'])
@login_required
def faturas():
    if request.method == 'POST':
        fatura_id = request.form.get('fatura_id')
        arquivo_pdf = request.files.get('relatorio_pdf')
        
        if arquivo_pdf and arquivo_pdf.filename.lower().endswith('.pdf'):
            filename = secure_filename(arquivo_pdf.filename)
            filepath = os.path.join('/tmp', filename)
            arquivo_pdf.save(filepath)
            
            # Extração dos dados baseada na Nota da Genial
            bruto, liquido = extrair_dados_nota_corretagem(filepath)
            
            if os.path.exists(filepath):
                os.remove(filepath)
                
            if bruto is not None and liquido is not None:
                fatura = Fatura.query.get(fatura_id)
                if fatura and fatura.user_id == current_user.id:
                    fatura.bruto = bruto
                    fatura.liquido = liquido
                    # Cálculo de 30% sobre o líquido positivo
                    fatura.repasse = liquido * 0.30 if liquido > 0 else 0.0
                    fatura.status = 'aguardando_pagamento'
                    db.session.commit()
                    flash('Nota de Corretagem processada com sucesso!', 'success')
                else:
                    flash('Fatura não encontrada.')
            else:
                flash('Erro ao ler valores. Use o PDF original.')
        else:
            flash('Envie um arquivo PDF válido.')
        return redirect(url_for('client.faturas'))

    faturas_db = Fatura.query.filter_by(user_id=current_user.id).order_by(Fatura.id.desc()).all()
    return render_template('client/faturas.html', user=current_user, faturas=faturas_db)

@client_bp.route('/perfil', methods=['GET', 'POST'])
@login_required
def perfil():
    if request.method == 'POST':
        current_user.nome = request.form.get('nome')
        current_user.corretora = request.form.get('corretora')
        current_user.perfil_risco = request.form.get('perfil_risco')
        db.session.commit()
        flash('Dados atualizados!', 'success')
        return redirect(url_for('client.perfil'))
    return render_template('client/perfil.html', user=current_user)

