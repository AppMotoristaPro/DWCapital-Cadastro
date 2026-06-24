from datetime import datetime
import os
import io
import logging
import pytz
import requests
from flask import Blueprint, flash, render_template, jsonify, request, send_file
from flask_login import login_required, current_user
from app import db, limiter
from app.models import User, ContaMT5Cliente, ProdutoRobo, VersaoRobo
from app.services.robo_service import (
    obter_produtos_ativos, liberado_para_download_produto, registrar_download_produto,
    obter_produto_baixado_no_ciclo_atual_por_conta, historico_downloads_por_conta,
    conta_baixou_algum_produto_no_ciclo, cliente_ja_baixou_demo, registrar_download_demo
)
from app.services.licenca_service import (
    gerar_licenca_comissao,
    obter_licenca_ativa_por_conta,
    is_modo_teste,
    is_licenca_bloqueada,
    calcular_ciclo_por_data,
    gerar_licenca_vitalicia
)
from app.services.parcela_service import todas_parcelas_pagas

logger = logging.getLogger(__name__)
tz_br = pytz.timezone('America/Sao_Paulo')
licenca_bp = Blueprint('licenca', __name__, url_prefix='/licenca')


@licenca_bp.route('/robo')
@login_required
def robo_download():
    """Página principal de download – exibe os robôs disponíveis e contas disponíveis."""
    produtos = obter_produtos_ativos()
    ciclo_inicio, _ = calcular_ciclo_por_data()

    from app.services.conta_mt5_service import listar_contas
    contas_ativas = listar_contas(current_user.id, apenas_ativas=True)

    # Para cada produto, calcular quais contas ainda podem baixar neste ciclo
    for p in produtos:
        # Verifica se já baixou demo (apenas para produtos demo)
        if p['produto'].is_demo and p['versao']:
            p['ja_baixou'] = cliente_ja_baixou_demo(current_user.id, p['versao'].id)
        else:
            p['ja_baixou'] = False

        contas_disponiveis = []
        for conta in contas_ativas:
            if not conta_baixou_algum_produto_no_ciclo(conta.id, ciclo_inicio):
                contas_disponiveis.append(conta)
        p['contas_disponiveis'] = contas_disponiveis
        p['download_disponivel'] = len(contas_disponiveis) > 0
        p['mensagem'] = ""  # será preenchido se bloqueado

    # Se cliente compra já possui vínculo vitalício, bloqueia os outros produtos
    if current_user.modelo_negocio == 'compra' and current_user.produto_vitalicio_id:
        for p in produtos:
            if p['produto'].id != current_user.produto_vitalicio_id:
                p['download_disponivel'] = False
                p['mensagem'] = "Você já possui licença vitalícia para outro robô e não pode mais baixar este."

    # Histórico de downloads por conta
    historico_por_conta = []
    for conta in contas_ativas:
        hist = historico_downloads_por_conta(conta.id)
        if hist:
            historico_por_conta.append({
                'conta': conta.numero_conta,
                'downloads': hist
            })

    return render_template(
        'client/robo_download.html',
        produtos=produtos,
        historico_por_conta=historico_por_conta,
        contas_ativas=contas_ativas
    )


@licenca_bp.route('/download/<int:produto_id>', methods=['POST'])
@login_required
@limiter.limit("3 per minute")
def baixar_robo_produto(produto_id):
    """Baixa um robô específico – exige conta MT5 selecionada."""
    print(f"[DOWNLOAD] Requisição recebida: user={current_user.id}, produto={produto_id}")
    
    data = request.get_json()
    conta_mt5_id = data.get('conta_mt5_id') if data else None
    
    if not conta_mt5_id:
        return jsonify({"error": "Selecione uma conta MT5 para baixar o robô."}), 400
    
    conta = ContaMT5Cliente.query.filter_by(id=conta_mt5_id, user_id=current_user.id, ativo=True).first()
    if not conta:
        return jsonify({"error": "Conta MT5 inválida ou inativa."}), 400
    if conta.bloqueada:
        return jsonify({"error": "Esta conta MT5 está bloqueada pelo administrador."}), 403

    try:
        ciclo_inicio, _ = calcular_ciclo_por_data()
        print(f"[DOWNLOAD] Ciclo calculado: inicio={ciclo_inicio}")

        liberado, msg, versao = liberado_para_download_produto(
            current_user, produto_id, ciclo_inicio, conta_mt5_id
        )
        print(f"[DOWNLOAD] liberado_para_download_produto: liberado={liberado}, msg='{msg}', versao={versao.id if versao else None}")

        if not liberado:
            return jsonify({"error": msg}), 403

        response = requests.get(versao.arquivo_url, stream=True, timeout=30)
        response.raise_for_status()

        registrar_download_produto(current_user, versao, ciclo_inicio, conta_mt5_id)

        nome_arquivo = f"dwcapital_{versao.versao}{versao.extensao or '.exe'}"
        return send_file(
            io.BytesIO(response.content),
            as_attachment=True,
            download_name=nome_arquivo,
            mimetype='application/octet-stream'
        )
    except Exception as e:
        print(f"[DOWNLOAD] ERRO: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Erro interno: {str(e)}"}), 500


