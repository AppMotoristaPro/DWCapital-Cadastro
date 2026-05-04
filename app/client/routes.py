import os
import time
from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app import db
from app.models import Fatura, FaturaDiaria
from app.utils.pdf_parser import extrair_dados_nota_corretagem
from app.utils.docusign import criar_envelope_embedded, gerar_url_assinatura

client_bp = Blueprint('client', __name__, url_prefix='/portal')

# O PEDÁGIO DE ASSINATURA
@client_bp.before_request
def check_assinatura():
    if not current_user.is_authenticated or current_user.role == 'admin':
        return
    
    rotas_livres = ['client.assinar_termo', 'client.retorno_assinatura', 'auth.logout', 'static']
    if request.endpoint not in rotas_livres and not current_user.termo_assinado:
        return redirect(url_for('client.assinar_termo'))

# NOVA ROTA: Tela de Bloqueio e Geração da Assinatura
@client_bp.route('/assinar', methods=['GET', 'POST'])
@login_required
def assinar_termo():
    if current_user.termo_assinado:
        return redirect(url_for('client.dashboard'))
        
    if request.method == 'POST':
        try:
            email_valido = current_user.email if current_user.email else "suporte@dwcapital.com"
            envelope_id = criar_envelope_embedded(current_user.nome, email_valido, str(current_user.id))
            
            current_user.docusign_envelope_id = envelope_id
            db.session.commit()
            
            return_url = url_for('client.retorno_assinatura', _external=True)
            url_docusign = gerar_url_assinatura(envelope_id, current_user.nome, email_valido, str(current_user.id), return_url)
            
            return redirect(url_docusign)
        except Exception as e:
            flash(f'Falha ao conectar com o serviço de contratos: {str(e)}', 'error')
            return redirect(url_for('client.assinar_termo'))

    return render_template('client/assinar_termo.html', user=current_user)

# NOVA ROTA: O Retorno após o cliente assinar o contrato na DocuSign
@client_bp.route('/retorno_assinatura')
@login_required
def retorno_assinatura():
    event = request.args.get('event')
    if event == 'signing_complete':
        current_user.termo_assinado = True
        db.session.commit()
        flash('Contrato assinado com sucesso! Painel liberado.', 'success')
        return redirect(url_for('client.dashboard'))
    else:
        flash('Assinatura não concluída ou cancelada. O painel continua bloqueado.', 'error')
        return redirect(url_for('client.assinar_termo'))

@client_bp.route('/dashboard')
@login_required
def dashboard():
    return render_template('client/index.html', user=current_user)

@client_bp.route('/dados')
@login_required
def dados_pessoais():
    return render_template('client/dados_pessoais.html', user=current_user)

@client_bp.route('/faturas', methods=['GET', 'POST'])
@login_required
def faturas():
    if request.method == 'POST':
        dia_id = request.form.get('dia_id')
        pdf = request.files.get('relatorio_pdf')
        
        if pdf and pdf.filename.lower().endswith('.pdf'):
            dia = FaturaDiaria.query.get(dia_id)
            if not dia or dia.fatura_semanal.user_id != current_user.id:
                flash('Sessão inválida.', 'error')
                return redirect(url_for('client.faturas'))

            upload_folder = os.path.join(current_app.root_path, 'static', 'uploads')
            os.makedirs(upload_folder, exist_ok=True)
            nome_arquivo = f"user_{current_user.id}_{int(time.time())}_{secure_filename(pdf.filename)}"
            path = os.path.join(upload_folder, nome_arquivo)
            
            pdf.save(path)
            dados = extrair_dados_nota_corretagem(path)
            
            if dados:
                data_esperada = dia.data_pregao.strftime('%d/%m/%Y')
                if dados['data_pregao'] != data_esperada:
                    os.remove(path)
                    flash(f'Bloqueio: Você enviou um relatório do dia {dados["data_pregao"] or "desconhecido"} no espaço do dia {data_esperada}.', 'error')
                    return redirect(url_for('client.faturas'))

                dia.bruto = dados['bruto']
                dia.liquido = dados['liquido']
                dia.irrf_1 = dados['irrf_1']
                dia.taxas_b3 = dados['taxas_b3']
                dia.repasse = (dados['liquido'] * 0.81) * 0.30 if dados['liquido'] > 0 else 0.0
                dia.arquivo_pdf = nome_arquivo
                dia.status = 'relatorio_enviado'
                
                fatura_semanal = dia.fatura_semanal
                fatura_semanal.bruto = sum(d.bruto for d in fatura_semanal.dias)
                fatura_semanal.liquido = sum(d.liquido for d in fatura_semanal.dias)
                fatura_semanal.irrf_1 = sum(d.irrf_1 for d in fatura_semanal.dias)
                fatura_semanal.taxas_b3 = sum(d.taxas_b3 for d in fatura_semanal.dias)
                fatura_semanal.repasse = sum(d.repasse for d in fatura_semanal.dias)
                
                if fatura_semanal.status == 'pendente':
                    fatura_semanal.status = 'parcial'

                db.session.commit()
                flash('Relatório diário processado com sucesso!', 'success')
            else:
                flash('Erro na leitura da Nota de Corretagem.', 'error')
                
        return redirect(url_for('client.faturas'))
    
    faturas_lista = Fatura.query.filter_by(user_id=current_user.id).order_by(Fatura.data_inicio.desc()).all()
    return render_template('client/faturas.html', user=current_user, faturas=faturas_lista)

