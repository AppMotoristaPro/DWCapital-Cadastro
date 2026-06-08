from flask import Blueprint, render_template, jsonify, request, url_for
from flask_login import login_required, current_user
from app import db, limiter
from app.models import User, ParcelaCompra, PremioSolicitacao
from app.services.parcela_service import calcular_premio_acumulado

indicacao_bp = Blueprint('indicacao', __name__, url_prefix='/indicacao')


@indicacao_bp.route('/')
@login_required
def indicacoes():
    """Tela do indicador: mostra link de indicação, lista de indicados e progresso do prêmio."""
    # Lista de clientes indicados por este usuário
    indicados = User.query.filter_by(indicador_id=current_user.id, is_indicado=True).all()
    
    dados_indicados = []
    for ind in indicados:
        parcela_entrada = ParcelaCompra.query.filter_by(user_id=ind.id, ordem=1).first()
        parcelas_semanais = ParcelaCompra.query.filter(
            ParcelaCompra.user_id == ind.id,
            ParcelaCompra.ordem >= 2
        ).order_by(ParcelaCompra.ordem).all()
        
        pagas = sum(1 for p in parcelas_semanais if p.status == 'pago')
        total = len(parcelas_semanais)
        
        dados_indicados.append({
            'cliente': ind,
            'entrada_paga': parcela_entrada and parcela_entrada.status == 'pago',
            'parcelas_pagas': pagas,
            'total_parcelas': total,
            'valor_pendente': sum(p.valor for p in parcelas_semanais if p.status == 'pendente')
        })
    
    # Link de indicação (para ser copiado)
    link_indicacao = url_for('auth.indicacao', ref=current_user.id, _external=True)
    
    # Cálculo do prêmio acumulado
    premio = calcular_premio_acumulado(current_user.id)
    
    return render_template('client/indicacoes.html',
                           indicados=dados_indicados,
                           link_indicacao=link_indicacao,
                           premio=premio)


@indicacao_bp.route('/solicitar', methods=['POST'])
@login_required
@limiter.limit("5 per minute")
def solicitar_premio():
    """Cliente solicita o prêmio (R$ 1.000 por indicação elegível, total acumulado)."""
    data = request.get_json()
    tipo = data.get('tipo')
    
    if tipo not in ['dinheiro', 'vitalicia']:
        return jsonify({"success": False, "message": "Tipo de prêmio inválido."}), 400
    
    # Verifica elegibilidade atual
    premio = calcular_premio_acumulado(current_user.id)
    if not premio['pode_solicitar']:
        return jsonify({"success": False, "message": "Você ainda não atingiu 7 indicações com entrada paga."}), 400
    
    # Verifica se já existe uma solicitação pendente
    solicitacao_existente = PremioSolicitacao.query.filter_by(
        user_id=current_user.id,
        status='pendente'
    ).first()
    if solicitacao_existente:
        return jsonify({"success": False, "message": "Você já possui uma solicitação de prêmio pendente."}), 400
    
    # Valor do prêmio (acumulado) se for dinheiro, caso contrário 0
    valor_final = premio['valor_acumulado'] if tipo == 'dinheiro' else 0.0
    
    nova_solicitacao = PremioSolicitacao(
        user_id=current_user.id,
        tipo_premio=tipo,
        status='pendente',
        valor=valor_final
    )
    db.session.add(nova_solicitacao)
    db.session.commit()
    
    return jsonify({"success": True, "message": f"Solicitação de R$ {valor_final:,.2f} enviada com sucesso! Aguarde a aprovação do administrador."})