from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from app import db

client_bp = Blueprint('client', __name__)

@client_bp.route('/')
def index():
    return redirect(url_for('auth.login'))

@client_bp.route('/dashboard')
@login_required
def dashboard():
    return render_template('client/index.html', user=current_user)

@client_bp.route('/faturas')
@login_required
def faturas():
    # Vamos criar dados fictícios apenas para desenhar a tela agora.
    # Na fase final, isso virá direto do banco de dados (Neon).
    faturas_mock = [
        {"id": 1, "semana": "01/02/2026 até 07/02/2026", "status": "pendente"},
        {"id": 2, "semana": "08/02/2026 até 14/02/2026", "status": "pendente"}
    ]
    return render_template('client/faturas.html', user=current_user, faturas=faturas_mock)

@client_bp.route('/perfil', methods=['GET', 'POST'])
@login_required
def perfil():
    if request.method == 'POST':
        # Recebendo os dados do formulário
        current_user.nome = request.form.get('nome')
        current_user.corretora = request.form.get('corretora')
        current_user.perfil_risco = request.form.get('perfil_risco')
        
        db.session.commit()
        flash('Dados atualizados com sucesso!', 'success')
        return redirect(url_for('client.perfil'))
        
    return render_template('client/perfil.html', user=current_user)