@licenca_bp.route('/download_demo/<int:produto_id>', methods=['POST'])
@login_required
@limiter.limit("10 per minute")
def baixar_demo(produto_id):
    """
    Download de robô demo (não exige conta MT5).
    Verifica se o cliente já baixou esta versão demo.
    """
    logger.info(f"[DOWNLOAD_DEMO] Requisição recebida: user={current_user.id}, produto={produto_id}")

    produto = ProdutoRobo.query.get_or_404(produto_id)
    if not produto.is_demo:
        return jsonify({"error": "Este produto não é uma versão demo."}), 400

    versao = VersaoRobo.query.filter_by(produto_id=produto_id, publicada=True).first()
    if not versao:
        return jsonify({"error": "Nenhuma versão disponível para este robô demo."}), 404

    # Verifica se o cliente já baixou esta versão demo
    if cliente_ja_baixou_demo(current_user.id, versao.id):
        return jsonify({"error": "Você já baixou esta versão demo. Aguarde uma atualização."}), 403

    # Bloqueio administrativo geral
    if getattr(current_user, 'robot_acesso_bloqueado', False):
        return jsonify({"error": "Acesso ao robô bloqueado pelo administrador."}), 403

    try:
        # Download do arquivo
        response = requests.get(versao.arquivo_url, stream=True, timeout=30)
        response.raise_for_status()

        # Registra o download
        registrar_download_demo(current_user.id, versao.id)

        nome_arquivo = f"dwcapital_demo_{produto.slug}_{versao.versao}{versao.extensao or '.exe'}"
        return send_file(
            io.BytesIO(response.content),
            as_attachment=True,
            download_name=nome_arquivo,
            mimetype='application/octet-stream'
        )
    except Exception as e:
        logger.error(f"[DOWNLOAD_DEMO] ERRO: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Erro interno: {str(e)}"}), 500


