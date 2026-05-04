import os
import time
from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app import db
from app.models import Fatura
from app.utils.pdf_parser import extrair_dados_nota_corretagem

client_bp = Blueprint('client', __name__, url_prefix='/portal')

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
            # Cria a pasta de uploads caso não exista
            upload_folder = os.path.join(current_app.root_path, 'static', 'uploads')
            os.makedirs(upload_folder, exist_ok=True)
            
            # Gera nome único para o PDF para evitar conflitos
            nome_seguro = secure_filename(pdf.filename)
            nome_arquivo = f"user_{current_user.id}_{int(time.time())}_{nome_seguro}"
            path = os.path.join(upload_folder, nome_arquivo)
            
            pdf.save(path)
            dados = extrair_dados_nota_corretagem(path)
            # Obs: Não usamos mais os.remove(path) pois o admin precisa ver o arquivo!
            
            if dados:
                fatura = Fatura.query.get(f_id)
                if fatura and fatura.user_id == current_user.id:
                    fatura.bruto = dados['bruto']
                    fatura.liquido = dados['liquido']
                    fatura.irrf_1 = dados['irrf_1']
                    fatura.taxas_b3 = dados['taxas_b3']
                    fatura.repasse = (dados['liquido'] * 0.81) * 0.30 if dados['liquido'] > 0 else 0.0
                    fatura.arquivo_pdf = nome_arquivo # Salva no banco
                    fatura.status = 'relatorio_enviado'
                    
                    db.session.commit()
                    flash('PDF processado e enviado com sucesso!', 'success')
            else:
                flash('Não foi possível ler os dados da sua Nota de Corretagem.', 'error')
                
        return redirect(url_for('client.faturas'))
    
    faturas_lista = Fatura.query.filter_by(user_id=current_user.id).order_by(Fatura.id.desc()).all()
    return render_template('client/faturas.html', user=current_user, faturas=faturas_lista)

