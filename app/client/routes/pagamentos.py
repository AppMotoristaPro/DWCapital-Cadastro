from flask import render_template, request, jsonify, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from app.client import client_bp

# ==========================================
# Rotas que serão movidas para cá:
# - /bloqueio_pagamento (GET)
# - /faturas/gerar_pix/<int:fatura_id> (POST)
# - /licencas/gerar_pix/<int:parcela_id> (POST)
# - /api/status_fatura/<int:fatura_id> (GET)
# - /api/status_licenca/<int:parcela_id> (GET)
# ==========================================

# @client_bp.route('/bloqueio_pagamento')
# @login_required
# def bloqueio_pagamento():
#     pass

# @client_bp.route('/faturas/gerar_pix/<int:fatura_id>', methods=['POST'])
# @login_required
# def gerar_pix_fatura(fatura_id):
#     pass

# @client_bp.route('/licencas/gerar_pix/<int:parcela_id>', methods=['POST'])
# @login_required
# def gerar_pix_licenca(parcela_id):
#     pass

# @client_bp.route('/api/status_fatura/<int:fatura_id>')
# @login_required
# def status_fatura_api(fatura_id):
#     pass

# @client_bp.route('/api/status_licenca/<int:parcela_id>')
# @login_required
# def status_licenca_api(parcela_id):
#     pass
