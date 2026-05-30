from flask import render_template, request, jsonify, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from app.client import client_bp

# ==========================================
# Rotas que serão movidas para cá:
# - /ajuda (GET)
# - /api/buscar_dados_whatsapp (POST)
# ==========================================

# @client_bp.route('/ajuda')
# @login_required
# def ajuda():
#     pass

# @client_bp.route('/api/buscar_dados_whatsapp', methods=['POST'])
# def buscar_dados_whatsapp():
#     pass
