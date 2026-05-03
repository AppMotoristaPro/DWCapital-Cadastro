from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from app.models import User, Fatura
from app import db
from datetime import datetime, timedelta

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

@admin_bp.route('/')
@login_required
def dashboard():
    if current_user.role != 'admin': return redirect(url_for('client.dashboard'))
    clientes = User.query.filter_by(role='cliente').order_by(User.id.desc()).all()
    return render_template('admin/index.html', user=current_user, clientes=clientes)

@admin_bp.route('/liberar_cpf', methods=['POST'])
@login_required
def liberar_cpf():
    cpf = ''.join(filter(str.isdigit, request.form.get('cpf')))
    if not User.query.filter_by(cpf=cpf).first():
        novo = User(cpf=cpf, role='cliente', status_acesso='pendente_cadastro')
        db.session.add(novo)
        db.session.flush()
        
        # Gera fatura da semana atual
        inicio = datetime.now().date() - timedelta(days=datetime.now().weekday())
        fim = inicio + timedelta(days=6)
        fatura = Fatura(user_id=novo.id, data_inicio=inicio, data_fim=fim)
        db.session.add(fatura)
        db.session.commit()
        flash(f'CPF {cpf} liberado!')
    return redirect(url_for('admin.dashboard'))

