from flask import render_template, request, jsonify, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from app.client import client_bp

# ==========================================
# Rotas que serão movidas para cá:
# - /faturas (GET, POST)
# - /faturas/remover/<int:dia_id> (POST)
# - /faturas/comprovante/<int:fatura_id> (POST)
# ==========================================

# @client_bp.route('/faturas', methods=['GET', 'POST'])
# @login_required
# def faturas():
#     pass

# @client_bp.route('/faturas/remover/<int:dia_id>', methods=['POST'])
# @login_required
# def remover_fatura(dia_id):
#     pass

# @client_bp.route('/faturas/comprovante/<int:fatura_id>', methods=['POST'])
# @login_required
# def enviar_comprovante(fatura_id):
#     pass
