from datetime import datetime
import os
import io
import logging
import pytz
import requests
from flask import Blueprint, flash, render_template, jsonify, request, send_file
from flask_login import login_required, current_user
from app import db, limiter
from app.models import User, ContaMT5Cliente
from app.services.robo_service import (
    versao_atual, liberado_para_download, registrar_download, historico_downloads_cliente,
    obter_produtos_ativos, liberado_para_download_produto, registrar_download_produto,
    obter_produto_baixado_no_ciclo_atual_por_conta
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
    """Página principal de download – exibe os robôs disponíveis."""
    produtos = obter_produtos_ativos()
    ciclo_inicio, _ = calcular_ciclo_por_data()

    # Se cliente compra já possui vínculo vitalício, bloqueia os outros produtos
    if current_user.modelo_negocio == 'compra' and current_user.produto_vitalicio_id:
        for p in produtos:
            if p['produto'].id != current_user.produto_vitalicio_id:
                p['liberado'] = False
                p['mensagem'] = "Você já possui licença vitalícia para outro robô e não pode mais baixar este."

    # Nota: a verificação de liberado_para_download_produto agora precisa de conta_mt5_id
    # Será preenchida no frontend (select) e validada na rota de download.
    # Na página inicial, apenas listamos os produtos.
    for p in produtos:
        p['liberado'] = True  # Será verificado no download
        p['mensagem'] = "Selecione uma conta para baixar"

    # Histórico de downloads por cliente (agora agregado por conta)
    from app.services.conta_mt5_service import listar_contas
    contas = listar_contas(current_user.id, apenas_ativas=True)
    historico_por_conta = []
    for conta in contas:
        from app.services.robo_service import historico_downloads_por_conta
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
        contas_ativas=contas
    )


