from flask import render_template, request, jsonify, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from app.client import client_bp

# ==========================================
# Rotas que serão movidas para cá:
# - /dashboard (GET)
# - /dados_pessoais (GET)
# ==========================================

# @client_bp.route('/dashboard')
# @login_required
# def dashboard():
#     pass

# @client_bp.route('/dados_pessoais')
# @login_required
# def dados_pessoais():
#     pass
