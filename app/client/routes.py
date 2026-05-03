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
            dados = extrair_dados_nota_corretagem(path)
            if os.path.exists(path): os.remove(path)
            
            if dados:
                fatura = Fatura.query.get(f_id)
                if fatura and fatura.user_id == current_user.id:
                    fatura.bruto = dados['bruto']
                    fatura.liquido = dados['liquido']
                    fatura.irrf_1 = dados['irrf_1']
                    fatura.taxas_b3 = dados['taxas_b3']
                    
                    if dados['liquido'] > 0:
                        # Regra: Líquido da nota - 19% (IRRF restante) -> 30% DW
                        base_dw = dados['liquido'] * 0.81
                        fatura.repasse = base_dw * 0.30
                    else:
                        fatura.repasse = 0.0
                        
                    fatura.status = 'aguardando_pagamento'
                    db.session.commit()
                    flash('Declaração processada com sucesso!', 'success')
            else:
                flash('Erro ao ler PDF. Tente novamente.', 'error')
        return redirect(url_for('client.faturas'))

    faturas_db = Fatura.query.filter_by(user_id=current_user.id).order_by(Fatura.id.desc()).all()
    return render_template('client/faturas.html', user=current_user, faturas=faturas_db)

@client_bp.route('/faturas/excluir/<int:id>', methods=['POST'])
@login_required
def excluir_fatura(id):
    fatura = Fatura.query.get_or_404(id)
    if fatura.user_id == current_user.id:
        # Resetamos os valores e voltamos o status para pendente
        fatura.bruto = 0
        fatura.liquido = 0
        fatura.irrf_1 = 0
        fatura.taxas_b3 = 0
        fatura.repasse = 0
        fatura.status = 'pendente'
        db.session.commit()
        flash('Declaração excluída. Você pode enviar o arquivo novamente.', 'info')
    return redirect(url_for('client.faturas'))

