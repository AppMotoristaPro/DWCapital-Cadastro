from flask import Blueprint, render_template, redirect, url_for
from flask_login import login_required

client_bp = Blueprint('client', __name__)

@client_bp.route('/')
def index():
    # Ao acessar a raiz do site, força o redirecionamento para o login
    return redirect(url_for('auth.login'))

@client_bp.route('/dashboard')
@login_required
def dashboard():
    # Tela principal do cliente logado
    return render_template('client/index.html')