@licenca_bp.route('/gerar', methods=['POST'])
@login_required
@limiter.limit("10 per minute", key_func=lambda: current_user.id)
def licenca_gerar():
    if is_licenca_bloqueada(current_user):
        return jsonify({
            "success": False,
            "error": "BLOQUEADO",
            "message": "A geração de licenças está bloqueada para este cliente."
        }), 403

    hoje = datetime.now(tz_br).date()
    if not is_modo_teste() and hoje.weekday() >= 5:
        return jsonify({
            "success": False,
            "error": "DIA_INVALIDO",
            "message": "A geração de licenças semanais só é permitida em dias úteis."
        }), 400

    data = request.get_json()
    conta_mt5_id = data.get('conta_mt5_id') if data else None
    if not conta_mt5_id:
        return jsonify({
            "success": False,
            "error": "PRECISA_CONTA",
            "message": "Selecione uma conta MT5 para gerar a licença."
        }), 400

    conta = ContaMT5Cliente.query.filter_by(id=conta_mt5_id, user_id=current_user.id, ativo=True).first()
    if not conta:
        return jsonify({"success": False, "error": "CONTA_INVALIDA", "message": "Conta MT5 inválida ou inativa."}), 400
    if conta.bloqueada:
        return jsonify({"success": False, "error": "CONTA_BLOQUEADA", "message": "Esta conta MT5 está bloqueada."}), 403

    produto_id = obter_produto_baixado_no_ciclo_atual_por_conta(conta_mt5_id)
    if not produto_id:
        return jsonify({
            "success": False,
            "error": "PRECISA_BAIXAR",
            "message": "Você precisa baixar um robô para esta conta antes de gerar a licença."
        }), 400

    # Lógica para clientes compra
    if current_user.modelo_negocio == 'compra':
        if todas_parcelas_pagas(current_user.id):
            if current_user.produto_vitalicio_id and current_user.produto_vitalicio_id != produto_id:
                return jsonify({"success": False, "error": "VINCULO_PERMANENTE", "message": "Já possui licença vitalícia para outro robô."}), 400

            licenca_vital = obter_licenca_ativa_por_conta(conta_mt5_id, tipo='vitalicia')
            if licenca_vital:
                return jsonify({"success": True, "chave": licenca_vital.chave_licenca, "message": "Licença vitalícia já gerada.", "validade": None, "ja_existente": True})
            else:
                chave, msg, licenca_obj = gerar_licenca_vitalicia(current_user, conta_mt5_id, produto_id)
                if not chave:
                    return jsonify({"success": False, "message": msg}), 400
                if not current_user.produto_vitalicio_id:
                    current_user.produto_vitalicio_id = produto_id
                    db.session.commit()
                return jsonify({"success": True, "chave": chave, "message": "Licença vitalícia gerada.", "validade": None, "ja_existente": False})
        else:
            # Ainda pagando → licença semanal
            chave, msg, licenca_obj, ja_existente = gerar_licenca_comissao(current_user, conta_mt5_id, produto_id)
            if not chave:
                return jsonify({"success": False, "message": msg}), 400
            return jsonify({
                "success": True,
                "chave": chave,
                "message": msg,
                "validade": licenca_obj.data_expiracao.strftime('%d/%m/%Y %H:%M') if licenca_obj.data_expiracao else None,
                "ja_existente": ja_existente
            })

    # Clientes comissão
    chave, msg, licenca_obj, ja_existente = gerar_licenca_comissao(current_user, conta_mt5_id, produto_id)
    if not chave:
        return jsonify({"success": False, "message": msg}), 400
    return jsonify({
        "success": True,
        "chave": chave,
        "message": msg,
        "validade": licenca_obj.data_expiracao.strftime('%d/%m/%Y %H:%M') if licenca_obj.data_expiracao else None,
        "ja_existente": ja_existente
    })


# ========== ROTAS ANTIGAS (adaptadas) ==========
@licenca_bp.route('/robo/download', methods=['POST'])
@login_required
@limiter.limit("3 per minute")
def baixar_robo_antigo():
    from app.models import ProdutoRobo
    primeiro_produto = ProdutoRobo.query.order_by(ProdutoRobo.ordem).first()
    if primeiro_produto:
        from app.services.conta_mt5_service import listar_contas
        contas = listar_contas(current_user.id, apenas_ativas=True)
        if not contas:
            return jsonify({"error": "Nenhuma conta MT5 ativa. Cadastre uma em 'Minhas Contas'."}), 400
        data = {"conta_mt5_id": contas[0].id}
        request._cached_json = (data,)
        return baixar_robo_produto(primeiro_produto.id)
    return jsonify({"error": "Nenhum robô disponível"}), 404


@licenca_bp.route('/status', methods=['GET'])
@login_required
def licenca_status():
    from app.services.conta_mt5_service import listar_contas
    contas = listar_contas(current_user.id, apenas_ativas=True)
    if contas:
        licenca = obter_licenca_ativa_por_conta(contas[0].id)
        if licenca:
            return jsonify({
                "success": True,
                "tem_licenca": True,
                "tipo": licenca.tipo,
                "chave": licenca.chave_licenca,
                "validade": licenca.data_expiracao.strftime('%d/%m/%Y %H:%M') if licenca.data_expiracao else "Vitalícia",
                "status": licenca.status
            })
    return jsonify({"success": True, "tem_licenca": False})


@licenca_bp.route('/visualizar', methods=['POST'])
@login_required
def licenca_visualizar():
    return licenca_gerar()


@licenca_bp.route('/api/salvar_conta_mt5', methods=['POST'])
@login_required
@limiter.limit("5 per minute")
def api_salvar_conta_mt5():
    return jsonify({
        "success": False,
        "message": "Esta funcionalidade foi substituída. Acesse 'Minhas Contas' para gerenciar suas contas MT5."
    }), 400