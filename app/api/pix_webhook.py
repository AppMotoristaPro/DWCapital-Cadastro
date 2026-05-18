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

    if not data:
        return jsonify({"status": "ignorado", "reason": "payload vazio"}), 200

    txids_processados = []

    # O Banco Inter envia um array de objetos dentro da chave 'pix'.
    # Nossa lógica agora varre a lista completa para evitar perda de pagamentos simultâneos.
    lista_pix = data.get('pix', [])
    
    # Tratamento de segurança para aceitar também testes manuais isolados (como o do Postman)
    if 'txid' in data:
        lista_pix.append({"txid": data['txid']})

    if not lista_pix:
        return jsonify({"status": "ignorado", "reason": "txid nao localizado no payload"}), 200

    for item in lista_pix:
        txid = item.get('txid')
        if not txid:
            continue

        # 1. Verifica se o txid pertence a uma Comissão Semanal (Fatura)
        fatura = Fatura.query.filter_by(txid_pix=txid).first()
        if fatura:
            fatura.status = 'pago'
            txids_processados.append({"txid": txid, "tipo": "comissao_semanal"})
            continue

        # 2. Verifica se o txid pertence a uma Licença de Robô (ParcelaCompra)
        parcela = ParcelaCompra.query.filter_by(txid_pix=txid).first()
        if parcela:
            parcela.status = 'pago'
            parcela.data_pagamento = datetime.now(tz_br)
            txids_processados.append({"txid": txid, "tipo": "parcela_licenca"})
            continue

    # Faz o commit de todas as baixas encontradas na varredura de uma só vez
    db.session.commit()

    return jsonify({
        "status": "sucesso", 
        "processados": txids_processados
    }), 200