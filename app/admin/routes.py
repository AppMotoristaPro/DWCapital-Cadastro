from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from app.models import User, Fatura
from app import db
from functools import wraps
from datetime import datetime, timedelta

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

def admin_required(f):
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if current_user.role != 'admin':
            flash('Acesso negado.')
            return redirect(url_for('client.dashboard'))
        return f(*args, **kwargs)
    return decorated_function

@admin_bp.route('/')
@admin_required
def dashboard():
    clientes = User.query.filter_by(role='cliente').order_by(User.id.desc()).all()
    return render_template('admin/index.html', user=current_user, clientes=clientes)

@admin_bp.route('/liberar_cpf', methods=['POST'])
@admin_required
def liberar_cpf():
    cpf = ''.join(filter(str.isdigit, request.form.get('cpf')))
    
    if len(cpf) != 11:
        flash('CPF inválido.')
        return redirect(url_for('admin.dashboard'))

    usuario_existente = User.query.filter_by(cpf=cpf).first()
    
    if usuario_existente:
        flash('Este CPF já existe.')
    else:
        # 1. Cria o usuário liberado
        novo_cliente = User(cpf=cpf, role='cliente', status_acesso='pendente_cadastro')
        db.session.add(novo_cliente)
        db.session.flush() # Gera o ID do cliente para a fatura

        # 2. Cria automaticamente a fatura da semana atual para ele já poder usar
        hoje = datetime.now().date()
        # Define o início da semana (segunda-feira) e o fim (domingo ou dia do pregão)
        inicio_semana = hoje - timedelta(days=hoje.weekday())
        fim_semana = inicio_semana + timedelta(days=6)

        nova_fatura = Fatura(
            user_id=novo_cliente.id,
            data_inicio=inicio_semana,
            data_fim=fim_semana,
            status='pendente'
        )
        
        db.session.add(nova_fatura)
        db.session.commit()
        flash(f'CPF {cpf} liberado e fatura semanal gerada com sucesso!')
        
    return redirect(url_for('admin.dashboard'))

