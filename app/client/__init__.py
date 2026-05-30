from flask import Blueprint, redirect, url_for, session, request
from flask_login import current_user
from app.models import DocumentoCliente, ParcelaCompra
from datetime import datetime
import pytz

tz_br = pytz.timezone('America/Sao_Paulo')

client_bp = Blueprint('client', __name__, url_prefix='/portal')

@client_bp.before_request
def check_paywall():
    # Rotas liberadas sem bloqueio
    if request.endpoint == 'client.buscar_dados_whatsapp':
        return

    if not current_user.is_authenticated:
        return
    if getattr(current_user, 'precisa_trocar_senha', False):
        return
        
    pendentes = DocumentoCliente.query.filter(
        DocumentoCliente.user_id == current_user.id,
        DocumentoCliente.status.in_(['na_fila', 'pendente', 'processando'])
    ).first()

    if pendentes:
        if request.endpoint not in ['client.assinar_termo', 'client.api_status_assinatura', 'auth.logout']:
            return redirect(url_for('client.assinar_termo'))
        return 
            
    if request.endpoint not in ['client.bloqueio_pagamento', 'client.gerar_pix_licenca', 'client.status_licenca_api', 'auth.logout']:
        if getattr(current_user, 'modelo_negocio', 'comissao') == 'compra':
            hoje = datetime.now(tz_br).date()
            parcela_pendente = ParcelaCompra.query.filter(
                ParcelaCompra.user_id == current_user.id,
                ParcelaCompra.status == 'pendente',
                ParcelaCompra.data_vencimento <= hoje
            ).order_by(ParcelaCompra.ordem.asc()).first()
            
            if parcela_pendente:
                return redirect(url_for('client.bloqueio_pagamento'))

# Importa os módulos de rota (cada um se registrará via decorador)
from app.client.routes import dashboard, faturas, documentos, pagamentos, robo, ajuda
