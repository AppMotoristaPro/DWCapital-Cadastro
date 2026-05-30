from flask import render_template, request, jsonify, redirect, url_for, flash, current_app, abort
from flask_login import login_required, current_user
from app.client import client_bp

# ==========================================
# Rotas que serão movidas para cá:
# - /assinar (GET)
# - /api/status_assinatura (GET)
# - /documentos (GET)
# - /documentos/visualizar/<int:doc_id> (GET)
# - /api/status_documento/<int:doc_id> (GET)
# ==========================================

# @client_bp.route('/assinar')
# @login_required
# def assinar_termo():
#     pass

# @client_bp.route('/api/status_assinatura')
# @login_required
# def api_status_assinatura():
#     pass

# @client_bp.route('/documentos')
# @login_required
# def documentos():
#     pass

# @client_bp.route('/documentos/visualizar/<int:doc_id>')
# @login_required
# def visualizar_documento(doc_id):
#     pass

# @client_bp.route('/api/status_documento/<int:doc_id>')
# @login_required
# def api_status_documento(doc_id):
#     pass