@licenca_bp.route('/download/<int:produto_id>', methods=['POST'])
@login_required
@limiter.limit("3 per minute")
def baixar_robo_produto(produto_id):
    """Baixa um robô específico – NÃO exige licença ativa, mas exige conta MT5 selecionada."""
    print(f"[DOWNLOAD] Requisição recebida: user={current_user.id}, produto={produto_id}")
    
    # O frontend agora envia conta_mt5_id no corpo da requisição (JSON)
    data = request.get_json()
    conta_mt5_id = data.get('conta_mt5_id') if data else None
    
    if not conta_mt5_id:
        return jsonify({"error": "Selecione uma conta MT5 para baixar o robô."}), 400
    
    # Valida se a conta pertence ao usuário
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
        print(f"[DOWNLOAD] liberado_para_download_produto retornou: liberado={liberado}, msg='{msg}', versao={versao.id if versao else None}")

        if not liberado:
            print(f"[DOWNLOAD] Bloqueado: {msg}")
            return jsonify({"error": msg}), 403

        print(f"[DOWNLOAD] Baixando arquivo do Cloudinary: {versao.arquivo_url}")
        response = requests.get(versao.arquivo_url, stream=True, timeout=30)
        response.raise_for_status()
        print(f"[DOWNLOAD] Arquivo baixado, tamanho: {len(response.content)} bytes")

        registrar_download_produto(current_user, versao, ciclo_inicio, conta_mt5_id)
        print(f"[DOWNLOAD] Download registrado")

        nome_arquivo = f"dwcapital_{versao.versao}{versao.extensao or '.exe'}"
        print(f"[DOWNLOAD] Enviando arquivo: {nome_arquivo}")

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

    # Recebe a conta selecionada do frontend
    data = request.get_json()
    conta_mt5_id = data.get('conta_mt5_id') if data else None
    
    if not conta_mt5_id:
        return jsonify({
            "success": False,
            "error": "PRECISA_CONTA",
            "message": "Selecione uma conta MT5 para gerar a licença."
        }), 400

    # Valida a conta
    conta = ContaMT5Cliente.query.filter_by(id=conta_mt5_id, user_id=current_user.id, ativo=True).first()
    if not conta:
        return jsonify({
            "success": False,
            "error": "CONTA_INVALIDA",
            "message": "Conta MT5 inválida ou inativa."
        }), 400
    if conta.bloqueada:
        return jsonify({
            "success": False,
            "error": "CONTA_BLOQUEADA",
            "message": "Esta conta MT5 está bloqueada pelo administrador."
        }), 403

    # Descobre qual produto foi baixado para esta conta no ciclo atual
    produto_id = obter_produto_baixado_no_ciclo_atual_por_conta(conta_mt5_id)
    if not produto_id:
        return jsonify({
            "success": False,
            "error": "PRECISA_BAIXAR",
            "message": "Você precisa baixar um robô para esta conta antes de gerar a licença. Escolha um robô na página de download."
        }), 400

    # ==================== LÓGICA PARA CLIENTES COMPRA ====================
    if current_user.modelo_negocio == 'compra':
        if todas_parcelas_pagas(current_user.id):
            # Cliente quite: deve ter licença vitalícia
            if current_user.produto_vitalicio_id and current_user.produto_vitalicio_id != produto_id:
                return jsonify({
                    "success": False,
                    "error": "VINCULO_PERMANENTE",
                    "message": "Você já possui licença vitalícia para outro robô e não pode trocar."
                }), 400

            # Verifica se já existe licença vitalícia ativa para esta conta
            licenca_vital = obter_licenca_ativa_por_conta(conta_mt5_id, tipo='vitalicia')
            if licenca_vital:
                return jsonify({
                    "success": True,
                    "chave": licenca_vital.chave_licenca,
                    "message": "Licença vitalícia já gerada anteriormente para esta conta.",
                    "validade": None,
                    "ja_existente": True
                })
            else:
                chave, msg, licenca_obj = gerar_licenca_vitalicia(
                    current_user, conta_mt5_id, produto_id
                )
                if not chave:
                    return jsonify({"success": False, "message": msg}), 400
                # Vincula o cliente permanentemente a este produto (se ainda não estiver)
                if not current_user.produto_vitalicio_id:
                    current_user.produto_vitalicio_id = produto_id
                    db.session.commit()
                return jsonify({
                    "success": True,
                    "chave": chave,
                    "message": "Licença vitalícia gerada com sucesso para esta conta. Agora você está vinculado permanentemente a este robô.",
                    "validade": None,
                    "ja_existente": False
                })
        else:
            # Ainda pagando → licença semanal
            chave, msg, licenca_obj, ja_existente = gerar_licenca_comissao(
                current_user, conta_mt5_id, produto_id
            )
            if not chave:
                return jsonify({"success": False, "message": msg}), 400
            return jsonify({
                "success": True,
                "chave": chave,
                "message": msg,
                "validade": licenca_obj.data_expiracao.strftime('%d/%m/%Y %H:%M') if licenca_obj.data_expiracao else None,
                "ja_existente": ja_existente
            })

    # ==================== CLIENTES COMISSÃO (padrão) ====================
    chave, msg, licenca_obj, ja_existente = gerar_licenca_comissao(
        current_user, conta_mt5_id, produto_id
    )
    if not chave:
        return jsonify({"success": False, "message": msg}), 400
    return jsonify({
        "success": True,
        "chave": chave,
        "message": msg,
        "validade": licenca_obj.data_expiracao.strftime('%d/%m/%Y %H:%M') if licenca_obj.data_expiracao else None,
        "ja_existente": ja_existente
    })


# ========== ROTAS ANTIGAS (adaptadas para compatibilidade) ==========
@licenca_bp.route('/robo/download', methods=['POST'])
@login_required
@limiter.limit("3 per minute")
def baixar_robo_antigo():
    from app.models import ProdutoRobo
    primeiro_produto = ProdutoRobo.query.order_by(ProdutoRobo.ordem).first()
    if primeiro_produto:
        # Tenta usar a primeira conta ativa do cliente (fallback)
        from app.services.conta_mt5_service import listar_contas
        contas = listar_contas(current_user.id, apenas_ativas=True)
        if not contas:
            return jsonify({"error": "Você não possui nenhuma conta MT5 ativa. Cadastre uma em 'Minhas Contas'."}), 400
        # Chama a nova rota com a primeira conta
        data = {"conta_mt5_id": contas[0].id}
        request._cached_json = (data,)
        return baixar_robo_produto(primeiro_produto.id)
    return jsonify({"error": "Nenhum robô disponível"}), 404


@licenca_bp.route('/status', methods=['GET'])
@login_required
def licenca_status():
    # Retorna status da primeira conta ativa (fallback)
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
    # Esta rota está obsoleta com o novo modelo de múltiplas contas.
    # Mantida para compatibilidade, mas orienta o usuário a usar a página de contas.
    return jsonify({
        "success": False,
        "message": "Esta funcionalidade foi substituída. Acesse 'Minhas Contas' para gerenciar suas contas MT5."
    }), 400