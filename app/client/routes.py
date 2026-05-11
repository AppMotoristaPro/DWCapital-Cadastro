import os
import urllib.parse
from datetime import datetime, timedelta
import pytz
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, jsonify
from flask_login import login_required, current_user
import cloudinary.uploader
from app import db
from app.models import FaturaDiaria, Fatura, AlocacaoCorretora, DocumentoCliente
from app.utils.autentique import criar_documento_autentique, verificar_status_autentique
from app.utils.parsers.gerenciador_pdf import processar_pdf
from sqlalchemy.exc import IntegrityError

tz_br = pytz.timezone('America/Sao_Paulo')
client_bp = Blueprint('client', __name__, url_prefix='/portal')

def atualizar_totais_semana(fatura):
    fatura.bruto = sum((d.bruto if d.bruto > 0 else 0.0) for d in fatura.dias if d.status == 'relatorio_enviado')
    fatura.taxas_b3 = sum((d.taxas_b3 if d.taxas_b3 > 0 else 0.0) for d in fatura.dias if d.status == 'relatorio_enviado')
    fatura.irrf_1 = sum((d.irrf_1 if d.irrf_1 > 0 else 0.0) for d in fatura.dias if d.status == 'relatorio_enviado')
    fatura.liquido_pregao = sum((d.liquido_pregao if d.liquido_pregao > 0 else 0.0) for d in fatura.dias if d.status == 'relatorio_enviado')
    fatura.irrf_19 = sum((d.irrf_19 if d.irrf_19 > 0 else 0.0) for d in fatura.dias if d.status == 'relatorio_enviado')
    fatura.liquido = sum((d.liquido if d.liquido > 0 else 0.0) for d in fatura.dias if d.status == 'relatorio_enviado')
    fatura.repasse = sum((d.repasse if d.repasse > 0 else 0.0) for d in fatura.dias if d.status == 'relatorio_enviado')
    
    dias_enviados = sum(1 for d in fatura.dias if d.status == 'relatorio_enviado')
    dias_isentos = sum(1 for d in fatura.dias if d.status == 'isento')
    total_exigido = len(fatura.dias) - dias_isentos
    
    if dias_enviados == 0:
        if total_exigido == 0 and len(fatura.dias) > 0:
            fatura.status = 'completo'
        else:
            fatura.status = 'pendente'
    elif dias_enviados >= total_exigido and total_exigido > 0:
        fatura.status = 'completo'
    else:
        fatura.status = 'parcial'
        
    db.session.commit()

def auto_gerar_ciclo_atual(user):
    if not user.alocacoes:
        return

    hoje = datetime.now(tz_br).date()
    dias_para_sexta = (hoje.weekday() - 4) % 7
    inicio_ciclo = hoje - timedelta(days=dias_para_sexta)
    fim_ciclo = inicio_ciclo + timedelta(days=6)

    fatura_existente = Fatura.query.filter_by(user_id=user.id, data_inicio=inicio_ciclo).first()

    if not fatura_existente:
        nova_fatura = Fatura(
            user_id=user.id,
            data_inicio=inicio_ciclo,
            data_fim=fim_ciclo,
            status='pendente'
        )
        db.session.add(nova_fatura)
        
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return

        data_atual = inicio_ciclo
        dias_uteis = []
        while len(dias_uteis) < 5 and data_atual <= fim_ciclo:
            if data_atual.weekday() < 5:
                dias_uteis.append(data_atual)
            data_atual += timedelta(days=1)

        for data in dias_uteis:
            for alocacao in user.alocacoes:
                existe = FaturaDiaria.query.filter_by(fatura_id=nova_fatura.id, data_pregao=data, nome_corretora=alocacao.nome_corretora).first()
                if not existe:
                    novo_dia = FaturaDiaria(
                        fatura_id=nova_fatura.id,
                        data_pregao=data,
                        nome_corretora=alocacao.nome_corretora,
                        status='pendente'
                    )
                    db.session.add(novo_dia)
        
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()

