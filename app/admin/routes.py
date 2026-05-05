from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from app.models import User, Fatura, FaturaDiaria
from app import db

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

@admin_bp.route('/pagamentos/<int:id>')
@login_required
def pagamentos_cliente(id):
    cliente = User.query.get_or_404(id)
    faturas = Fatura.query.filter_by(user_id=cliente.id).order_by(Fatura.data_inicio.desc()).all()
    return render_template('admin/pagamentos_cliente.html', cliente=cliente, faturas=faturas)

@admin_bp.route('/pagamentos/status/<int:fatura_id>', methods=['POST'])
@login_required
def status_pagamento(fatura_id):
    fatura = Fatura.query.get_or_404(fatura_id)
    fatura.status = request.form.get('status')
    db.session.commit()
    return redirect(url_for('admin.pagamentos_cliente', id=fatura.user_id))

@admin_bp.route('/pagamentos/rejeitar/<int:dia_id>', methods=['POST'])
@login_required
def rejeitar_relatorio(dia_id):
    dia = FaturaDiaria.query.get_or_404(dia_id)
    dia.arquivo_pdf, dia.status = None, 'pendente'
    db.session.commit()
    return redirect(url_for('admin.pagamentos_cliente', id=dia.fatura_semanal.user_id))

