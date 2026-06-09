import logging
from io import BytesIO
from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
import cloudinary.uploader
from app import db, limiter
from app.models import FaturaDiaria
from app.services.fatura_service import atualizar_totais_semana
from app.services.html_relatorio_service import validar_estrutura_html_mt5, extrair_datas_operacoes

logger = logging.getLogger(__name__)
nao_operei_bp = Blueprint('nao_operei', __name__, url_prefix='/portal/faturas')


@nao_operei_bp.route('/nao_operei_html/<int:dia_id>', methods=['POST'])
@login_required
@limiter.limit("5 per minute")
def nao_operei_html(dia_id):
    dia = FaturaDiaria.query.get_or_404(dia_id)
    if dia.fatura_semanal.user_id != current_user.id:
        return jsonify({'success': False, 'error': 'Acesso negado.'}), 403

    if dia.status != 'pendente':
        return jsonify({'success': False, 'error': 'Dia já processado.'}), 400

    arquivo = request.files.get('relatorio_html')
    if not arquivo or not arquivo.filename.endswith(('.html', '.htm')):
        return jsonify({'success': False, 'error': 'Arquivo HTML inválido.'}), 400

    conteudo = arquivo.read()

    # 1. Validar estrutura
    valido, msg = validar_estrutura_html_mt5(conteudo)
    if not valido:
        return jsonify({'success': False, 'error': 'ESTRUTURA_INVALIDA', 'message': msg}), 400

    # 2. Extrair datas das operações
    datas_operacoes = extrair_datas_operacoes(conteudo)
    data_alvo_str = dia.data_pregao.isoformat()

    # 3. Verificar se há operações em outras datas
    datas_erradas = [d for d in datas_operacoes if d != data_alvo_str]
    if datas_erradas:
        return jsonify({
            'success': False,
            'error': 'DATAS_DIFERENTES',
            'message': f'O relatório contém operações em outras datas: {", ".join(datas_erradas)}. Gere um relatório apenas para o dia {data_alvo_str}.'
        }), 400

    # 4. Operação na data alvo?
    teve_operacao = data_alvo_str in datas_operacoes

    # 5. Upload para Cloudinary
    arquivo_stream = BytesIO(conteudo)
    arquivo_stream.name = arquivo.filename
    try:
        upload_result = cloudinary.uploader.upload(
            arquivo_stream,
            folder="dwcapital/relatorios_nao_operei",
            resource_type="raw",
            public_id=f"nao_operei_{current_user.id}_{dia.id}_{dia.data_pregao.isoformat()}"
        )
        relatorio_url = upload_result.get('secure_url')
    except Exception as e:
        return jsonify({'success': False, 'error': 'UPLOAD_FAIL', 'message': str(e)}), 500

    # 6. Atualizar o dia
    dia.relatorio_html_url = relatorio_url
    dia.motivo_isencao = 'nao_operou'
    dia.operacao_detectada = teve_operacao
    dia.is_isento = True
    dia.status = 'isento'
    dia.zerar_valores(isentar=True)
    db.session.commit()
    atualizar_totais_semana(dia.fatura_semanal)

    if teve_operacao:
        return jsonify({'success': True, 'warning': 'Dia isentado, mas o sistema identificou operações neste dia. O relatório será auditado pelo administrador.'})
    else:
        return jsonify({'success': True, 'message': 'Dia isentado com sucesso!'})