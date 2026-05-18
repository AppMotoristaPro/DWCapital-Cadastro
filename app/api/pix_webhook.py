from flask import Blueprint, request, jsonify
from app import db
from app.models import Fatura, ParcelaCompra
from datetime import datetime
import pytz

tz_br = pytz.timezone('America/Sao_Paulo')
api_bp = Blueprint('api_pix', __name__, url_prefix='/api')

@api_bp.route('/webhook/pix', methods=['POST'])
def webhook_pix():
    data = request.get_json()
    
    # Intercepta o txid de forma flexível caso venha na raiz ou dentro da lista de pix
    txid = None
    if data:
        if 'txid' in data:
            txid = data['txid']
        elif 'pix' in data and isinstance(data['pix'], list) and len(data['pix']) > 0:
            txid = data['pix'][0].get('txid')

    if not txid:
        return jsonify({"status": "ignorado", "reason": "txid nao localizado no payload"}), 200

    # 1. Verifica se o txid pertence a uma Comissão Semanal (Fatura)
    fatura = Fatura.query.filter_by(txid_pix=txid).first()
    if fatura:
        fatura.status = 'pago'
        db.session.commit()
        return jsonify({"status": "sucesso", "tipo": "comissao_semanal"}), 200

    # 2. Verifica se o txid pertence a uma Licença de Robô (ParcelaCompra)
    parcela = ParcelaCompra.query.filter_by(txid_pix=txid).first()
    if parcela:
        parcela.status = 'pago'
        parcela.data_pagamento = datetime.now(tz_br)
        db.session.commit()
        return jsonify({"status": "sucesso", "tipo": "parcela_licenca"}), 200

    return jsonify({"status": "nao_encontrado", "txid": txid}), 200