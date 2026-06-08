from datetime import datetime
import os
import io
import logging
import pytz
import requests
from flask import Blueprint, flash, render_template, jsonify, request, send_file
from flask_login import login_required, current_user
from app import db, limiter
from app.models import User
from app.services.robo_service import versao_atual, liberado_para_download, registrar_download, historico_downloads_cliente
from app.services.licenca_service import (
    gerar_licenca_comissao,
    obter_licenca_ativa,
    salvar_conta_mt5_e_gerar_vitalicia_se_necessario,
    is_modo_teste,
    is_licenca_bloqueada
)

logger = logging.getLogger(__name__)
tz_br = pytz.timezone('America/Sao_Paulo')
licenca_bp = Blueprint('licenca', __name__, url_prefix='/licenca')


@licenca_bp.route('/robo')
@login_required
def robo_download():
    versao = versao_atual()
    if not versao:
        flash("Nenhuma versão do robô disponível no momento.", "warning")  # Importar flash
        return render_template('client/robo_download.html', versao=None, botao_liberado=False, historico=[])
    
    liberado, msg = liberado_para_download(current_user, versao)
    historico = historico_downloads_cliente(current_user)
    
    return render_template(
        'client/robo_download.html',
        versao=versao,
        botao_liberado=liberado,
        msg_bloqueio=msg if not liberado else None,
        historico=historico
    )


@licenca_bp.route('/robo/download', methods=['POST'])
@login_required
@limiter.limit("3 per minute")
def baixar_robo():
    versao = versao_atual()
    if not versao:
        return jsonify({"error": "Nenhuma versão disponível"}), 404
    
    liberado, msg = liberado_para_download(current_user, versao)
    if not liberado:
        return jsonify({"error": msg}), 403
    
    registrar_download(current_user, versao.id)
    
    try:
        response = requests.get(versao.arquivo_url, stream=True, timeout=30)
        response.raise_for_status()
    except Exception as e:
        logger.error(f"Erro ao baixar arquivo do Cloudinary: {e}")
        return jsonify({"error": "Falha ao obter o arquivo do robô"}), 500
    
    extensao = versao.extensao if versao.extensao else '.exe'
    nome_arquivo = f"dwcapital_robo_v{versao.versao}{extensao}"
    
    return send_file(
        io.BytesIO(response.content),
        as_attachment=True,
        download_name=nome_arquivo,
        mimetype='application/octet-stream'
    )


@licenca_bp.route('/status', methods=['GET'])
@login_required
def licenca_status():
    licenca = obter_licenca_ativa(current_user)
    if licenca:
        return jsonify({
            "success": True,
            "tem_licenca": True,
            "tipo": licenca.tipo,
            "chave": licenca.chave_licenca,
            "validade": licenca.data_expiracao.strftime('%d/%m/%Y %H:%M') if licenca.data_expiracao else "Vitalícia",
            "status": licenca.status
        })
    else:
        return jsonify({
            "success": True,
            "tem_licenca": False
        })


@licenca_bp.route('/gerar', methods=['POST'])
@login_required
@limiter.limit("10 per minute", key_func=lambda: current_user.id)
def licenca_gerar():
    if is_licenca_bloqueada(current_user):
        return jsonify({
            "success": False,
            "error": "BLOQUEADO",
            "message": "A geração de licenças está bloqueada para este cliente. Entre em contato com o suporte."
        }), 403
    
    hoje = datetime.now(tz_br).date()
    if not is_modo_teste():
        if hoje.weekday() >= 5:
            return jsonify({
                "success": False,
                "error": "DIA_INVALIDO",
                "message": "A geração de licenças semanais só é permitida em dias úteis (segunda a sexta)."
            }), 400
    
    if not current_user.conta_mt5:
        return jsonify({
            "success": False,
            "error": "PRECISA_CONTA",
            "message": "Você precisa cadastrar sua conta MT5 antes de gerar a licença."
        }), 200
    
    chave, msg, licenca_obj, ja_existente = gerar_licenca_comissao(current_user, current_user.conta_mt5)
    if not chave:
        return jsonify({
            "success": False,
            "error": "CONDICOES_NAO_ATENDIDAS",
            "message": msg
        }), 400
    
    return jsonify({
        "success": True,
        "chave": chave,
        "message": msg,
        "validade": licenca_obj.data_expiracao.strftime('%d/%m/%Y %H:%M') if licenca_obj.data_expiracao else None,
        "ja_existente": ja_existente
    })


@licenca_bp.route('/visualizar', methods=['POST'])
@login_required
def licenca_visualizar():
    return licenca_gerar()


@licenca_bp.route('/api/salvar_conta_mt5', methods=['POST'])
@login_required
@limiter.limit("5 per minute")
def api_salvar_conta_mt5():
    data = request.get_json()
    nova_conta = data.get('conta_mt5', '').strip()
    if not nova_conta:
        return jsonify({"success": False, "message": "Número da conta MT5 é obrigatório."}), 400
    
    if not nova_conta.isdigit():
        return jsonify({"success": False, "message": "A conta MT5 deve conter apenas números."}), 400
    
    gerou, chave, msg = salvar_conta_mt5_e_gerar_vitalicia_se_necessario(current_user, nova_conta)
    
    return jsonify({
        "success": True,
        "conta_salva": nova_conta,
        "licenca_gerada": gerou,
        "chave_licenca": chave,
        "message": msg
    })