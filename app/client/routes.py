import os
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, jsonify
from flask_login import login_required, current_user
import cloudinary.uploader
from app import db
from app.models import FaturaDiaria, Fatura
from app.utils.pdf_parser import extrair_dados_nota_corretagem

client_bp = Blueprint('client', __name__, url_prefix='/portal')

def atualizar_totais_semana(fatura):
    fatura.bruto = sum(d.bruto for d in fatura.dias if d.status == 'relatorio_enviado')
    fatura.taxas_b3 = sum(d.taxas_b3 for d in fatura.dias if d.status == 'relatorio_enviado')
    fatura.irrf_1 = sum(d.irrf_1 for d in fatura.dias if d.status == 'relatorio_enviado')
    fatura.liquido_pregao = sum(d.liquido_pregao for d in fatura.dias if d.status == 'relatorio_enviado')
    fatura.irrf_19 = sum(d.irrf_19 for d in fatura.dias if d.status == 'relatorio_enviado')
    fatura.liquido = sum(d.liquido for d in fatura.dias if d.status == 'relatorio_enviado')
    fatura.repasse = sum(d.repasse for d in fatura.dias if d.status == 'relatorio_enviado')
    fatura.status = 'relatorio_enviado' if all(d.status == 'relatorio_enviado' for d in fatura.dias) else 'parcial'
    db.session.commit()

@client_bp.route('/dashboard')
@login_required
def dashboard(): return render_template('client/index.html', user=current_user)

@client_bp.route('/faturas', methods=['GET', 'POST'])
@login_required
def faturas():
    if request.method == 'POST':
        dia_id = request.form.get('dia_id')
        arquivo = request.files.get('relatorio_pdf')
        if arquivo and arquivo.filename:
            file_path = os.path.join(current_app.root_path, 'static', 'uploads', arquivo.filename)
            arquivo.save(file_path)
            dia = FaturaDiaria.query.get(dia_id)
            dados = extrair_dados_nota_corretagem(file_path)
            
            if not dados or dados.get('data_pregao') != dia.data_pregao.strftime('%d/%m/%Y'):
                os.remove(file_path)
                flash('PDF Inválido ou data incorreta.', 'danger')
                return redirect(url_for('client.faturas'))
            
            try:
                # Upload direto pra nuvem
                upload_res = cloudinary.uploader.upload(file_path, folder="dwcapital/relatorios", resource_type="raw")
                dia.arquivo_pdf = upload_res.get('secure_url')
                dia.bruto, dia.taxas_b3, dia.irrf_1 = dados.get('bruto'), dados.get('taxas_b3'), dados.get('irrf_1')
                dia.liquido_pregao, dia.irrf_19, dia.liquido = dados.get('liquido_pregao'), dados.get('irrf_19'), dados.get('liquido_dia')
                dia.repasse = dados.get('repasse_dw')
                dia.status = 'relatorio_enviado'
                db.session.commit()
                os.remove(file_path)
                atualizar_totais_semana(dia.fatura_semanal)
                flash('Relatório salvo na nuvem!', 'success')
            except: flash('Erro na nuvem.', 'danger')
    return render_template('client/faturas.html', user=current_user, faturas=current_user.faturas)

@client_bp.route('/faturas/comprovante/<int:fatura_id>', methods=['POST'])
@login_required
def enviar_comprovante(fatura_id):
    fatura = Fatura.query.get_or_404(fatura_id)
    arquivo = request.files.get('comprovante')
    if arquivo:
        try:
            # Cloudinary faz o trabalho de otimizar a imagem aqui
            res = cloudinary.uploader.upload(arquivo, folder="dwcapital/comprovantes")
            fatura.comprovante_pix = res.get('secure_url')
            db.session.commit()
            flash('Comprovante enviado!', 'success')
        except: flash('Erro ao enviar comprovante.', 'danger')
    return redirect(url_for('client.faturas'))

@client_bp.route('/faturas/remover/<int:dia_id>', methods=['POST'])
@login_required
def remover_fatura(dia_id):
    dia = FaturaDiaria.query.get_or_404(dia_id)
    dia.arquivo_pdf, dia.status = None, 'pendente'
    db.session.commit()
    atualizar_totais_semana(dia.fatura_semanal)
    return redirect(url_for('client.faturas'))