@client_bp.route('/dashboard')
@login_required
def dashboard():
    if getattr(current_user, 'precisa_trocar_senha', False):
        return redirect(url_for('auth.forcar_troca_senha'))
    if not current_user.termo_assinado:
        return redirect(url_for('client.assinar_termo'))
        
    auto_gerar_ciclo_atual(current_user)
    
    fatura_atual = Fatura.query.filter_by(user_id=current_user.id).order_by(Fatura.data_inicio.desc()).first()
    
    bruto_semana = fatura_atual.bruto if fatura_atual else 0.0
    dias_enviados = sum(1 for d in fatura_atual.dias if d.status == 'relatorio_enviado') if fatura_atual else 0
    media_diaria = (bruto_semana / dias_enviados) if dias_enviados > 0 else 0.0
    
    return render_template('client/index.html', user=current_user, bruto_semana=bruto_semana, media_diaria=media_diaria)

@client_bp.route('/assinar')
@login_required
def assinar_termo():
    if current_user.termo_assinado: return redirect(url_for('client.dashboard'))
    documento_enviado = bool(current_user.docusign_envelope_id)
    if not documento_enviado:
        caminho_pdf = os.path.join(current_app.root_path, 'static', 'documentos', 'termo_adesao.pdf')
        try:
            doc_id = criar_documento_autentique(
                nome_signer=current_user.nome,
                email_signer=current_user.email,
                caminho_pdf=caminho_pdf
            )
            current_user.docusign_envelope_id = doc_id 
            db.session.commit()
            documento_enviado = True
        except Exception as e:
            flash(f"Erro ao gerar contrato: {str(e)}", "danger")
    return render_template('client/assinar_termo.html', documento_enviado=documento_enviado)

@client_bp.route('/api/status_assinatura')
@login_required
def api_status_assinatura():
    doc_id = current_user.docusign_envelope_id
    if not doc_id: return jsonify({"assinado": False})
    try:
        if verificar_status_autentique(doc_id):
            current_user.termo_assinado = True
            db.session.commit()
            return jsonify({"assinado": True})
    except: pass
    return jsonify({"assinado": False})

@client_bp.route('/dados_pessoais')
@login_required
def dados_pessoais():
    return render_template('client/dados_pessoais.html', user=current_user)

@client_bp.route('/faturas', methods=['GET', 'POST'])
@login_required
def faturas():
    auto_gerar_ciclo_atual(current_user)

    if request.method == 'GET':
        for fatura in current_user.faturas:
            for dia in list(fatura.dias):
                if dia.data_pregao.weekday() >= 5:
                    db.session.delete(dia)
            db.session.commit()

            datas_da_semana = []
            data_atual = fatura.data_inicio
            while len(datas_da_semana) < 5:
                if data_atual.weekday() < 5:
                    datas_da_semana.append(data_atual)
                data_atual += timedelta(days=1)
                
            for data in datas_da_semana:
                for alocacao in current_user.alocacoes:
                    dia_existente = FaturaDiaria.query.filter_by(
                        fatura_id=fatura.id, 
                        data_pregao=data, 
                        nome_corretora=alocacao.nome_corretora
                    ).first()
                    if not dia_existente:
                        novo_dia = FaturaDiaria(
                            fatura_id=fatura.id, 
                            data_pregao=data, 
                            nome_corretora=alocacao.nome_corretora, 
                            status='pendente'
                        )
                        db.session.add(novo_dia)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()

    if request.method == 'POST':
        dia_id = request.form.get('dia_id')
        senha_manual = request.form.get('senha_manual')
        arquivo = request.files.get('relatorio_pdf')
        
        if arquivo and arquivo.filename:
            upload_folder = os.path.join(current_app.root_path, 'static', 'uploads')
            os.makedirs(upload_folder, exist_ok=True)
            file_path = os.path.join(upload_folder, arquivo.filename)
            arquivo.save(file_path)
            
            dia = FaturaDiaria.query.get(dia_id)
            
            try:
                dados = processar_pdf(file_path, dia.nome_corretora, current_user.cpf, senha_manual)
                
                bloq_data_env = os.environ.get('BLOQ_DATA', 'False').lower()
                bloquear_data = bloq_data_env in ('true', '1', 't')
                
                if not dados:
                    if os.path.exists(file_path): os.remove(file_path)
                    return jsonify({'success': False, 'error': 'RELATORIO_INVALIDO', 'message': 'Não foi possível ler os dados do PDF.'})

                data_pdf = dados.get('data_pregao')
                data_esperada = dia.data_pregao.strftime('%d/%m/%Y')
                
                if bloquear_data and data_pdf != data_esperada:
                    if os.path.exists(file_path): os.remove(file_path)
                    return jsonify({'success': False, 'error': 'RELATORIO_INVALIDO', 'message': f'Data incorreta. Esperado: {data_esperada}.'})

                upload_res = cloudinary.uploader.upload(file_path, folder="dwcapital/relatorios")
                
                dia.arquivo_pdf = upload_res.get('secure_url')
                dia.bruto = dados.get('bruto')
                dia.taxas_b3 = dados.get('taxas_b3')
                dia.irrf_1 = dados.get('irrf_1')
                dia.liquido_pregao = dados.get('liquido_pregao')
                dia.irrf_19 = dados.get('irrf_19')
                dia.liquido = dados.get('liquido_dia')
                
                if getattr(current_user, 'is_isento', False):
                    dia.repasse = 0.0
                else:
                    dia.repasse = dados.get('repasse_dw')
                    
                dia.status = 'relatorio_enviado'
                
                db.session.commit()
                atualizar_totais_semana(dia.fatura_semanal)
                
                if os.path.exists(file_path): os.remove(file_path)
                return jsonify({'success': True})

            except Exception as e:
                if os.path.exists(file_path): os.remove(file_path)
                
                if "SENHA_INCORRETA" in str(e):
                    return jsonify({'success': False, 'error': 'REQUER_SENHA'})
                
                return jsonify({'success': False, 'error': 'ERRO_TECNICO', 'message': str(e)})

    return render_template('client/faturas.html', faturas=current_user.faturas)

