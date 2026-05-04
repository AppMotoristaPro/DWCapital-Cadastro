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
    clientes = User.query.filter_by(role='cliente').all()
    return render_template('admin/index.html', clientes=clientes)

@admin_bp.route('/liberar_cliente', methods=['POST'])
@login_required
def liberar_cliente():
    cpf = ''.join(filter(str.isdigit, request.form.get('cpf')))
    if not User.query.filter_by(cpf=cpf).first():
        novo = User(
            cpf=cpf, 
            nome=request.form.get('nome'),
            role='cliente',
            status_acesso='pendente_cadastro',
            corretora=request.form.get('corretora'),
            capital_alocado=float(request.form.get('valor_alocado') or 0.0)
        )
        db.session.add(novo)
        db.session.flush()
        
        # Gera a primeira fatura
        inicio = datetime.now().date() - timedelta(days=datetime.now().weekday())
        fatura = Fatura(user_id=novo.id, data_inicio=inicio, data_fim=inicio+timedelta(days=6))
        db.session.add(fatura)
        db.session.commit()
        flash('CPF Liberado para o cliente!')
    return redirect(url_for('admin.dashboard'))

