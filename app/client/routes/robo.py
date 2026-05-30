from flask import render_template, request, jsonify, redirect, url_for, flash, current_app, send_file
from flask_login import login_required, current_user
from app.client import client_bp

# ==========================================
# Rotas que serão movidas para cá:
# - /robo (GET)
# - /robo/download (POST)
# - /faturas/gerar_licenca (POST)
# ==========================================

# @client_bp.route('/robo')
# @login_required
# def robo_download():
#     pass

# @client_bp.route('/robo/download', methods=['POST'])
# @login_required
# def baixar_robo():
#     pass

# @client_bp.route('/faturas/gerar_licenca', methods=['POST'])
# @login_required
# def gerar_licenca():
#     pass