@client_bp.route('/faturas/comprovante/<int:fatura_id>', methods=['POST'])
@login_required
def enviar_comprovante(fatura_id):
    fatura = Fatura.query.get_or_404(fatura_id)
    arquivo = request.files.get('comprovante')
    if arquivo:
        try:
            res = cloudinary.uploader.upload(arquivo, folder="dwcapital/comprovantes", resource_type="image")
            fatura.comprovante_pix = res.get('secure_url')
            db.session.commit()
            flash('Comprovante enviado com sucesso!', 'success')
        except Exception as e:
            flash(f"Erro ao enviar para nuvem: {str(e)}", "danger")
    return redirect(url_for('client.faturas'))

@client_bp.route('/faturas/remover/<int:dia_id>', methods=['POST'])
@login_required
def remover_fatura(dia_id):
    dia = FaturaDiaria.query.get_or_404(dia_id)
    dia.arquivo_pdf = None
    dia.status = 'pendente'
    db.session.commit()
    atualizar_totais_semana(dia.fatura_semanal)
    return redirect(url_for('client.faturas'))

# --- FASE 4: COFRE DE CONTRATOS DO CLIENTE ---
@client_bp.route('/documentos')
@login_required
def documentos():
    # 1. Puxa as pendências do banco e verifica na API Autentique se o cliente já assinou.
    pendentes = DocumentoCliente.query.filter_by(user_id=current_user.id, status='pendente').all()
    atualizou_algum = False
    
    for doc in pendentes:
        if verificar_status_autentique(doc.autentique_document_id):
            doc.status = 'assinado'
            doc.data_assinatura = datetime.now(tz_br)
            atualizou_algum = True
            
    if atualizou_algum:
        db.session.commit()
        
    # 2. Mostra os documentos na tela
    meus_docs = DocumentoCliente.query.filter_by(user_id=current_user.id).order_by(DocumentoCliente.data_envio.desc()).all()
    return render_template('client/documentos.html', documentos=meus_docs)

@client_bp.route('/ajuda')
@login_required
def ajuda():
    mensagem = f"Olá, sou {current_user.nome}. Preciso de suporte referente ao portal DW Capital."
    msg_encoded = urllib.parse.quote(mensagem)
    return render_template('client/ajuda.html', link_suporte=f"https://wa.me/5511991167709?text={msg_encoded}")

