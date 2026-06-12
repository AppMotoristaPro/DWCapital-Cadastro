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
from app.services.robo_service import (
    versao_atual, liberado_para_download, registrar_download, historico_downloads_cliente,
    obter_produtos_ativos, liberado_para_download_produto, registrar_download_produto,
    obter_produto_baixado_no_ciclo_atual
)
from app.services.licenca_service import (
    gerar_licenca_comissao,
    obter_licenca_ativa,
    salvar_conta_mt5_e_gerar_vitalicia_se_necessario,
    is_modo_teste,
    is_licenca_bloqueada,
    calcular_ciclo_por_data
)

logger = logging.getLogger(__name__)
tz_br = pytz.timezone('America/Sao_Paulo')
licenca_bp = Blueprint('licenca', __name__, url_prefix='/licenca')


@licenca_bp.route('/robo')
@login_required
def robo_download():
    """Página principal de download – exibe os 3 robôs disponíveis."""
    produtos = obter_produtos_ativos()
    ciclo_inicio, _ = calcular_ciclo_por_data()

    for p in produtos:
        if p['disponivel']:
            liberado, msg, _ = liberado_para_download_produto(current_user, p['produto'].id, ciclo_inicio)
            p['liberado'] = liberado
            p['mensagem'] = msg
        else:
            p['liberado'] = False
            p['mensagem'] = "Robô sem versão publicada"

    historico = historico_downloads_cliente(current_user)

    return render_template(
        'client/robo_download.html',
        produtos=produtos,
        historico=historico
    )


@licenca_bp.route('/download/<int:produto_id>', methods=['POST'])
@login_required
@limiter.limit("3 per minute")
def baixar_robo_produto(produto_id):
    """Baixa um robô específico – NÃO exige licença ativa."""
    try:
        # Log 1: início da requisição
        logger.info(f"[DOWNLOAD] Iniciando download para user={current_user.id}, produto={produto_id}")

        ciclo_inicio, _ = calcular_ciclo_por_data()
        logger.info(f"[DOWNLOAD] Ciclo calculado: inicio={ciclo_inicio}")

        liberado, msg, versao = liberado_para_download_produto(current_user, produto_id, ciclo_inicio)
        logger.info(f"[DOWNLOAD] liberado_para_download_produto retornou: liberado={liberado}, msg='{msg}', versao={versao.id if versao else None}")

        if not liberado:
            logger.warning(f"[DOWNLOAD] Bloqueado: {msg}")
            return jsonify({"error": msg}), 403

        # Baixar arquivo do Cloudinary
        logger.info(f"[DOWNLOAD] Baixando arquivo do Cloudinary: {versao.arquivo_url}")
        response = requests.get(versao.arquivo_url, stream=True, timeout=30)
        response.raise_for_status()
        logger.info(f"[DOWNLOAD] Arquivo baixado com sucesso, tamanho: {len(response.content)} bytes")

        # Registrar download
        registrar_download_produto(current_user, versao, ciclo_inicio)
        logger.info(f"[DOWNLOAD] Download registrado com sucesso")

        nome_arquivo = f"dwcapital_{versao.versao}{versao.extensao or '.exe'}"
        logger.info(f"[DOWNLOAD] Enviando arquivo ao cliente: {nome_arquivo}")

        return send_file(
            io.BytesIO(response.content),
            as_attachment=True,
            download_name=nome_arquivo,
            mimetype='application/octet-stream'
        )
    except Exception as e:
        logger.exception(f"[DOWNLOAD] Erro inesperado: {str(e)}")
        return jsonify({"error": f"Erro interno: {str(e)}"}), 500

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

    produto_id = obter_produto_baixado_no_ciclo_atual(current_user)
    if not produto_id:
        return jsonify({
            "success": False,
            "error": "PRECISA_BAIXAR",
            "message": "Você precisa baixar um robô antes de gerar a licença. Escolha um robô na página de download."
        }), 400

    chave, msg, licenca_obj, ja_existente = gerar_licenca_comissao(
        current_user, 
        current_user.conta_mt5, 
        produto_id=produto_id
    )
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


# ========== ROTAS ANTIGAS ==========

@licenca_bp.route('/robo/download', methods=['POST'])
@login_required
@limiter.limit("3 per minute")
def baixar_robo_antigo():
    from app.models import ProdutoRobo
    primeiro_produto = ProdutoRobo.query.order_by(ProdutoRobo.ordem).first()
    if primeiro_produto:
        return baixar_robo_produto(primeiro_produto.id)
    return jsonify({"error": "Nenhum robô disponível"}), 404


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